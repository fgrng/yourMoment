"""Alembic migrations against a SQLite file with the schema before the migration.

Pattern for migration tests: upgrade a fresh file to the revision before the
migration, insert rows in the old shape, then upgrade to the migration and back.
"""

from __future__ import annotations

import json
import sqlite3
import uuid

import pytest
from alembic import command
from alembic.config import Config


pytestmark = [pytest.mark.unit, pytest.mark.database]


@pytest.fixture
def migrate(tmp_path, monkeypatch):
    """Run `migrate("upgrade"|"downgrade", revision)` against a fresh SQLite file; yields its path."""
    db_file = tmp_path / "migration.db"
    # migrations/env.py reads the URL from here; settings would point at the testing DB
    monkeypatch.setattr("src.config.database.get_alembic_database_url", lambda: f"sqlite:///{db_file}")
    config = Config()
    config.set_main_option("script_location", "migrations")

    def run(direction: str, revision: str) -> None:
        getattr(command, direction)(config, revision)

    run.db_file = db_file
    return run


def _columns(db_file, table):
    with sqlite3.connect(db_file) as conn:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


# --- 2026101501: monitoring process target ---

BEFORE_TARGET = "2026070601"
TARGET = "2026101501"


def _insert_old_process(db_file, *, category, task, tab, search=None, sort=None):
    process_id = uuid.uuid4().hex
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            "INSERT INTO monitoring_processes (id, user_id, name, generate_only, max_duration_minutes, status,"
            " is_active, category_filter, task_filter, tab_filter, search_filter, sort_option)"
            " VALUES (?, ?, 'P', 1, 60, 'created', 1, ?, ?, ?, ?, ?)",
            (process_id, uuid.uuid4().hex, category, task, tab, search, sort),
        )
    return process_id


def _row(db_file, process_id, *columns):
    with sqlite3.connect(db_file) as conn:
        return conn.execute(
            f"SELECT {', '.join(columns)} FROM monitoring_processes WHERE id = ?", (process_id,)
        ).fetchone()


def test_target_migration_moves_the_three_columns_into_target(migrate):
    migrate("upgrade", BEFORE_TARGET)
    full = _insert_old_process(migrate.db_file, category=7, task=12, tab="4711", search="Rotpanda", sort="recent")
    classroom_only = _insert_old_process(migrate.db_file, category=None, task=None, tab="4711")

    migrate("upgrade", TARGET)

    target, search = _row(migrate.db_file, full, "target", "search_filter")
    assert (json.loads(target), search) == ({"category": "7", "arrangement": "12", "classroom": "4711"}, "Rotpanda")
    assert json.loads(_row(migrate.db_file, classroom_only, "target")[0]) == {"classroom": "4711"}


def test_target_migration_gives_empty_columns_no_key(migrate):
    migrate("upgrade", BEFORE_TARGET)
    process = _insert_old_process(migrate.db_file, category=None, task=None, tab="")

    migrate("upgrade", TARGET)

    assert json.loads(_row(migrate.db_file, process, "target")[0]) == {}


def test_target_migration_drops_the_old_columns(migrate):
    migrate("upgrade", BEFORE_TARGET)

    migrate("upgrade", TARGET)

    columns = _columns(migrate.db_file, "monitoring_processes")
    assert {"target", "search_filter"} <= columns
    assert columns.isdisjoint({"category_filter", "task_filter", "tab_filter", "sort_option"})


def test_target_migration_downgrade_restores_the_columns(migrate):
    migrate("upgrade", BEFORE_TARGET)
    full = _insert_old_process(migrate.db_file, category=7, task=12, tab="4711", search="Rotpanda")
    classroom_only = _insert_old_process(migrate.db_file, category=None, task=None, tab="4711")
    migrate("upgrade", TARGET)

    migrate("downgrade", BEFORE_TARGET)

    assert "target" not in _columns(migrate.db_file, "monitoring_processes")
    columns = ("category_filter", "task_filter", "tab_filter", "search_filter", "sort_option")
    assert _row(migrate.db_file, full, *columns) == (7, 12, "4711", "Rotpanda", None)
    assert _row(migrate.db_file, classroom_only, *columns) == (None, None, "4711", None, None)
