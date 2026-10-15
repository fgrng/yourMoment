from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.platforms import PlatformAuthError, PlatformRejected, PlatformUnavailable
from src.services.student_backup_service import StudentBackupService
from src.tasks import student_backup
from src.tasks.student_backup import StudentBackupTask
from tests.fixtures.builders import build_scenario
from tests.support.runtime import reset_all_singletons


pytestmark = [pytest.mark.unit, pytest.mark.database, pytest.mark.celery, pytest.mark.web_scraping]


class _CountingSession(AsyncSession):
    """Counts the sessions the task holds open."""

    open_sessions = 0

    async def __aenter__(self):
        type(self).open_sessions += 1
        return await super().__aenter__()

    async def __aexit__(self, *exc_info):
        type(self).open_sessions -= 1
        return await super().__aexit__(*exc_info)


def _bind_task_sessions(task, db_engine):
    _CountingSession.open_sessions = 0
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=_CountingSession)

    async def _get_async_session():
        return session_factory()

    task.get_async_session = _get_async_session
    return task


@pytest.fixture
def backup_enabled(monkeypatch):
    monkeypatch.setenv("STUDENT_BACKUP_ENABLED", "true")
    reset_all_singletons()
    yield
    reset_all_singletons()


@pytest.fixture
async def scenario(db_session, backup_enabled):
    scenario = await build_scenario("student_backup_with_versions", db_session)
    await db_session.commit()
    return scenario


def _add_student_article(fake_platform, student, article_id="4711", **overrides):
    defaults = dict(
        title="Mein Ausflug in den Zoo",
        body_text="Wir waren im Zoo.",
        body_html="<p>Wir waren im Zoo.</p>",
        edited_at=datetime(2026, 1, 28, 9, 24, tzinfo=UTC),
        extra={"status": "Publiziert", "visibility": "Beispielklasse A", "categories": "Unterhalten"},
        student=str(student.mymoment_student_id),
    )
    return fake_platform.add_article(article_id, **{**defaults, **overrides})


async def _versions(db_session, scenario, article_id):
    service = StudentBackupService(db_session)
    return await service.get_article_versions(
        scenario["tracked_student"].id, scenario["user"].id, mymoment_article_id=article_id
    )


async def test_backup_single_student_skips_unchanged_versions(db_session, db_engine, fake_platform, scenario):
    latest = scenario["latest_article_version"]
    _add_student_article(
        fake_platform,
        scenario["tracked_student"],
        article_id=str(latest.mymoment_article_id),
        title=latest.article_title,
        body_text=latest.article_content,
        body_html=latest.article_raw_html,
        extra={
            "status": latest.article_status,
            "visibility": latest.article_visibility,
            "categories": latest.article_category,
        },
    )

    task = _bind_task_sessions(StudentBackupTask(), db_engine)
    result = await task._backup_single_student_by_id_async(str(scenario["tracked_student"].id))

    assert (result["status"], result["articles_found"], result["versions_created"], result["versions_skipped"],
            result["errors"]) == ("completed", 1, 0, 1, [])


async def test_backup_single_student_stores_a_new_article_with_its_absolute_url(
    db_session, db_engine, fake_platform, scenario
):
    _add_student_article(fake_platform, scenario["tracked_student"], article_id="4711")

    task = _bind_task_sessions(StudentBackupTask(), db_engine)
    await task._backup_single_student_by_id_async(str(scenario["tracked_student"].id))

    [version] = await _versions(db_session, scenario, 4711)
    assert (
        version.article_url,
        version.article_title,
        version.article_content,
        version.article_raw_html,
        version.article_status,
        version.article_visibility,
        version.article_category,
        version.article_last_modified,
    ) == (
        "https://fake.example/articles/4711",
        "Mein Ausflug in den Zoo",
        "Wir waren im Zoo.",
        "<p>Wir waren im Zoo.</p>",
        "Publiziert",
        "Beispielklasse A",
        "Unterhalten",
        datetime(2026, 1, 28, 9, 24, tzinfo=UTC),
    )


