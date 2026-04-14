from __future__ import annotations

from types import SimpleNamespace
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.tasks import article_discovery, scheduler
from src.tasks.scheduler import SchedulingTask
from tests.fixtures.factories.monitoring import create_monitoring_process
from tests.fixtures.factories.users import create_user


pytestmark = [pytest.mark.unit, pytest.mark.database, pytest.mark.celery]


def _bind_task_sessions(task, db_engine):
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _get_async_session():
        return session_factory()

    task.get_async_session = _get_async_session
    return task


class AsyncResultStub:
    """Small Celery AsyncResult stub for in-flight state checks."""

    def __init__(self, task_id: str, *, state_by_task_id: dict[str, str]):
        self.id = task_id
        self.state = state_by_task_id[task_id]


async def test_trigger_pipeline_async_process_scoped_filters_to_requested_running_active_processes(
    db_session,
    db_engine,
    monkeypatch,
):
    user = await create_user(db_session)
    requested_running = await create_monitoring_process(db_session, user=user, status="running")
    requested_stopped = await create_monitoring_process(db_session, user=user, status="stopped")
    requested_inactive = await create_monitoring_process(
        db_session,
        user=user,
        status="running",
        is_active=False,
    )
    await create_monitoring_process(db_session, user=user, status="running")
    await db_session.commit()
    await db_session.close()

    task = _bind_task_sessions(SchedulingTask(), db_engine)
    seen_process_ids: list[str] = []

    async def fake_spawn(session, process, discover_articles_task, force_immediate=False):
        seen_process_ids.append(str(process.id))
        return {
            "spawned": [
                {
                    "process_id": str(process.id),
                    "stage": "discovery",
                    "task_id": f"task-{process.id}",
                }
            ],
            "skipped": [],
        }

    monkeypatch.setattr(task, "_spawn_stage_tasks_for_process", fake_spawn)

    result = await task._trigger_pipeline_async(
        process_ids=[
            str(requested_running.id),
            str(requested_stopped.id),
            str(requested_inactive.id),
        ]
    )

    assert result["trigger_mode"] == "process_scoped"
    assert result["processes_checked"] == 1
    assert result["tasks_spawned"] == 1
    assert result["tasks_skipped"] == 0
    assert result["errors"] == []
    assert seen_process_ids == [str(requested_running.id)]
    assert result["spawned_details"] == [
        {
            "process_id": str(requested_running.id),
            "stage": "discovery",
            "task_id": f"task-{requested_running.id}",
        }
    ]


async def test_trigger_pipeline_async_process_scoped_reports_invalid_ids(
    db_session,
    db_engine,
    monkeypatch,
):
    user = await create_user(db_session)
    valid_process = await create_monitoring_process(db_session, user=user, status="running")
    await db_session.commit()
    await db_session.close()

    task = _bind_task_sessions(SchedulingTask(), db_engine)
    seen_process_ids: list[str] = []

    async def fake_spawn(session, process, discover_articles_task, force_immediate=False):
        seen_process_ids.append(str(process.id))
        return {
            "spawned": [
                {
                    "process_id": str(process.id),
                    "stage": "discovery",
                    "task_id": f"task-{process.id}",
                }
            ],
            "skipped": [],
        }

    monkeypatch.setattr(task, "_spawn_stage_tasks_for_process", fake_spawn)

    result = await task._trigger_pipeline_async(
        process_ids=["not-a-uuid", None, str(valid_process.id)]
    )

    assert result["trigger_mode"] == "process_scoped"
    assert result["processes_checked"] == 1
    assert result["tasks_spawned"] == 1
    assert result["tasks_skipped"] == 0
    assert len(result["errors"]) == 2
    assert any("not-a-uuid" in error for error in result["errors"])
    assert any("None" in error for error in result["errors"])
    assert seen_process_ids == [str(valid_process.id)]


async def test_trigger_pipeline_async_periodic_global_scans_all_running_active_processes(
    db_session,
    db_engine,
    monkeypatch,
):
    user = await create_user(db_session)
    running_a = await create_monitoring_process(db_session, user=user, status="running")
    running_b = await create_monitoring_process(db_session, user=user, status="running")
    await create_monitoring_process(db_session, user=user, status="stopped")
    await create_monitoring_process(db_session, user=user, status="running", is_active=False)
    await db_session.commit()
    await db_session.close()

    task = _bind_task_sessions(SchedulingTask(), db_engine)
    seen_process_ids: list[str] = []

    async def fake_spawn(session, process, discover_articles_task, force_immediate=False):
        seen_process_ids.append(str(process.id))
        return {
            "spawned": [
                {
                    "process_id": str(process.id),
                    "stage": "discovery",
                    "task_id": f"task-{process.id}",
                }
            ],
            "skipped": [],
        }

    monkeypatch.setattr(task, "_spawn_stage_tasks_for_process", fake_spawn)

    result = await task._trigger_pipeline_async()

    assert result["trigger_mode"] == "periodic_global"
    assert result["processes_checked"] == 2
    assert result["tasks_spawned"] == 2
    assert result["tasks_skipped"] == 0
    assert result["errors"] == []
    assert set(seen_process_ids) == {str(running_a.id), str(running_b.id)}


