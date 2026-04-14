"""add discovery backpressure state to monitoring_processes

Revision ID: 2026041401
Revises: f0c58f54ecfa
Create Date: 2026-04-14 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '2026041401'
down_revision = 'f0c58f54ecfa'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('monitoring_processes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('next_discovery_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(
            sa.Column('discovery_empty_streak', sa.Integer(), nullable=False, server_default='0')
        )
        batch_op.add_column(sa.Column('discovery_queued_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('monitoring_processes', schema=None) as batch_op:
        batch_op.drop_column('discovery_queued_at')
        batch_op.drop_column('discovery_empty_streak')
        batch_op.drop_column('next_discovery_at')
