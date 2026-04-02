from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.models.ai_comment import AIComment
from src.services.scraper_service import ArticleMetadata
from src.tasks import article_discovery
from src.tasks.article_discovery import ArticleDiscoveryTask
from tests.fixtures.assertions import assert_task_result_shape
from tests.fixtures.builders import build_scenario


pytestmark = [pytest.mark.unit, pytest.mark.database, pytest.mark.celery, pytest.mark.web_scraping]


def _bind_task_sessions(task, db_engine):
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _get_async_session():
        return session_factory()

    task.get_async_session = _get_async_session
    return task


async def test_discovery_creates_rows_and_skips_duplicates(db_session, db_engine, monkeypatch):
    scenario = await build_scenario("minimal_happy_path", db_session)
    await db_session.commit()

    task = _bind_task_sessions(ArticleDiscoveryTask(), db_engine)
    article = ArticleMetadata(
        id="article-1234",
        title="Discovery Fixture",
        author="Fixture Teacher",
        date="2026-04-02",
        status="published",
        category_id=7,
        task_id=4,
        visibility="Class 5A",
        url="https://www.mymoment.ch/article/1234/",
    )

    async def fake_scrape_articles_for_login(login_id, user_id, config_snapshot):
        assert login_id == scenario["login"].id
        assert user_id == scenario["user"].id
        assert config_snapshot.process_id == scenario["process"].id
        return [article]

    monkeypatch.setattr(task, "_scrape_articles_for_login", fake_scrape_articles_for_login)

    first_result = await task._discover_articles_async(scenario["process"].id)
    second_result = await task._discover_articles_async(scenario["process"].id)

    assert_task_result_shape(
        first_result,
        required_keys=("status", "discovered", "created_ai_comment_ids", "errors"),
        expected_status="success",
    )
    assert first_result["discovered"] == 1
    assert second_result["status"] == "success"
    assert second_result["discovered"] == 0
    assert second_result["created_ai_comment_ids"] == []

    result = await db_session.execute(
        select(AIComment).where(AIComment.monitoring_process_id == scenario["process"].id)
    )
    comments = result.scalars().all()
    assert len(comments) == 1

    comment = comments[0]
    assert comment.status == "discovered"
    assert comment.mymoment_article_id == article.id
    assert comment.prompt_template_id == scenario["prompt"].id
    assert comment.llm_provider_id == scenario["provider"].id
    assert comment.mymoment_login_id == scenario["login"].id
    assert comment.is_hidden is scenario["process"].hide_comments


@pytest.mark.parametrize("generate_only", [False, True])
def test_discovery_wrapper_dispatches_processing_chains(generate_only, monkeypatch):
    process_id = uuid.uuid4()
    created_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    task = ArticleDiscoveryTask()
    captured: dict[str, object] = {}

    async def fake_discover(process_uuid):
        assert process_uuid == process_id
        return {
            "status": "success",
            "discovered": len(created_ids),
            "generate_only": generate_only,
            "created_ai_comment_ids": created_ids,
            "errors": [],
            "execution_time_seconds": 0.01,
        }

    def fake_dispatch(ai_comment_ids, *, generate_only):
        captured["ai_comment_ids"] = ai_comment_ids
        captured["generate_only"] = generate_only
        return [
            {"ai_comment_id": ai_comment_id, "root_task_id": f"root-{index}"}
            for index, ai_comment_id in enumerate(ai_comment_ids, start=1)
        ]

    monkeypatch.setattr(task, "_discover_articles_async", fake_discover)
    monkeypatch.setattr(article_discovery, "_dispatch_processing_chains", fake_dispatch)

    result = article_discovery.discover_articles.run.__func__(task, str(process_id))

    assert_task_result_shape(result, required_keys=("status", "spawned_chains"), expected_status="success")
    assert captured == {"ai_comment_ids": created_ids, "generate_only": generate_only}
    assert [row["ai_comment_id"] for row in result["spawned_chains"]] == created_ids
