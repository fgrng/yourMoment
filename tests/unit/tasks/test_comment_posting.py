from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime

import pytest
from celery.utils.threads import LocalStack
from sqlalchemy import Select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.models.mymoment_login import MyMomentLogin
from src.platforms import PlatformAuthError, PlatformUnavailable, PostedComment, use_adapter
from src.tasks import comment_posting
from src.tasks.comment_posting import CommentPostingTask
from tests.fixtures.assertions import assert_task_result_shape
from tests.fixtures.builders import build_scenario
from tests.fixtures.factories.comments import create_generated_ai_comment
from tests.support.platform import FakeConnection, FakePlatform


pytestmark = [pytest.mark.unit, pytest.mark.database, pytest.mark.celery, pytest.mark.web_scraping]


def _bind_task_sessions(task, db_engine):
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _get_async_session():
        return session_factory()

    task.get_async_session = _get_async_session
    return task


def _attach_retry_context(task, *, retries=0, max_retries=3, retry_callback=None):
    if task.request_stack is None:
        task.request_stack = LocalStack()
    task.push_request(id="fixture-task-id", retries=retries)
    task.max_retries = max_retries
    task.retry_calls = []

    def _retry(*, exc, countdown):
        task.retry_calls.append({"exc": exc, "countdown": countdown})
        if retry_callback is not None:
            return retry_callback(exc=exc, countdown=countdown)
        raise AssertionError("retry() should not have been called")

    task.retry = _retry
    return task


async def _run_post_comment_task(task, ai_comment_id, *, retries=0, max_retries=3, retry_callback=None):
    def _call():
        _attach_retry_context(
            task,
            retries=retries,
            max_retries=max_retries,
            retry_callback=retry_callback,
        )
        try:
            return comment_posting.post_comment_for_article.run.__func__(
                task,
                str(ai_comment_id),
            )
        finally:
            task.pop_request()

    return await asyncio.to_thread(_call)


async def _run_batch_task(task, process_id):
    batch_task_body = type(comment_posting.post_comments_for_articles._get_current_object()).run  # without autoretry
    return await asyncio.to_thread(batch_task_body, task, str(process_id))


async def _generated_comment_on_platform(db_session, fake_platform, **ai_comment):
    scenario = await build_scenario("generated_not_posted", db_session, overrides={"ai_comment": ai_comment})
    await db_session.commit()
    fake_platform.add_article(scenario["ai_comment"].mymoment_article_id)
    return scenario


async def test_post_single_comment_transitions_generated_to_posted(db_session, db_engine, fake_platform):
    scenario = await _generated_comment_on_platform(db_session, fake_platform)

    task = _bind_task_sessions(CommentPostingTask(), db_engine)
    result = await _run_post_comment_task(task, scenario["ai_comment"].id)

    assert_task_result_shape(result, required_keys=("status", "ai_comment_id"), expected_status="posted")
    await db_session.refresh(scenario["ai_comment"])
    assert scenario["ai_comment"].status == "posted"
    assert scenario["ai_comment"].posted_at is not None


async def test_post_single_comment_publishes_the_text_with_ai_prefix(db_session, db_engine, fake_platform):
    scenario = await _generated_comment_on_platform(
        db_session, fake_platform, comment_content="<p>Gut gemacht.</p>", is_hidden=True
    )

    task = _bind_task_sessions(CommentPostingTask(), db_engine)
    await _run_post_comment_task(task, scenario["ai_comment"].id)

    [posted] = fake_platform.posted_comments
    assert (posted.ref.id, posted.text, posted.hidden, posted.account.id) == (
        scenario["ai_comment"].mymoment_article_id,
        "<p>[Dieser Kommentar stammt von einem KI-ChatBot.]</p><p>Gut gemacht.</p>",
        True,
        scenario["login"].id,
    )


