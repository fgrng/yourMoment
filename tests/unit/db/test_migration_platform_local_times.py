"""Migration of platform local times (Europe/Zurich wall clock) to UTC."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


pytestmark = pytest.mark.database

MIGRATION = Path(__file__).parents[3] / "migrations" / "versions" / "2026101502_platform_local_times_to_utc.py"


def _migration():
    spec = importlib.util.spec_from_file_location("platform_local_times_to_utc", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def connection():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE article_versions (id CHAR(32) PRIMARY KEY, article_last_modified DATETIME)"))
        conn.execute(sa.text("INSERT INTO article_versions VALUES ('a', '2026-07-14 09:30:00.000000'), ('b', '2026-01-14 09:30:00.000000'), ('c', NULL)"))
        yield conn
    engine.dispose()


def _run(connection, step: str) -> None:
    with Operations.context(MigrationContext.configure(connection)):
        getattr(_migration(), step)()


def _stored(connection) -> list:
    return connection.execute(
        sa.text("SELECT article_last_modified FROM article_versions ORDER BY id")
    ).scalars().all()


def test_upgrade_converts_zurich_wall_clock_to_utc_per_value(connection):
    _run(connection, "upgrade")

    assert _stored(connection) == ["2026-07-14 07:30:00.000000", "2026-01-14 08:30:00.000000", None]


def test_downgrade_restores_the_zurich_wall_clock(connection):
    _run(connection, "upgrade")
    _run(connection, "downgrade")

    assert _stored(connection) == ["2026-07-14 09:30:00.000000", "2026-01-14 09:30:00.000000", None]
