"""add llm_provider_id to monitoring_processes

Revision ID: a1b2c3d4e5f6
Revises: 9c0b8ec3260d
Create Date: 2026-03-25 12:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '2526bb29dffe'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('monitoring_processes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('llm_provider_id', sa.UUID(), nullable=True))
        batch_op.create_foreign_key(
            'fk_monitoring_processes_llm_provider',
            'llm_provider_configurations',
            ['llm_provider_id'], ['id'],
            ondelete='SET NULL'
        )


def downgrade() -> None:
    with op.batch_alter_table('monitoring_processes', schema=None) as batch_op:
        batch_op.drop_constraint('fk_monitoring_processes_llm_provider', type_='foreignkey')
        batch_op.drop_column('llm_provider_id')