async def test_post_single_comment_stores_a_placeholder_comment_id(db_session, db_engine, fake_platform):
    scenario = await _generated_comment_on_platform(db_session, fake_platform)

    task = _bind_task_sessions(CommentPostingTask(), db_engine)
    await _run_post_comment_task(task, scenario["ai_comment"].id)

    await db_session.refresh(scenario["ai_comment"])
    assert scenario["ai_comment"].mymoment_comment_id.startswith(f"{scenario['ai_comment'].mymoment_article_id}-")


async def test_post_single_comment_skips_generate_only_processes(db_session, db_engine):
    scenario = await build_scenario("generate_only_process", db_session)
    await db_session.commit()

    task = _bind_task_sessions(CommentPostingTask(), db_engine)
    result = await task._post_single_comment_async(scenario["ai_comment"].id)

    assert result["status"] == "skipped"
    assert result["reason"] == "generate_only"


async def test_claim_comment_for_posting_is_atomic_no_op_after_first_claim(db_session, db_engine):
    scenario = await build_scenario("generated_not_posted", db_session)
    await db_session.commit()

    task = _bind_task_sessions(CommentPostingTask(), db_engine)
    claimed = await task._claim_comment_for_posting(
        scenario["ai_comment"].id,
    )
    claimed_again = await task._claim_comment_for_posting(
        scenario["ai_comment"].id,
    )

    assert claimed is True
    assert claimed_again is False
    await db_session.refresh(scenario["ai_comment"])
    assert scenario["ai_comment"].status == "posting"
    assert scenario["ai_comment"].mymoment_comment_id is None
    assert scenario["ai_comment"].posted_at is None


async def test_finalize_posted_comment_updates_claimed_rows(db_session, db_engine):
    scenario = await build_scenario("generated_not_posted", db_session)
    await db_session.commit()

    task = _bind_task_sessions(CommentPostingTask(), db_engine)
    claimed = await task._claim_comment_for_posting(
        scenario["ai_comment"].id,
    )
    assert claimed is True

    finalized_at = datetime.utcnow()
    updated = await task._finalize_posted_comment(
        scenario["ai_comment"].id,
        comment_id="replacement-comment-id",
        posted_at=finalized_at,
    )

    assert updated is True
    await db_session.refresh(scenario["ai_comment"])
    assert scenario["ai_comment"].status == "posted"
    assert scenario["ai_comment"].mymoment_comment_id == "replacement-comment-id"
    assert scenario["ai_comment"].posted_at == finalized_at


async def test_mark_comment_failed_persists_posting_failure_metadata(db_session, db_engine):
    scenario = await build_scenario("generated_not_posted", db_session)
    await db_session.commit()

    task = _bind_task_sessions(CommentPostingTask(), db_engine)
    await task._claim_comment_for_posting(
        scenario["ai_comment"].id,
    )
    await task._mark_comment_failed(
        scenario["ai_comment"].id,
        "Max retries exhausted: posting failed hard",
        expected_status="posting",
    )

    await db_session.refresh(scenario["ai_comment"])
    assert scenario["ai_comment"].status == "failed"
    assert scenario["ai_comment"].error_message == "Max retries exhausted: posting failed hard"
    assert scenario["ai_comment"].failed_at is not None
    assert scenario["ai_comment"].retry_count == 1
    assert scenario["ai_comment"].mymoment_comment_id is None
    assert scenario["ai_comment"].posted_at is None


async def test_unavailable_platform_reverts_the_claim_and_retries(db_session, db_engine, fake_platform):
    scenario = await _generated_comment_on_platform(db_session, fake_platform)
    fake_platform.fail("post_comment", PlatformUnavailable("timeout"))

    class RetryScheduled(Exception):
        pass

    def _raise_retry(*, exc, countdown):
        raise RetryScheduled()

    task = _bind_task_sessions(CommentPostingTask(), db_engine)
    with pytest.raises(RetryScheduled):
        await _run_post_comment_task(task, scenario["ai_comment"].id, retry_callback=_raise_retry)

    assert task.retry_calls[0]["countdown"] == 60
    await db_session.refresh(scenario["ai_comment"])
    assert scenario["ai_comment"].status == "generated"
    assert scenario["ai_comment"].mymoment_comment_id is None
    assert scenario["ai_comment"].posted_at is None
    assert scenario["ai_comment"].failed_at is None


