"""DB-backed tests for the `UTCDateTime` column type."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text
from sqlalchemy.exc import StatementError

from src.models import MonitoringProcess
from tests.fixtures.factories import create_monitoring_process, create_user


pytestmark = pytest.mark.database


async def _reloaded(db_session, process):
    db_session.expunge(process)
    return await db_session.get(MonitoringProcess, process.id)


async def test_saved_value_is_loaded_as_equal_utc_datetime(db_session):
    started_at = datetime(2026, 7, 14, 7, 30, 15, 123456, tzinfo=UTC)
    user = await create_user(db_session)
    process = await create_monitoring_process(
        db_session, user=user, started_at=started_at
    )

    loaded = await _reloaded(db_session, process)

    assert loaded.started_at.isoformat() == "2026-07-14T07:30:15.123456+00:00"


async def test_saving_a_naive_value_fails(db_session):
    user = await create_user(db_session)

    with pytest.raises(StatementError):
        naive = datetime(2026, 7, 14, 7, 30)  # noqa: DTZ001
        await create_monitoring_process(db_session, user=user, started_at=naive)


async def test_value_in_another_timezone_is_saved_as_the_same_utc_instant(db_session):
    user = await create_user(db_session)
    process = await create_monitoring_process(
        db_session,
        user=user,
        started_at=datetime(2026, 7, 14, 9, 30, tzinfo=ZoneInfo("Europe/Zurich")),
    )

    loaded = await _reloaded(db_session, process)

    assert loaded.started_at.isoformat() == "2026-07-14T07:30:00+00:00"


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ("2026-07-14 07:30:15.123456", "2026-07-14T07:30:15.123456+00:00"),
        ("2026-07-14 07:30:15", "2026-07-14T07:30:15+00:00"),
    ],
)
async def test_existing_value_in_todays_storage_format_is_read_as_utc(
    db_session, stored, expected
):
    user = await create_user(db_session)
    process = await create_monitoring_process(db_session, user=user)
    await db_session.execute(
        text("UPDATE monitoring_processes SET started_at = :stored WHERE id = :id"),
        {"stored": stored, "id": process.id.hex},
    )

    loaded = await _reloaded(db_session, process)

    assert loaded.started_at.isoformat() == expected
