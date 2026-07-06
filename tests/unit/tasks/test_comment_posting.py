from __future__ import annotations
import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest
from celery.utils.threads import LocalStack
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.tasks import comment_posting
from src.tasks.comment_posting import CommentPostingTask
from src.services.scraper_service import ScrapingError
from tests.fixtures.assertions import assert_task_result_shape
from tests.fixtures.builders import build_scenario


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


async def test_post_single_comment_transitions_generated_to_posted(
    db_session,
    db_engine,
    monkeypatch,
):
    scenario = await build_scenario(
        "generated_not_posted",
        db_session,
        overrides={"ai_comment": {"is_hidden": True}},
    )
    await db_session.commit()

    post_calls: list[dict[str, object]] = []

    class FakeScraperService:
        def __init__(self, session, config):
            self.session = session
            self.config = config

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def initialize_session_for_login(self, login_id, user_id):
            return SimpleNamespace(login_id=login_id, user_id=user_id, is_authenticated=True)

        async def post_comment(self, *, context, article_id, comment_content, hide_comment):
            post_calls.append(
                {
                    "article_id": article_id,
                    "comment_content": comment_content,
                    "hide_comment": hide_comment,
                }
            )
            return True

        async def cleanup_session(self, login_id):
            return None

    monkeypatch.setattr(comment_posting, "ScraperService", FakeScraperService)

    task = _bind_task_sessions(CommentPostingTask(), db_engine)
    result = await task._post_single_comment_async(scenario["ai_comment"].id)

    assert_task_result_shape(result, required_keys=("status", "ai_comment_id"), expected_status="posted")
    assert post_calls[0]["article_id"] == scenario["ai_comment"].mymoment_article_id
    assert post_calls[0]["hide_comment"] is True

    await db_session.refresh(scenario["ai_comment"])
    assert scenario["ai_comment"].status == "posted"
    assert scenario["ai_comment"].posted_at is not None
    assert scenario["ai_comment"].mymoment_comment_id.startswith(
        f"{scenario['ai_comment'].mymoment_article_id}-"
    )


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


async def test_post_single_comment_wrapper_reverts_claim_before_retry(
    db_session,
    db_engine,
    monkeypatch,
):
    scenario = await build_scenario("generated_not_posted", db_session)
    await db_session.commit()

    class RetryScheduled(Exception):
        pass

    class FailingScraperService:
        def __init__(self, session, config):
            self.session = session
            self.config = config

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def initialize_session_for_login(self, login_id, user_id):
            raise RuntimeError("transient init failure")

        async def cleanup_session(self, login_id):
            return None

    def _raise_retry(*, exc, countdown):
        raise RetryScheduled()

    monkeypatch.setattr(comment_posting, "ScraperService", FailingScraperService)

    task = _bind_task_sessions(CommentPostingTask(), db_engine)
    with pytest.raises(RetryScheduled):
        await _run_post_comment_task(
            task,
            scenario["ai_comment"].id,
            retries=0,
            max_retries=3,
            retry_callback=_raise_retry,
        )

    assert task.retry_calls[0]["countdown"] == 60
    await db_session.refresh(scenario["ai_comment"])
    assert scenario["ai_comment"].status == "generated"
    assert scenario["ai_comment"].mymoment_comment_id is None
    assert scenario["ai_comment"].posted_at is None
    assert scenario["ai_comment"].failed_at is None


async def test_post_single_comment_wrapper_marks_failed_after_retry_budget_is_exhausted(
    db_session,
    db_engine,
    monkeypatch,
):
    scenario = await build_scenario("generated_not_posted", db_session)
    await db_session.commit()

    class FailingScraperService:
        def __init__(self, session, config):
            self.session = session
            self.config = config

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def initialize_session_for_login(self, login_id, user_id):
            raise RuntimeError("transient init failure")

        async def cleanup_session(self, login_id):
            return None

    monkeypatch.setattr(comment_posting, "ScraperService", FailingScraperService)

    task = _bind_task_sessions(CommentPostingTask(), db_engine)
    mark_failed_statuses: list[str] = []
    original_mark_comment_failed = task._mark_comment_failed

    async def probe_mark_comment_failed(ai_comment_id, error_msg, expected_status="posting"):
        mark_failed_statuses.append(expected_status)
        return await original_mark_comment_failed(ai_comment_id, error_msg, expected_status)

    task._mark_comment_failed = probe_mark_comment_failed
    result = await _run_post_comment_task(
        task,
        scenario["ai_comment"].id,
        retries=3,
        max_retries=3,
    )

    assert result["status"] == "failed"
    assert task.retry_calls == []
    assert mark_failed_statuses == ["generated"]
    await db_session.refresh(scenario["ai_comment"])
    assert scenario["ai_comment"].status == "failed"
    assert scenario["ai_comment"].error_message == "Max retries exhausted: transient init failure"
    assert scenario["ai_comment"].mymoment_comment_id is None
    assert scenario["ai_comment"].posted_at is None
    assert scenario["ai_comment"].retry_count == 1


async def test_post_single_comment_wrapper_marks_auth_failures_failed_without_retry(
    db_session,
    db_engine,
    monkeypatch,
):
    scenario = await build_scenario("generated_not_posted", db_session)
    await db_session.commit()

    class AuthFailingScraperService:
        def __init__(self, session, config):
            self.session = session
            self.config = config

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def initialize_session_for_login(self, login_id, user_id):
            raise ScrapingError("Failed to authenticate with myMoment: invalid credentials")

        async def cleanup_session(self, login_id):
            return None

    monkeypatch.setattr(comment_posting, "ScraperService", AuthFailingScraperService)

    task = _bind_task_sessions(CommentPostingTask(), db_engine)
    result = await _run_post_comment_task(
        task,
        scenario["ai_comment"].id,
        retries=0,
        max_retries=3,
    )

    assert result["status"] == "failed"
    assert task.retry_calls == []
    await db_session.refresh(scenario["ai_comment"])
    assert scenario["ai_comment"].status == "failed"
    assert scenario["ai_comment"].error_message == "Failed to authenticate with myMoment: invalid credentials"
    assert scenario["ai_comment"].mymoment_comment_id is None
    assert scenario["ai_comment"].posted_at is None


async def test_post_single_comment_concurrent_claim_allows_only_one_http_post(
    db_session,
    db_engine,
    monkeypatch,
):
    scenario = await build_scenario("generated_not_posted", db_session)
    await db_session.commit()

    post_calls: list[dict[str, object]] = []
    first_post_started = asyncio.Event()
    release_first_post = asyncio.Event()

    class SlowScraperService:
        def __init__(self, session, config):
            self.session = session
            self.config = config

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def initialize_session_for_login(self, login_id, user_id):
            return SimpleNamespace(login_id=login_id, user_id=user_id, is_authenticated=True)

        async def post_comment(self, *, context, article_id, comment_content, hide_comment):
            post_calls.append({"article_id": article_id, "hide_comment": hide_comment})
            first_post_started.set()
            await release_first_post.wait()
            return True

        async def cleanup_session(self, login_id):
            return None

    monkeypatch.setattr(comment_posting, "ScraperService", SlowScraperService)

    task = _bind_task_sessions(CommentPostingTask(), db_engine)
    first_attempt = asyncio.create_task(task._post_single_comment_async(scenario["ai_comment"].id))
    await asyncio.wait_for(first_post_started.wait(), timeout=1.0)

    second_result = await task._post_single_comment_async(scenario["ai_comment"].id)
    release_first_post.set()
    first_result = await first_attempt

    assert len(post_calls) == 1
    assert first_result["status"] == "posted"
    assert second_result["status"] == "skipped"
    assert second_result["reason"] in {"already_claimed", "already_posting", "already_posted"}


async def test_post_single_comment_reverts_claim_when_posting_returns_false(
    db_session,
    db_engine,
    monkeypatch,
):
    scenario = await build_scenario("generated_not_posted", db_session)
    await db_session.commit()

    class FalsePostingScraperService:
        def __init__(self, session, config):
            self.session = session
            self.config = config

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def initialize_session_for_login(self, login_id, user_id):
            return SimpleNamespace(login_id=login_id, user_id=user_id, is_authenticated=True)

        async def post_comment(self, *, context, article_id, comment_content, hide_comment):
            return False

        async def cleanup_session(self, login_id):
            return None

    monkeypatch.setattr(comment_posting, "ScraperService", FalsePostingScraperService)

    task = _bind_task_sessions(CommentPostingTask(), db_engine)
    with pytest.raises(RuntimeError, match="Comment posting returned False"):
        await task._post_single_comment_async(scenario["ai_comment"].id)

    await db_session.refresh(scenario["ai_comment"])
    assert scenario["ai_comment"].status == "generated"
    assert scenario["ai_comment"].mymoment_comment_id is None
    assert scenario["ai_comment"].posted_at is None


async def test_post_single_comment_does_not_revert_after_successful_external_post_if_finalize_fails(
    db_session,
    db_engine,
    monkeypatch,
):
    scenario = await build_scenario("generated_not_posted", db_session)
    await db_session.commit()

    class SuccessfulScraperService:
        def __init__(self, session, config):
            self.session = session
            self.config = config

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def initialize_session_for_login(self, login_id, user_id):
            return SimpleNamespace(login_id=login_id, user_id=user_id, is_authenticated=True)

        async def post_comment(self, *, context, article_id, comment_content, hide_comment):
            return True

        async def cleanup_session(self, login_id):
            return None

    monkeypatch.setattr(comment_posting, "ScraperService", SuccessfulScraperService)

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
        raise RuntimeError("posting failed hard")

    async def fail_revert(_ai_comment_id):
        return False

    task._mark_comment_failed = probe_mark_comment_failed
    task._post_single_comment_async = fail_post
    task._revert_comment_claim = fail_revert
    task._is_retryable_posting_error = lambda exc: True

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