@pytest.mark.parametrize("task_state", ["STARTED", "RETRY"])
@pytest.mark.parametrize("trigger_mode", ["process_scoped", "periodic_global"])
async def test_trigger_pipeline_async_inflight_guard_skips_started_or_retry_tasks(
    trigger_mode,
    task_state,
    db_session,
    db_engine,
    monkeypatch,
):
    user = await create_user(db_session)
    process = await create_monitoring_process(
        db_session,
        user=user,
        status="running",
        celery_discovery_task_id="existing-discovery-task",
    )
    await db_session.commit()
    await db_session.close()

    task = _bind_task_sessions(SchedulingTask(), db_engine)
    delay_calls: list[str] = []
    state_by_task_id = {process.celery_discovery_task_id: task_state}

    def fake_delay(process_id):
        delay_calls.append(process_id)
        return SimpleNamespace(id=f"new-discovery-task-{process_id}")

    monkeypatch.setattr(article_discovery.discover_articles, "delay", fake_delay)
    monkeypatch.setattr(
        scheduler,
        "AsyncResult",
        lambda task_id: AsyncResultStub(task_id, state_by_task_id=state_by_task_id),
    )

    process_ids = [str(process.id)] if trigger_mode == "process_scoped" else None
    result = await task._trigger_pipeline_async(process_ids=process_ids)

    assert result["trigger_mode"] == trigger_mode
    assert result["processes_checked"] == 1
    assert result["tasks_spawned"] == 0
    assert result["tasks_skipped"] == 1
    assert result["errors"] == []
    assert delay_calls == []
    assert result["spawned_details"] == []
    assert result["skipped_details"] == [
        {
            "process_id": str(process.id),
            "stage": "discovery",
            "task_id": "existing-discovery-task",
            "state": task_state,
            "reason": "already running",
        }
    ]

    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_factory() as verification_session:
        persisted = await verification_session.get(type(process), process.id)
        assert persisted is not None
        assert persisted.celery_discovery_task_id == "existing-discovery-task"


@pytest.mark.parametrize("trigger_mode", ["process_scoped", "periodic_global"])
async def test_trigger_pipeline_async_inflight_guard_spawns_on_pending_state(
    trigger_mode,
    db_session,
    db_engine,
    monkeypatch,
):
    """PENDING must NOT be treated as in-flight — expired results return PENDING.
    The guard must allow re-spawning so stale task IDs don't permanently block a process."""
    user = await create_user(db_session)
    process = await create_monitoring_process(
        db_session,
        user=user,
        status="running",
        celery_discovery_task_id="stale-or-expired-task",
    )
    await db_session.commit()
    await db_session.close()

    task = _bind_task_sessions(SchedulingTask(), db_engine)
    delay_calls: list[str] = []
    state_by_task_id = {process.celery_discovery_task_id: "PENDING"}

    def fake_delay(process_id):
        delay_calls.append(process_id)
        return SimpleNamespace(id=f"new-task-{process_id}")

    monkeypatch.setattr(article_discovery.discover_articles, "delay", fake_delay)
    monkeypatch.setattr(
        scheduler,
        "AsyncResult",
        lambda task_id: AsyncResultStub(task_id, state_by_task_id=state_by_task_id),
    )

    process_ids = [str(process.id)] if trigger_mode == "process_scoped" else None
    result = await task._trigger_pipeline_async(process_ids=process_ids)

    assert result["tasks_spawned"] == 1
    assert result["tasks_skipped"] == 0
    assert delay_calls == [str(process.id)]


@pytest.mark.parametrize("trigger_mode", ["process_scoped", "periodic_global"])
async def test_trigger_pipeline_async_inflight_guard_spawns_on_async_result_exception(
    trigger_mode,
    db_session,
    db_engine,
    monkeypatch,
):
    """If AsyncResult raises, the guard must fail open: log a warning and spawn a new task."""
    user = await create_user(db_session)
    process = await create_monitoring_process(
        db_session,
        user=user,
        status="running",
        celery_discovery_task_id="broken-backend-task",
    )
    await db_session.commit()
    await db_session.close()

    task = _bind_task_sessions(SchedulingTask(), db_engine)
    delay_calls: list[str] = []

    def raising_async_result(task_id):
        raise RuntimeError("Redis backend unreachable")

    def fake_delay(process_id):
        delay_calls.append(process_id)
        return SimpleNamespace(id=f"new-task-{process_id}")

    monkeypatch.setattr(article_discovery.discover_articles, "delay", fake_delay)
    monkeypatch.setattr(scheduler, "AsyncResult", raising_async_result)

    process_ids = [str(process.id)] if trigger_mode == "process_scoped" else None
    result = await task._trigger_pipeline_async(process_ids=process_ids)

    assert result["tasks_spawned"] == 1
    assert result["tasks_skipped"] == 0
    assert delay_calls == [str(process.id)]


def test_trigger_monitoring_pipeline_wrapper_forwards_process_ids_to_async_impl(monkeypatch):
    process_ids = [str(uuid.uuid4())]
    captured: dict[str, object] = {}
    expected_result = {
        "trigger_mode": "process_scoped",
        "processes_checked": 1,
        "tasks_spawned": 1,
        "tasks_skipped": 0,
        "spawned_details": [{"process_id": process_ids[0]}],
        "skipped_details": [],
        "errors": [],
        "execution_time_seconds": 0.01,
        "timestamp": "2026-04-14T08:00:00",
    }

    class FakeSchedulingTask:
        async def _trigger_pipeline_async(self, force_immediate=False, process_ids=None):
            captured["force_immediate"] = force_immediate
            captured["process_ids"] = process_ids
            return expected_result

    monkeypatch.setattr(scheduler, "SchedulingTask", FakeSchedulingTask)

    result = scheduler.trigger_monitoring_pipeline.run(
        force_immediate=True,
        process_ids=process_ids,
    )

    assert result == expected_result
    assert captured == {
        "force_immediate": True,
        "process_ids": process_ids,
    }
