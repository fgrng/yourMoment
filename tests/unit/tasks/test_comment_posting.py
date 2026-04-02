from __future__ import annotations
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.tasks import comment_posting
from src.tasks.comment_posting import CommentPostingTask
from tests.fixtures.assertions import assert_task_result_shape
from tests.fixtures.builders import build_scenario
from tests.fixtures.stubs import CeleryTaskContextStub


pytestmark = [pytest.mark.unit, pytest.mark.database, pytest.mark.celery, pytest.mark.web_scraping]


def _bind_task_sessions(task, db_engine):
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _get_async_session():
        return session_factory()

    task.get_async_session = _get_async_session
    return task


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


async def test_update_posted_comment_is_a_stale_no_op(db_session, db_engine):
    scenario = await build_scenario("posted_comment_audit_snapshot", db_session)
    original_comment_id = scenario["ai_comment"].mymoment_comment_id
    original_posted_at = scenario["ai_comment"].posted_at
    await db_session.commit()

    task = _bind_task_sessions(CommentPostingTask(), db_engine)
    updated = await task._update_posted_comment(
        scenario["ai_comment"].id,
        comment_id="replacement-comment-id",
        posted_at=datetime.utcnow(),
        expected_status="generated",
    )

    assert updated is True
    await db_session.refresh(scenario["ai_comment"])
    assert scenario["ai_comment"].status == "posted"
    assert scenario["ai_comment"].mymoment_comment_id == original_comment_id
    assert scenario["ai_comment"].posted_at == original_posted_at


async def test_mark_comment_failed_persists_posting_failure_metadata(db_session, db_engine):
    scenario = await build_scenario("generated_not_posted", db_session)
    await db_session.commit()

    task = _bind_task_sessions(CommentPostingTask(), db_engine)
    await task._mark_comment_failed(
        scenario["ai_comment"].id,
        "Max retries exhausted: posting failed hard",
        expected_status="generated",
    )

    await db_session.refresh(scenario["ai_comment"])
    assert scenario["ai_comment"].status == "failed"
    assert scenario["ai_comment"].error_message == "Max retries exhausted: posting failed hard"
    assert scenario["ai_comment"].failed_at is not None
    assert scenario["ai_comment"].retry_count == 1


def test_post_single_comment_wrapper_uses_exponential_backoff(
    monkeypatch,
):
    retry_stub = CeleryTaskContextStub(retries=2)
    marked_failures: list[dict[str, object]] = []

    async def fail_post(_ai_comment_id):
        raise RuntimeError("posting failed hard")

    async def fake_mark_failed(ai_comment_id, error_msg, expected_status="generated"):
        marked_failures.append(
            {
                "ai_comment_id": ai_comment_id,
                "error_message": error_msg,
                "expected_status": expected_status,
            }
        )
        return None

    retry_stub._post_single_comment_async = fail_post
    retry_stub._mark_comment_failed = fake_mark_failed

    ai_comment_id = "6ddbb035-014f-4d95-a9d4-49f3fa0c5d93"
    result = comment_posting.post_comment_for_article.run.__func__(retry_stub, ai_comment_id)

    assert result["status"] == "failed"
    assert retry_stub.retry_calls[0]["countdown"] == 240
    assert marked_failures[0]["expected_status"] == "generated"
    assert "Max retries exhausted: posting failed hard" in marked_failures[0]["error_message"]
