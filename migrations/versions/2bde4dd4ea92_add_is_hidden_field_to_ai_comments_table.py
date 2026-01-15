"""Add is_hidden field to ai_comments table

Revision ID: 2bde4dd4ea92
Revises: ef36ae3ec41f
Create Date: 2026-01-14 13:03:38.505976

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2bde4dd4ea92'
down_revision = 'ef36ae3ec41f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add is_hidden column to ai_comments table
    op.add_column(
        'ai_comments',
        sa.Column('is_hidden', sa.Boolean(), nullable=False, server_default='0')
    )


def downgrade() -> None:
    # Remove is_hidden column from ai_comments table
    op.drop_column('ai_comments', 'is_hidden')