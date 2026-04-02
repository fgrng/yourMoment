from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.services.monitoring_service import MonitoringService
from src.tasks.timeout_enforcer import TimeoutEnforcementTask
from tests.fixtures.builders import build_scenario
from tests.fixtures.factories import create_monitoring_process


pytestmark = [pytest.mark.unit, pytest.mark.database, pytest.mark.celery]


def _bind_task_sessions(task, db_engine):
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _get_async_session():
        return session_factory()

    task.get_async_session = _get_async_session
    return task


async def test_timeout_enforcer_stops_only_overdue_processes(
    db_session,
    db_engine,
    monkeypatch,
):
    scenario = await build_scenario("minimal_happy_path", db_session)
    overdue_process = scenario["process"]
    overdue_process.started_at = datetime.now(timezone.utc) - timedelta(minutes=31)
    overdue_process.max_duration_minutes = 30
    overdue_process.status = "running"
    overdue_process.is_active = True

    fresh_process = await create_monitoring_process(
        db_session,
        user=scenario["user"],
        llm_provider=scenario["provider"],
        mymoment_logins=scenario["logins"],
        prompt_templates=scenario["prompts"],
        status="running",
        started_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        max_duration_minutes=30,
    )
    await db_session.commit()

    monkeypatch.setattr(MonitoringService, "_revoke_process_tasks", lambda self, process: {})

    task = _bind_task_sessions(TimeoutEnforcementTask(), db_engine)
    result = await task._check_process_timeouts_async()

    assert result["total_processes"] == 2
    assert result["timeout_processes"] == 1
    assert result["stopped_processes"] == 1
    assert result["errors"] == []

    await db_session.refresh(overdue_process)
    await db_session.refresh(fresh_process)
    assert overdue_process.status == "stopped"
    assert overdue_process.stopped_at is not None
    assert fresh_process.status == "running"
    assert fresh_process.stopped_at is None
