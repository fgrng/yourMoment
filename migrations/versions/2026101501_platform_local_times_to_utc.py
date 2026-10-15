"""convert platform local times to UTC

Revision ID: 2026101501
Revises: 2026070601
Create Date: 2026-10-15 00:00:00.000000

myMoment shows times as Europe/Zurich wall-clock time without an offset.
The student dashboard date was stored as if it were UTC, so
article_versions.article_last_modified is 1-2 hours off. No other column was
ever filled from a platform local time.

On PostgreSQL the prompt_templates timestamps also become TIMESTAMPTZ, like
every other DateTime column; SQLite stores both the same way.
"""
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from alembic import op
import sqlalchemy as sa


revision = "2026101501"
down_revision = "2026070601"
branch_labels = None
depends_on = None

MYMOMENT_TIMEZONE = ZoneInfo("Europe/Zurich")

article_versions = sa.table(
    "article_versions",
    sa.column("id"),
    sa.column("article_last_modified", sa.DateTime(timezone=True)),
)


def _wall_clock(value: datetime) -> datetime:
    """The stored digits without offset (SQLite returns naive, PostgreSQL aware values)."""
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _zurich_to_utc(value: datetime) -> datetime:
    return _wall_clock(value).replace(tzinfo=MYMOMENT_TIMEZONE).astimezone(UTC)


def _utc_to_zurich(value: datetime) -> datetime:
    return _wall_clock(value).replace(tzinfo=UTC).astimezone(MYMOMENT_TIMEZONE).replace(tzinfo=UTC)


def _convert_article_last_modified(convert) -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.select(article_versions.c.id, article_versions.c.article_last_modified)
        .where(article_versions.c.article_last_modified.is_not(None))
    ).all()
    for row_id, value in rows:
        bind.execute(
            article_versions.update()
            .where(article_versions.c.id == row_id)
            .values(article_last_modified=convert(value))
        )


def _alter_prompt_template_timestamps(timezone: bool) -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for column in ("created_at", "updated_at"):
        op.alter_column(
            "prompt_templates",
            column,
            type_=sa.DateTime(timezone=timezone),
            postgresql_using=f"{column} AT TIME ZONE 'UTC'",
        )


def upgrade() -> None:
    _convert_article_last_modified(_zurich_to_utc)
    _alter_prompt_template_timestamps(timezone=True)


def downgrade() -> None:
    _alter_prompt_template_timestamps(timezone=False)
    _convert_article_last_modified(_utc_to_zurich)