async def test_backup_single_student_adds_a_version_when_the_content_changed(
    db_session, db_engine, fake_platform, scenario
):
    latest = scenario["latest_article_version"]
    _add_student_article(
        fake_platform,
        scenario["tracked_student"],
        article_id=str(latest.mymoment_article_id),
        body_text="Ganz neuer Inhalt.",
    )

    task = _bind_task_sessions(StudentBackupTask(), db_engine)
    await task._backup_single_student_by_id_async(str(scenario["tracked_student"].id))

    versions = await _versions(db_session, scenario, latest.mymoment_article_id)
    assert [(v.version_number, v.article_content) for v in versions][0] == (3, "Ganz neuer Inhalt.")


async def test_backup_holds_no_database_session_during_platform_calls(db_engine, fake_platform, scenario):
    _add_student_article(fake_platform, scenario["tracked_student"], article_id="4711")
    _add_student_article(fake_platform, scenario["tracked_student"], article_id="4712")
    sessions_during_calls = []
    fake_platform.on_call = lambda operation: sessions_during_calls.append(_CountingSession.open_sessions)

    task = _bind_task_sessions(StudentBackupTask(), db_engine)
    result = await task._backup_all_students_async()

    assert (result["versions_created"], set(sessions_during_calls)) == (2, {0})


async def test_backup_connects_with_the_students_admin_account(db_engine, fake_platform, scenario):
    task = _bind_task_sessions(StudentBackupTask(), db_engine)
    await task._backup_all_students_async()

    assert [(a.id, a.role) for a in fake_platform.connected_accounts] == [(scenario["admin_login"].id, "admin")]


async def test_backup_skips_students_whose_account_is_no_longer_an_admin_account(
    db_session, db_engine, fake_platform, scenario
):
    scenario["admin_login"].is_admin = False
    await db_session.commit()
    _add_student_article(fake_platform, scenario["tracked_student"], article_id="4711")

    task = _bind_task_sessions(StudentBackupTask(), db_engine)
    result = await task._backup_all_students_async()

    assert (fake_platform.connected_accounts, result["versions_created"], len(result["errors"])) == ([], 0, 1)


@pytest.mark.parametrize(
    "operation,error",
    [
        ("connect", PlatformAuthError("wrong password")),
        ("list_student_articles", PlatformUnavailable("timeout")),
    ],
)
async def test_backup_reports_platform_errors(db_engine, fake_platform, scenario, operation, error):
    fake_platform.fail(operation, error)

    task = _bind_task_sessions(StudentBackupTask(), db_engine)
    result = await task._backup_all_students_async()

    assert (result["status"], result["students_processed"], len(result["errors"])) == ("completed", 0, 1)


async def test_backup_reports_an_article_the_platform_refuses_to_deliver(db_engine, fake_platform, scenario):
    _add_student_article(fake_platform, scenario["tracked_student"], article_id="4711")
    fake_platform.fail("fetch_article", PlatformRejected("article deleted"))

    task = _bind_task_sessions(StudentBackupTask(), db_engine)
    result = await task._backup_single_student_by_id_async(str(scenario["tracked_student"].id))

    assert (result["status"], result["versions_created"], len(result["errors"])) == ("completed", 0, 1)


async def test_backup_keeps_other_articles_when_one_cannot_be_read(db_session, db_engine, fake_platform, scenario):
    _add_student_article(fake_platform, scenario["tracked_student"], article_id="4711")
    _add_student_article(fake_platform, scenario["tracked_student"], article_id="draft-1")

    task = _bind_task_sessions(StudentBackupTask(), db_engine)
    result = await task._backup_single_student_by_id_async(str(scenario["tracked_student"].id))

    assert (result["versions_created"], len(result["errors"]), len(await _versions(db_session, scenario, 4711))) == (
        1,
        1,
        1,
    )


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
