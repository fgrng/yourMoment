from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.platforms import ArticleContent, ArticleRef, PlatformUnavailable
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
    fake_platform,
):
    scenario = await build_scenario("article_discovered_not_prepared", db_session)
    await db_session.commit()
    fake_platform.add_article(
        scenario["ai_comment"].mymoment_article_id,
        title="Prepared Title",
        body_text="Prepared article body captured from the platform.",
        body_html="<article><p>Prepared article body captured from the platform.</p></article>",
        category="14",
        extra={"arrangement": "10"},
    )

    task = _bind_task_sessions(ArticlePreparationTask(), db_engine)
    result = await task._prepare_single_article_async(scenario["ai_comment"].id)

    assert_task_result_shape(result, required_keys=("status", "ai_comment_id"), expected_status="prepared")

    await db_session.refresh(scenario["ai_comment"])
    assert scenario["ai_comment"].status == "prepared"
    assert scenario["ai_comment"].article_content == "Prepared article body captured from the platform."
    assert scenario["ai_comment"].article_raw_html == (
        "<article><p>Prepared article body captured from the platform.</p></article>"
    )
    assert scenario["ai_comment"].article_title == "Prepared Title"
    assert scenario["ai_comment"].article_category == 14
    assert scenario["ai_comment"].article_task_id == 10
    assert scenario["ai_comment"].failed_at is None
    assert scenario["ai_comment"].error_message is None


async def test_prepare_single_article_connects_with_the_comments_platform_account(
    db_session,
    db_engine,
    fake_platform,
):
    scenario = await build_scenario("article_discovered_not_prepared", db_session)
    await db_session.commit()
    fake_platform.add_article(scenario["ai_comment"].mymoment_article_id)

    task = _bind_task_sessions(ArticlePreparationTask(), db_engine)
    await task._prepare_single_article_async(scenario["ai_comment"].id)

    assert [a.id for a in fake_platform.connected_accounts] == [scenario["login"].id]


async def test_prepare_single_article_propagates_platform_errors_for_retry(
    db_session,
    db_engine,
    fake_platform,
):
    scenario = await build_scenario("article_discovered_not_prepared", db_session)
    await db_session.commit()
    fake_platform.fail("fetch_article", PlatformUnavailable("timeout"))

    task = _bind_task_sessions(ArticlePreparationTask(), db_engine)
    with pytest.raises(PlatformUnavailable):
        await task._prepare_single_article_async(scenario["ai_comment"].id)

    await db_session.refresh(scenario["ai_comment"])
    assert scenario["ai_comment"].status == "discovered"


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
        ArticleContent(
            ref=ArticleRef(id="1", url="https://www.mymoment.ch/article/1/"),
            title="race-lost title",
            author="Author",
            body_html="<p>race-lost overwrite</p>",
            body_text="race-lost overwrite",
        ),
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
