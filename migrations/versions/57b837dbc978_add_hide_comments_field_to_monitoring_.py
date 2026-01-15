"""Add hide_comments field to monitoring_processes table

Revision ID: 57b837dbc978
Revises: 2bde4dd4ea92
Create Date: 2026-01-14 13:20:33.215626

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '57b837dbc978'
down_revision = '2bde4dd4ea92'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add hide_comments column to monitoring_processes table
    op.add_column(
        'monitoring_processes',
        sa.Column('hide_comments', sa.Boolean(), nullable=False, server_default='0')
    )


def downgrade() -> None:
    # Remove hide_comments column from monitoring_processes table
    op.drop_column('monitoring_processes', 'hide_comments')