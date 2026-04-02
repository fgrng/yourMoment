from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.models.article_version import ArticleVersion
from src.services.scraper_service import StudentArticleInfo
from src.tasks import student_backup
from src.tasks.student_backup import StudentBackupTask
from tests.fixtures.builders import build_scenario
from tests.support.runtime import reset_all_singletons


pytestmark = [pytest.mark.unit, pytest.mark.database, pytest.mark.celery, pytest.mark.web_scraping]


def _bind_task_sessions(task, db_engine):
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _get_async_session():
        return session_factory()

    task.get_async_session = _get_async_session
    return task


async def test_backup_single_student_skips_unchanged_versions(
    db_session,
    db_engine,
    monkeypatch,
):
    monkeypatch.setenv("STUDENT_BACKUP_ENABLED", "true")
    reset_all_singletons()

    scenario = await build_scenario("student_backup_with_versions", db_session)
    latest_version = scenario["latest_article_version"]
    await db_session.commit()

    class FakeScraperService:
        def __init__(self, session):
            self.session = session

        async def initialize_session_for_login(self, login_id, user_id):
            return SimpleNamespace(login_id=login_id, user_id=user_id, is_authenticated=True)

        async def cleanup_session(self, login_id):
            return None

        async def get_student_articles_from_dashboard(self, context, mymoment_student_id):
            assert mymoment_student_id == scenario["tracked_student"].mymoment_student_id
            return [
                StudentArticleInfo(
                    article_id=latest_version.mymoment_article_id,
                    title=latest_version.article_title,
                    visibility=latest_version.article_visibility,
                    category=latest_version.article_category,
                    status=latest_version.article_status,
                    last_modified=latest_version.article_last_modified,
                    edit_url=f"/article/edit/{latest_version.mymoment_article_id}/",
                    view_url=latest_version.article_url,
                )
            ]

        async def get_article_content(self, context, article_id):
            assert int(article_id) == latest_version.mymoment_article_id
            return {
                "content": latest_version.article_content,
                "full_html": latest_version.article_raw_html,
            }

    monkeypatch.setattr(student_backup, "ScraperService", FakeScraperService)

    task = _bind_task_sessions(StudentBackupTask(), db_engine)
    result = await task._backup_single_student_by_id_async(str(scenario["tracked_student"].id))

    assert result["status"] == "completed"
    assert result["students_processed"] == 1
    assert result["articles_found"] == 1
    assert result["versions_created"] == 0
    assert result["versions_skipped"] == 1
    assert result["errors"] == []

    count_result = await db_session.execute(
        select(func.count(ArticleVersion.id)).where(
            ArticleVersion.tracked_student_id == scenario["tracked_student"].id,
            ArticleVersion.is_active == True,
        )
    )
    assert count_result.scalar_one() == 2


@pytest.mark.parametrize("tracked_student_ids", [["student-a", "student-b"], None])
def test_trigger_backup_dispatches_expected_task_shape(monkeypatch, tracked_student_ids):
    monkeypatch.setenv("STUDENT_BACKUP_ENABLED", "true")
    reset_all_singletons()

    monkeypatch.setattr(
        student_backup.backup_single_student,
        "delay",
        lambda student_id: SimpleNamespace(id=f"single-{student_id}"),
    )
    monkeypatch.setattr(
        student_backup.backup_all_tracked_students,
        "delay",
        lambda: SimpleNamespace(id="full-backup-task"),
    )

    result = student_backup.trigger_backup(tracked_student_ids)

    assert result["status"] == "dispatched"
    if tracked_student_ids:
        assert result["count"] == 2
        assert [row["task_id"] for row in result["tasks"]] == [
            "single-student-a",
            "single-student-b",
        ]
    else:
        assert result["type"] == "full_backup"
        assert result["task_id"] == "full-backup-task"