async def test_unavailable_platform_marks_failed_once_retries_are_exhausted(db_session, db_engine, fake_platform):
    scenario = await _generated_comment_on_platform(db_session, fake_platform)
    fake_platform.fail("connect", PlatformUnavailable("connection refused"))

    task = _bind_task_sessions(CommentPostingTask(), db_engine)
    result = await _run_post_comment_task(task, scenario["ai_comment"].id, retries=3, max_retries=3)

    assert (result["status"], task.retry_calls) == ("failed", [])
    await db_session.refresh(scenario["ai_comment"])
    assert scenario["ai_comment"].status == "failed"
    assert scenario["ai_comment"].error_message == "Max retries exhausted: connection refused"
    assert scenario["ai_comment"].retry_count == 1


async def test_wrong_credentials_mark_failed_without_retry(db_session, db_engine, fake_platform):
    scenario = await _generated_comment_on_platform(db_session, fake_platform)
    fake_platform.fail("connect", PlatformAuthError("wrong password"))

    task = _bind_task_sessions(CommentPostingTask(), db_engine)
    result = await _run_post_comment_task(task, scenario["ai_comment"].id)

    assert (result["status"], task.retry_calls) == ("failed", [])
    await db_session.refresh(scenario["ai_comment"])
    assert scenario["ai_comment"].status == "failed"
    assert scenario["ai_comment"].error_message == "wrong password"


async def test_rejected_comment_is_marked_failed_without_retry(db_session, db_engine, fake_platform):
    scenario = await _generated_comment_on_platform(db_session, fake_platform)
    fake_platform.reject_comments(scenario["ai_comment"].mymoment_article_id)

    task = _bind_task_sessions(CommentPostingTask(), db_engine)
    result = await _run_post_comment_task(task, scenario["ai_comment"].id)

    assert (result["status"], task.retry_calls) == ("failed", [])
    await db_session.refresh(scenario["ai_comment"])
    assert scenario["ai_comment"].status == "failed"
    assert scenario["ai_comment"].posted_at is None
    assert fake_platform.posted_comments == []


async def test_inactive_platform_account_marks_failed_without_retry(db_session, db_engine, fake_platform):
    scenario = await build_scenario("generated_not_posted", db_session, overrides={"login": {"is_active": False}})
    await db_session.commit()

    task = _bind_task_sessions(CommentPostingTask(), db_engine)
    result = await _run_post_comment_task(task, scenario["ai_comment"].id)

    assert (result["status"], task.retry_calls) == ("failed", [])
    await db_session.refresh(scenario["ai_comment"])
    assert scenario["ai_comment"].status == "failed"


class _GatedConnection(FakeConnection):
    async def post_comment(self, ref, text, *, hidden=False) -> PostedComment:
        self._platform.post_started.set()
        await self._platform.release.wait()
        return await super().post_comment(ref, text, hidden=hidden)


class _GatedPlatform(FakePlatform):
    """Holds every post until `release` is set, to overlap two posting attempts."""

    def __init__(self) -> None:
        super().__init__()
        self.post_started = asyncio.Event()
        self.release = asyncio.Event()

    @asynccontextmanager
    async def connect(self, account):
        yield _GatedConnection(self, account)


