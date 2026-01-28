"""add_is_admin_to_mymoment_logins

Revision ID: dc495c4925cc
Revises: 09319578e7e3
Create Date: 2026-01-28 10:23:37.954334

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'dc495c4925cc'
down_revision = '09319578e7e3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Add is_admin column to mymoment_logins table.

    This column distinguishes admin accounts (which can access student dashboards
    for the Student Backup feature) from regular accounts (used for MonitoringProcesses).
    """
    op.add_column(
        'mymoment_logins',
        sa.Column('is_admin', sa.Boolean(), nullable=False, server_default=sa.false())
    )


def downgrade() -> None:
    """Remove is_admin column from mymoment_logins table."""
    op.drop_column('mymoment_logins', 'is_admin')