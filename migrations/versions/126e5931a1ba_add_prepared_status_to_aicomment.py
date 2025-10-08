"""Add prepared status to AIComment

Revision ID: 126e5931a1ba
Revises: 001_initial_schema
Create Date: 2025-10-08 09:05:32.367821

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '126e5931a1ba'
down_revision = '001_initial_schema'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Use batch mode for SQLite compatibility
    with op.batch_alter_table('ai_comments', schema=None) as batch_op:
        # Drop the old check constraint
        batch_op.drop_constraint('check_ai_comment_status', type_='check')

        # Create the new check constraint with 'prepared' status included
        batch_op.create_check_constraint(
            'check_ai_comment_status',
            "status IN ('discovered', 'prepared', 'generated', 'posted', 'failed', 'deleted')"
        )


def downgrade() -> None:
    # Use batch mode for SQLite compatibility
    with op.batch_alter_table('ai_comments', schema=None) as batch_op:
        # Drop the new check constraint
        batch_op.drop_constraint('check_ai_comment_status', type_='check')

        # Restore the old check constraint without 'prepared' status
        batch_op.create_check_constraint(
            'check_ai_comment_status',
            "status IN ('discovered', 'generated', 'posted', 'failed', 'deleted')"
        )