async def test_post_single_comment_concurrent_claim_allows_only_one_post(db_session, db_engine):
    platform = _GatedPlatform()
    use_adapter(platform)
    try:
        scenario = await _generated_comment_on_platform(db_session, platform)

        task = _bind_task_sessions(CommentPostingTask(), db_engine)
        first_attempt = asyncio.create_task(task._post_single_comment_async(scenario["ai_comment"].id))
        await asyncio.wait_for(platform.post_started.wait(), timeout=1.0)

        second_result = await task._post_single_comment_async(scenario["ai_comment"].id)
        platform.release.set()
        first_result = await first_attempt
    finally:
        use_adapter(None)

    assert len(platform.posted_comments) == 1
    assert first_result["status"] == "posted"
    assert second_result["status"] == "skipped"


async def test_post_single_comment_does_not_revert_after_successful_external_post_if_finalize_fails(
    db_session,
    db_engine,
    fake_platform,
):
    scenario = await _generated_comment_on_platform(db_session, fake_platform)

    task = _bind_task_sessions(CommentPostingTask(), db_engine)

    async def fail_finalize(*args, **kwargs):
        raise RuntimeError("database unavailable")

    task._finalize_posted_comment = fail_finalize
    result = await task._post_single_comment_async(scenario["ai_comment"].id)

    assert result["status"] == "posting"
    assert result["reason"] == "finalization_failed"
    await db_session.refresh(scenario["ai_comment"])
    assert scenario["ai_comment"].status == "posting"
    assert scenario["ai_comment"].mymoment_comment_id is None
    assert scenario["ai_comment"].posted_at is None


async def test_post_single_comment_wrapper_uses_posting_fallback_when_claim_revert_is_stuck(
    db_session,
    db_engine,
):
    scenario = await build_scenario("generated_not_posted", db_session)
    scenario["ai_comment"].status = "posting"
    await db_session.commit()

    task = _bind_task_sessions(CommentPostingTask(), db_engine)
    mark_failed_statuses: list[str] = []
    original_mark_comment_failed = task._mark_comment_failed

    async def probe_mark_comment_failed(ai_comment_id, error_msg, expected_status="posting"):
        mark_failed_statuses.append(expected_status)
        return await original_mark_comment_failed(ai_comment_id, error_msg, expected_status)

    async def fail_post(_ai_comment_id):
        raise PlatformUnavailable("posting failed hard")

    async def fail_revert(_ai_comment_id):
        return False

    task._mark_comment_failed = probe_mark_comment_failed
    task._post_single_comment_async = fail_post
    task._revert_comment_claim = fail_revert

    result = await _run_post_comment_task(
        task,
        scenario["ai_comment"].id,
        retries=0,
        max_retries=3,
    )

    assert result["status"] == "failed"
    assert task.retry_calls == []
    assert mark_failed_statuses == ["generated", "posting"]
    await db_session.refresh(scenario["ai_comment"])
    assert scenario["ai_comment"].status == "failed"
    assert "Retry recovery failed after posting error: posting failed hard" in scenario["ai_comment"].error_message


async def _process_with_two_generated_comments(db_session, fake_platform):
    scenario = await build_scenario("generated_not_posted", db_session)
    second = await create_generated_ai_comment(
        db_session,
        user=scenario["user"],
        monitoring_process=scenario["process"],
        mymoment_login=scenario["login"],
        prompt_template=scenario["prompt"],
        llm_provider=scenario["provider"],
    )
    await db_session.commit()
    first = scenario["ai_comment"]
    fake_platform.add_article(first.mymoment_article_id)
    fake_platform.add_article(second.mymoment_article_id)
    return scenario["process"], first, second


async def test_batch_posting_posts_every_generated_comment_of_the_process(db_session, db_engine, fake_platform):
    process, first, second = await _process_with_two_generated_comments(db_session, fake_platform)

    task = _bind_task_sessions(CommentPostingTask(), db_engine)
    result = await _run_batch_task(task, process.id)

    assert (result["status"], result["posted"]) == ("success", 2)
    assert sorted(c.ref.id for c in fake_platform.posted_comments) == sorted(
        [first.mymoment_article_id, second.mymoment_article_id]
    )


