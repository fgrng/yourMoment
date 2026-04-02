"""drop_monitoring_process_counter_columns

Revision ID: f0c58f54ecfa
Revises: d7f8e9a0b1c2
Create Date: 2026-04-02 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'f0c58f54ecfa'
down_revision = 'd7f8e9a0b1c2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('monitoring_processes', schema=None) as batch_op:
        batch_op.drop_column('articles_discovered')
        batch_op.drop_column('articles_prepared')
        batch_op.drop_column('comments_generated')
        batch_op.drop_column('comments_posted')
        batch_op.drop_column('errors_encountered_in_discovery')
        batch_op.drop_column('errors_encountered_in_preparation')
        batch_op.drop_column('errors_encountered_in_generation')
        batch_op.drop_column('errors_encountered_in_posting')


def downgrade() -> None:
    with op.batch_alter_table('monitoring_processes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('errors_encountered_in_posting',     sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('errors_encountered_in_generation',  sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('errors_encountered_in_preparation', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('errors_encountered_in_discovery',   sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('comments_posted',     sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('comments_generated',  sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('articles_prepared',   sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('articles_discovered', sa.Integer(), nullable=False, server_default='0'))
