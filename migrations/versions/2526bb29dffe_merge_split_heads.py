"""merge split heads

Revision ID: 2526bb29dffe
Revises: 57b837dbc978, 2026011301
Create Date: 2026-03-25 11:56:13.472172

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2526bb29dffe'
down_revision = ('57b837dbc978', '2026011301')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass