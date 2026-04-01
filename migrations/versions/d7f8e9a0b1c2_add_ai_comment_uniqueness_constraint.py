"""add ai_comments uniqueness constraint for monitoring pipeline

Revision ID: d7f8e9a0b1c2
Revises: c4d5e6f7a8b9
Create Date: 2026-04-01 15:30:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d7f8e9a0b1c2"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


UNIQUE_CONSTRAINT_NAME = "uq_ai_comments_article_process_login_prompt"


def _assert_no_duplicate_ai_comments() -> None:
    bind = op.get_bind()
    duplicate_rows = bind.execute(
        sa.text(
            """
            SELECT
                mymoment_article_id,
                monitoring_process_id,
                mymoment_login_id,
                prompt_template_id,
                COUNT(*) AS duplicate_count
            FROM ai_comments
            WHERE monitoring_process_id IS NOT NULL
              AND mymoment_login_id IS NOT NULL
              AND prompt_template_id IS NOT NULL
            GROUP BY
                mymoment_article_id,
                monitoring_process_id,
                mymoment_login_id,
                prompt_template_id
            HAVING COUNT(*) > 1
            LIMIT 5
            """
        )
    ).fetchall()

    if not duplicate_rows:
        return

    formatted = ", ".join(
        (
            f"article={row[0]!r}, process={row[1]!r}, "
            f"login={row[2]!r}, prompt={row[3]!r}, count={row[4]}"
        )
        for row in duplicate_rows
    )
    raise RuntimeError(
        "Cannot add ai_comments uniqueness constraint because duplicate rows exist. "
        f"Examples: {formatted}"
    )


def upgrade() -> None:
    _assert_no_duplicate_ai_comments()

    with op.batch_alter_table("ai_comments", schema=None) as batch_op:
        batch_op.create_unique_constraint(
            UNIQUE_CONSTRAINT_NAME,
            [
                "mymoment_article_id",
                "monitoring_process_id",
                "mymoment_login_id",
                "prompt_template_id",
            ],
        )


def downgrade() -> None:
    with op.batch_alter_table("ai_comments", schema=None) as batch_op:
        batch_op.drop_constraint(UNIQUE_CONSTRAINT_NAME, type_="unique")
