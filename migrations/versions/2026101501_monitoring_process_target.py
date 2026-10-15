"""store the monitoring process target as one mapping

Revision ID: 2026101501
Revises: 2026070601
Create Date: 2026-10-15 00:00:00.000000

category_filter -> category, task_filter -> arrangement, tab_filter -> classroom
(values as strings, empty columns give no key); sort_option is dropped,
search_filter stays (ADR-0002).
"""
from alembic import op
import sqlalchemy as sa


revision = "2026101501"
down_revision = "2026070601"
branch_labels = None
depends_on = None

# Old column -> key of the target
_KEYS = {"category_filter": "category", "task_filter": "arrangement", "tab_filter": "classroom"}
_INTEGER_COLUMNS = {"category_filter", "task_filter"}


def _processes(*columns: sa.Column) -> sa.Table:
    return sa.table("monitoring_processes", sa.column("id", sa.String()), *columns)


def upgrade() -> None:
    with op.batch_alter_table("monitoring_processes", schema=None) as batch_op:
        batch_op.add_column(sa.Column("target", sa.JSON(), nullable=True))

    bind = op.get_bind()
    old = _processes(*(sa.column(name) for name in _KEYS))
    new = _processes(sa.column("target", sa.JSON()))
    for row in bind.execute(sa.select(old)).mappings().all():
        target = {
            key: str(row[column])
            for column, key in _KEYS.items()
            if row[column] is not None and str(row[column]) != ""
        }
        bind.execute(sa.update(new).where(new.c.id == row["id"]).values(target=target))

    with op.batch_alter_table("monitoring_processes", schema=None) as batch_op:
        batch_op.alter_column("target", existing_type=sa.JSON(), nullable=False)
        batch_op.drop_column("sort_option")
        batch_op.drop_column("tab_filter")
        batch_op.drop_column("task_filter")
        batch_op.drop_column("category_filter")


def downgrade() -> None:
    with op.batch_alter_table("monitoring_processes", schema=None) as batch_op:
        batch_op.add_column(sa.Column("category_filter", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("task_filter", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("tab_filter", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("sort_option", sa.String(length=50), nullable=True))

    bind = op.get_bind()
    old = _processes(*(sa.column(name) for name in _KEYS))
    new = _processes(sa.column("target", sa.JSON()))
    for row in bind.execute(sa.select(new)).mappings().all():
        target = row["target"] or {}
        values = {}
        for column, key in _KEYS.items():
            value = target.get(key)
            if column in _INTEGER_COLUMNS and value is not None:
                value = int(value) if value.isascii() and value.isdigit() else None
            values[column] = value
        bind.execute(sa.update(old).where(old.c.id == row["id"]).values(**values))

    with op.batch_alter_table("monitoring_processes", schema=None) as batch_op:
        batch_op.drop_column("target")
