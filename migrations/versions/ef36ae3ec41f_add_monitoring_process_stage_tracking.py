"""add_monitoring_process_stage_tracking_fields

Revision ID: ef36ae3ec41f
Revises: f8f3ae517756
Create Date: 2025-10-10 07:29:11.461662

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ef36ae3ec41f'
down_revision = 'f8f3ae517756'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Using batch_alter_table for SQLite compatibility
    with op.batch_alter_table('monitoring_processes', schema=None) as batch_op:
        # Drop the index on celery_task_id first (SQLite requires this)
        batch_op.drop_index('ix_monitoring_processes_celery_task_id')

        # Drop old columns
        batch_op.drop_column('celery_task_id')
        batch_op.drop_column('errors_encountered')  # Old aggregate error column

        # Add 4 new task ID columns for each stage
        batch_op.add_column(sa.Column('celery_discovery_task_id', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('celery_preparation_task_id', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('celery_generation_task_id', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('celery_posting_task_id', sa.String(length=255), nullable=True))

        # Add indexes for the new task ID columns
        batch_op.create_index('ix_monitoring_processes_celery_discovery_task_id', ['celery_discovery_task_id'])
        batch_op.create_index('ix_monitoring_processes_celery_preparation_task_id', ['celery_preparation_task_id'])
        batch_op.create_index('ix_monitoring_processes_celery_generation_task_id', ['celery_generation_task_id'])
        batch_op.create_index('ix_monitoring_processes_celery_posting_task_id', ['celery_posting_task_id'])

        # Add 4 progress tracking columns
        batch_op.add_column(sa.Column('articles_discovered', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('articles_prepared', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('comments_generated', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('comments_posted', sa.Integer(), nullable=False, server_default='0'))

        # Add 4 error tracking columns
        batch_op.add_column(sa.Column('errors_encountered_in_discovery', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('errors_encountered_in_preparation', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('errors_encountered_in_generation', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('errors_encountered_in_posting', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    with op.batch_alter_table('monitoring_processes', schema=None) as batch_op:
        # Drop the 4 error tracking columns
        batch_op.drop_column('errors_encountered_in_posting')
        batch_op.drop_column('errors_encountered_in_generation')
        batch_op.drop_column('errors_encountered_in_preparation')
        batch_op.drop_column('errors_encountered_in_discovery')

        # Drop the 4 progress tracking columns
        batch_op.drop_column('comments_posted')
        batch_op.drop_column('comments_generated')
        batch_op.drop_column('articles_prepared')
        batch_op.drop_column('articles_discovered')

        # Drop indexes for the new task ID columns
        batch_op.drop_index('ix_monitoring_processes_celery_posting_task_id')
        batch_op.drop_index('ix_monitoring_processes_celery_generation_task_id')
        batch_op.drop_index('ix_monitoring_processes_celery_preparation_task_id')
        batch_op.drop_index('ix_monitoring_processes_celery_discovery_task_id')

        # Drop the 4 new task ID columns
        batch_op.drop_column('celery_posting_task_id')
        batch_op.drop_column('celery_generation_task_id')
        batch_op.drop_column('celery_preparation_task_id')
        batch_op.drop_column('celery_discovery_task_id')

        # Re-add the old columns
        batch_op.add_column(sa.Column('celery_task_id', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('errors_encountered', sa.Integer(), nullable=False, server_default='0'))

        # Recreate the index on celery_task_id
        batch_op.create_index('ix_monitoring_processes_celery_task_id', ['celery_task_id'])
