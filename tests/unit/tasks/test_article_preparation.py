from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.tasks import article_preparation
from src.tasks.article_preparation import ArticlePreparationTask
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


async def test_prepare_single_article_transitions_discovered_to_prepared(
    db_session,
    db_engine,
    monkeypatch,
):
    scenario = await build_scenario("article_discovered_not_prepared", db_session)
    await db_session.commit()

    cleanup_calls: list[object] = []

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

        async def get_article_content(self, context, article_id):
            assert article_id == scenario["ai_comment"].mymoment_article_id
            return {
                "content": "Prepared article body captured from the scraper fixture.",
                "full_html": "<article><p>Prepared article body captured from the scraper fixture.</p></article>",
                "title": "Prepared Title",
                "category_id": 14,
                "task_id": 10,
            }

        async def cleanup_session(self, login_id):
            cleanup_calls.append(login_id)

    monkeypatch.setattr(article_preparation, "ScraperService", FakeScraperService)

    task = _bind_task_sessions(ArticlePreparationTask(), db_engine)
    result = await task._prepare_single_article_async(scenario["ai_comment"].id)

    assert_task_result_shape(result, required_keys=("status", "ai_comment_id"), expected_status="prepared")
    assert cleanup_calls == [scenario["login"].id]

    await db_session.refresh(scenario["ai_comment"])
    assert scenario["ai_comment"].status == "prepared"
    assert scenario["ai_comment"].article_content == "Prepared article body captured from the scraper fixture."
    assert scenario["ai_comment"].article_title == "Prepared Title"
    assert scenario["ai_comment"].article_category == 14
    assert scenario["ai_comment"].article_task_id == 10
    assert scenario["ai_comment"].failed_at is None
    assert scenario["ai_comment"].error_message is None


async def test_prepare_single_article_skips_rows_that_already_advanced(db_session, db_engine):
    scenario = await build_scenario("prepared_not_generated", db_session)
    await db_session.commit()

    task = _bind_task_sessions(ArticlePreparationTask(), db_engine)
    result = await task._prepare_single_article_async(scenario["ai_comment"].id)

    assert result["status"] == "skipped"
    assert result["reason"] == "already_prepared"


async def test_update_article_content_is_idempotent_for_stale_rows(db_session, db_engine):
    scenario = await build_scenario("prepared_not_generated", db_session)
    original_content = scenario["ai_comment"].article_content
    await db_session.commit()

    task = _bind_task_sessions(ArticlePreparationTask(), db_engine)
    updated = await task._update_article_content(
        scenario["ai_comment"].id,
        {"content": "race-lost overwrite", "full_html": "<p>race-lost overwrite</p>"},
        expected_status="discovered",
    )

    assert updated is True
    await db_session.refresh(scenario["ai_comment"])
    assert scenario["ai_comment"].status == "prepared"
    assert scenario["ai_comment"].article_content == original_content


async def test_mark_article_failed_persists_failure_metadata(db_session, db_engine):
    scenario = await build_scenario("article_discovered_not_prepared", db_session)
    await db_session.commit()

    task = _bind_task_sessions(ArticlePreparationTask(), db_engine)
    marked = await task._mark_article_failed(
        scenario["ai_comment"].id,
        "Max retries exhausted: scraper blew up",
        expected_status="discovered",
    )

    assert marked is True
    await db_session.refresh(scenario["ai_comment"])
    assert scenario["ai_comment"].status == "failed"
    assert scenario["ai_comment"].error_message == "Max retries exhausted: scraper blew up"
    assert scenario["ai_comment"].failed_at is not None


def test_prepare_single_article_wrapper_uses_exponential_backoff(
    monkeypatch,
):
    retry_stub = CeleryTaskContextStub(retries=2)
    marked_failures: list[dict[str, object]] = []

    async def fail_prepare(_ai_comment_id):
        raise RuntimeError("scraper blew up")

    async def fake_mark_failed(ai_comment_id, error_message, expected_status="discovered"):
        marked_failures.append(
            {
                "ai_comment_id": ai_comment_id,
                "error_message": error_message,
                "expected_status": expected_status,
            }
        )
        return True

    retry_stub._prepare_single_article_async = fail_prepare
    retry_stub._mark_article_failed = fake_mark_failed

    ai_comment_id = "4b4fce69-df53-41e1-a3d9-46f0afdbf8a9"
    result = article_preparation.prepare_article_content.run.__func__(retry_stub, ai_comment_id)

    assert result["status"] == "failed"
    assert retry_stub.retry_calls[0]["countdown"] == 240
    assert marked_failures[0]["expected_status"] == "discovered"
    assert "Max retries exhausted: scraper blew up" in marked_failures[0]["error_message"]
