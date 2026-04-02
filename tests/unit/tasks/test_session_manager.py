from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.models.mymoment_session import MyMomentSession
from src.tasks import session_manager
from src.tasks.session_manager import SessionManagementTask
from tests.fixtures.builders import build_scenario
from tests.fixtures.factories import create_mymoment_session


pytestmark = [pytest.mark.unit, pytest.mark.database, pytest.mark.celery]


def _bind_task_sessions(task, db_engine):
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _get_async_session():
        return session_factory()

    task.get_async_session = _get_async_session
    return task


async def test_cleanup_expired_sessions_marks_only_expired_rows_inactive(
    db_session,
    db_engine,
):
    scenario = await build_scenario("expired_mymoment_session", db_session)
    active_session = await create_mymoment_session(
        db_session,
        mymoment_login=scenario["login"],
        expires_at=datetime.utcnow() + timedelta(hours=2),
    )
    await db_session.commit()

    task = _bind_task_sessions(SessionManagementTask(), db_engine)
    result = await task._cleanup_expired_sessions_async()

    assert result["cleaned_up_sessions"] == 1
    assert result["errors"] == []

    await db_session.refresh(scenario["expired_mymoment_session"])
    await db_session.refresh(active_session)
    assert scenario["expired_mymoment_session"].is_active is False
    assert active_session.is_active is True


async def test_cleanup_old_session_records_deletes_only_inactive_records_older_than_retention(
    db_session,
    db_engine,
    monkeypatch,
):
    scenario = await build_scenario("minimal_happy_path", db_session)
    old_inactive = await create_mymoment_session(
        db_session,
        mymoment_login=scenario["login"],
        is_active=False,
        created_at=datetime.utcnow() - timedelta(days=45),
    )
    new_inactive = await create_mymoment_session(
        db_session,
        mymoment_login=scenario["login"],
        is_active=False,
        created_at=datetime.utcnow() - timedelta(days=5),
    )
    old_active = await create_mymoment_session(
        db_session,
        mymoment_login=scenario["login"],
        is_active=True,
        created_at=datetime.utcnow() - timedelta(days=45),
    )
    await db_session.commit()

    class FakeDatabaseManager:
        def get_async_sessionmaker(self):
            return async_sessionmaker(db_engine, expire_on_commit=False)

    monkeypatch.setattr(session_manager, "get_database_manager", lambda: FakeDatabaseManager())

    result = await session_manager._cleanup_old_session_records_async()

    assert result["deleted_records"] == 1

    rows = await db_session.execute(select(MyMomentSession).order_by(MyMomentSession.created_at))
    remaining_ids = {row.id for row in rows.scalars().all()}
    assert old_inactive.id not in remaining_ids
    assert new_inactive.id in remaining_ids
    assert old_active.id in remaining_ids
