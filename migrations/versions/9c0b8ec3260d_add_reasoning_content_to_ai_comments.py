"""add reasoning_content to ai_comments

Revision ID: 9c0b8ec3260d
Revises: 2526bb29dffe
Create Date: 2026-03-25 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9c0b8ec3260d'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('ai_comments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('reasoning_content', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('ai_comments', schema=None) as batch_op:
        batch_op.drop_column('reasoning_content')
