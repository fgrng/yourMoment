"""Add task filter support for myMoment writing tasks

Revision ID: 2026011301
Revises: ef36ae3ec41f
Create Date: 2026-01-13 10:00:00.000000

This migration adds support for filtering by writing tasks (Aufgaben) in addition to categories.
myMoment now separates categories (Kategorien) from writing tasks (Aufgaben), allowing
more granular filtering.

Changes:
- Add task_filter to monitoring_processes table
- Add article_task_id to ai_comments table
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2026011301'
down_revision = 'ef36ae3ec41f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Add task_filter column to monitoring_processes and article_task_id to ai_comments.
    """
    # Add task_filter to monitoring_processes
    with op.batch_alter_table('monitoring_processes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('task_filter', sa.Integer(), nullable=True))

    # Add article_task_id to ai_comments
    with op.batch_alter_table('ai_comments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('article_task_id', sa.Integer(), nullable=True))


def downgrade() -> None:
    """
    Remove task_filter from monitoring_processes and article_task_id from ai_comments.
    """
    # Remove task_filter from monitoring_processes
    with op.batch_alter_table('monitoring_processes', schema=None) as batch_op:
        batch_op.drop_column('task_filter')

    # Remove article_task_id from ai_comments
    with op.batch_alter_table('ai_comments', schema=None) as batch_op:
        batch_op.drop_column('article_task_id')