async def test_batch_posting_marks_rejected_comment_failed_and_posts_the_rest(db_session, db_engine, fake_platform):
    process, first, second = await _process_with_two_generated_comments(db_session, fake_platform)
    fake_platform.reject_comments(first.mymoment_article_id)

    task = _bind_task_sessions(CommentPostingTask(), db_engine)
    result = await _run_batch_task(task, process.id)

    await db_session.refresh(first)
    await db_session.refresh(second)
    assert (result["posted"], result["failed"], first.status, second.status) == (1, 1, "failed", "posted")


async def test_batch_posting_keeps_comments_generated_when_platform_is_unavailable(db_session, db_engine, fake_platform):
    process, first, second = await _process_with_two_generated_comments(db_session, fake_platform)
    fake_platform.fail("post_comment", PlatformUnavailable("timeout"))

    task = _bind_task_sessions(CommentPostingTask(), db_engine)
    with pytest.raises(comment_posting.PostingDeferred):
        await _run_batch_task(task, process.id)

    await db_session.refresh(first)
    await db_session.refresh(second)
    assert (first.status, second.status) == ("generated", "generated")


async def test_batch_posting_marks_comments_failed_when_credentials_are_wrong(db_session, db_engine, fake_platform):
    process, first, second = await _process_with_two_generated_comments(db_session, fake_platform)
    fake_platform.fail("connect", PlatformAuthError("wrong password"))

    task = _bind_task_sessions(CommentPostingTask(), db_engine)
    result = await _run_batch_task(task, process.id)

    await db_session.refresh(first)
    await db_session.refresh(second)
    assert (result["failed"], result["deferred"], first.status, second.status) == (2, 0, "failed", "failed")


async def test_batch_posting_marks_comments_failed_when_credentials_cannot_be_decrypted(
    db_session, db_engine, fake_platform
):
    process, first, second = await _process_with_two_generated_comments(db_session, fake_platform)
    login = await db_session.get(MyMomentLogin, first.mymoment_login_id)
    login.username_encrypted = "not-a-fernet-token"
    await db_session.commit()

    task = _bind_task_sessions(CommentPostingTask(), db_engine)
    result = await _run_batch_task(task, process.id)

    await db_session.refresh(first)
    await db_session.refresh(second)
    assert (result["failed"], first.status, second.status) == (2, "failed", "failed")


def _fail_platform_account_reads(task):
    """A database outage that hits only the query for platform accounts."""
    get_session = task.get_async_session

    async def _get_async_session():
        session = await get_session()
        execute = session.execute

        async def _execute(statement, *args, **kwargs):
            if isinstance(statement, Select) and MyMomentLogin.__table__ in statement.get_final_froms():
                raise OperationalError(str(statement), {}, Exception("database is locked"))
            return await execute(statement, *args, **kwargs)

        session.execute = _execute
        return session

    task.get_async_session = _get_async_session
    return task


async def test_batch_posting_keeps_comments_generated_when_accounts_cannot_be_read(
    db_session, db_engine, fake_platform
):
    process, first, second = await _process_with_two_generated_comments(db_session, fake_platform)

    task = _fail_platform_account_reads(_bind_task_sessions(CommentPostingTask(), db_engine))
    result = await _run_batch_task(task, process.id)

    await db_session.refresh(first)
    await db_session.refresh(second)
    assert (result["status"], first.status, second.status) == ("failed", "generated", "generated")


async def test_batch_posting_task_raises_for_celery_retry_when_comments_were_deferred(
    db_session, db_engine, fake_platform
):
    process, _, _ = await _process_with_two_generated_comments(db_session, fake_platform)
    fake_platform.fail("connect", PlatformUnavailable("connection refused"))

    task = _bind_task_sessions(CommentPostingTask(), db_engine)
    with pytest.raises(comment_posting.PostingDeferred):
        await _run_batch_task(task, process.id)
