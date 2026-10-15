from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.models.ai_comment import AIComment
from src.platforms import PlatformUnavailable
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


def _add_target_article(fake_platform, article_id, **kwargs):
    """An article matching the default process target: classroom home, category 7, title with "sample"."""
    kwargs.setdefault("title", f"Sample Story {article_id}")
    kwargs.setdefault("category", "7")
    return fake_platform.add_article(article_id, extra={"classroom": "home"}, **kwargs)


async def _comments_of(db_session, process_id):
    result = await db_session.execute(select(AIComment).where(AIComment.monitoring_process_id == process_id))
    return result.scalars().all()


async def test_discovery_creates_rows_and_skips_duplicates(db_session, db_engine, fake_platform):
    scenario = await build_scenario("minimal_happy_path", db_session)
    await db_session.commit()
    ref = _add_target_article(fake_platform, "1234", title="Sample Discovery", author="Fixture Student")

    task = _bind_task_sessions(ArticleDiscoveryTask(), db_engine)
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

    [comment] = await _comments_of(db_session, scenario["process"].id)
    assert comment.status == "discovered"
    assert comment.mymoment_article_id == "1234"
    assert (comment.article_title, comment.article_author, comment.article_url) == (
        "Sample Discovery",
        "Fixture Student",
        ref.url,
    )
    assert (comment.article_category, comment.article_task_id) == (7, None)
    assert comment.prompt_template_id == scenario["prompt"].id
    assert comment.llm_provider_id == scenario["provider"].id
    assert comment.mymoment_login_id == scenario["login"].id
    assert comment.is_hidden is scenario["process"].hide_comments


async def test_discovery_creates_rows_only_for_the_process_target(db_session, db_engine, fake_platform):
    # Process target: classroom "home", category 7, arrangement 10
    target = {"classroom": "home", "category": "7", "arrangement": "10"}
    scenario = await build_scenario("minimal_happy_path", db_session, {"process": {"target": target}})
    await db_session.commit()
    fake_platform.add_article("1", title="Sample", category="7", extra={"classroom": "home", "arrangement": "10"})
    fake_platform.add_article("2", title="Sample", category="9", extra={"classroom": "home", "arrangement": "10"})
    fake_platform.add_article("3", title="Sample", category="7", extra={"classroom": "82", "arrangement": "10"})
    fake_platform.add_article("4", title="Sample", category="7", extra={"classroom": "home", "arrangement": "4"})

    task = _bind_task_sessions(ArticleDiscoveryTask(), db_engine)
    await task._discover_articles_async(scenario["process"].id)

    assert [c.mymoment_article_id for c in await _comments_of(db_session, scenario["process"].id)] == ["1"]


async def test_discovery_stores_no_category_when_the_platform_reports_a_non_numeric_one(
    db_session, db_engine, fake_platform
):
    scenario = await build_scenario("minimal_happy_path", db_session, {"process": {"target": {"classroom": "home"}}})
    await db_session.commit()
    _add_target_article(fake_platform, "1", category="²")

    task = _bind_task_sessions(ArticleDiscoveryTask(), db_engine)
    await task._discover_articles_async(scenario["process"].id)

    [comment] = await _comments_of(db_session, scenario["process"].id)
    assert comment.article_category is None


async def test_discovery_keeps_only_titles_with_the_search_term(db_session, db_engine, fake_platform):
    scenario = await build_scenario("minimal_happy_path", db_session, {"process": {"search_filter": "rotpanda"}})
    await db_session.commit()
    _add_target_article(fake_platform, "1", title="Der Rotpanda")
    _add_target_article(fake_platform, "2", title="Der Eisbär")

    task = _bind_task_sessions(ArticleDiscoveryTask(), db_engine)
    await task._discover_articles_async(scenario["process"].id)

    assert [c.mymoment_article_id for c in await _comments_of(db_session, scenario["process"].id)] == ["1"]
    assert fake_platform.listed_targets == [scenario["process"].target]


async def test_discovery_keeps_all_titles_without_a_search_term(db_session, db_engine, fake_platform):
    scenario = await build_scenario("minimal_happy_path", db_session, {"process": {"search_filter": None}})
    await db_session.commit()
    _add_target_article(fake_platform, "1", title="Der Rotpanda")
    _add_target_article(fake_platform, "2", title="Der Eisbär")

    task = _bind_task_sessions(ArticleDiscoveryTask(), db_engine)
    await task._discover_articles_async(scenario["process"].id)

    assert sorted(c.mymoment_article_id for c in await _comments_of(db_session, scenario["process"].id)) == ["1", "2"]


async def test_discovery_creates_at_most_20_rows_per_login(db_session, db_engine, fake_platform):
    scenario = await build_scenario("minimal_happy_path", db_session)
    await db_session.commit()
    for article_id in range(25):
        _add_target_article(fake_platform, str(article_id))

    task = _bind_task_sessions(ArticleDiscoveryTask(), db_engine)
    result = await task._discover_articles_async(scenario["process"].id)

    assert result["discovered"] == 20


async def test_discovery_passes_the_stored_target_unchanged_to_the_platform(db_session, db_engine, fake_platform):
    target = {"classroom": "4711", "category": "7", "arrangement": "10"}
    scenario = await build_scenario("minimal_happy_path", db_session, {"process": {"target": target}})
    await db_session.commit()

    task = _bind_task_sessions(ArticleDiscoveryTask(), db_engine)
    await task._discover_articles_async(scenario["process"].id)

    assert fake_platform.listed_targets == [target]


async def test_discovery_without_classroom_does_not_contact_the_platform(db_session, db_engine, fake_platform):
    # A process migrated from an empty tab_filter column has no classroom in its target
    scenario = await build_scenario("minimal_happy_path", db_session, {"process": {"target": {"category": "7"}}})
    await db_session.commit()
    _add_target_article(fake_platform, "1")

    task = _bind_task_sessions(ArticleDiscoveryTask(), db_engine)
    result = await task._discover_articles_async(scenario["process"].id)

    assert (result["discovered"], fake_platform.connected_accounts) == (0, [])


async def test_discovery_connects_with_the_decrypted_platform_account(db_session, db_engine, fake_platform):
    scenario = await build_scenario(
        "minimal_happy_path", db_session, {"login": {"username": "teacher", "password": "Secret-1!"}}
    )
    await db_session.commit()

    task = _bind_task_sessions(ArticleDiscoveryTask(), db_engine)
    await task._discover_articles_async(scenario["process"].id)

    [account] = fake_platform.connected_accounts
    assert (account.id, account.username, account.password) == (scenario["login"].id, "teacher", "Secret-1!")


async def test_discovery_reports_unavailable_platform_as_error(db_session, db_engine, fake_platform):
    scenario = await build_scenario("minimal_happy_path", db_session)
    await db_session.commit()
    fake_platform.fail("list_articles", PlatformUnavailable("myMoment down"))

    task = _bind_task_sessions(ArticleDiscoveryTask(), db_engine)
    result = await task._discover_articles_async(scenario["process"].id)

    assert (result["discovered"], len(result["errors"])) == (0, 1)


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
