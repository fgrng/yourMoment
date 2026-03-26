"""add_student_backup_tables

Revision ID: eb82f700314e
Revises: dc495c4925cc
Create Date: 2026-01-28 14:39:26.497589

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'eb82f700314e'
down_revision = 'dc495c4925cc'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Create tracked_students and article_versions tables for Student Backup feature.

    tracked_students: Stores information about students being tracked
    article_versions: Stores versioned snapshots of student articles
    """
    # Create tracked_students table
    op.create_table(
        'tracked_students',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('mymoment_login_id', sa.UUID(), nullable=True),
        sa.Column('mymoment_student_id', sa.Integer(), nullable=False),
        sa.Column('display_name', sa.String(length=255), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('1')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('last_backup_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['mymoment_login_id'], ['mymoment_logins.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tracked_students_user_id'), 'tracked_students', ['user_id'], unique=False)
    op.create_index(op.f('ix_tracked_students_mymoment_login_id'), 'tracked_students', ['mymoment_login_id'], unique=False)
    op.create_index(op.f('ix_tracked_students_mymoment_student_id'), 'tracked_students', ['mymoment_student_id'], unique=False)

    # Create article_versions table
    op.create_table(
        'article_versions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('tracked_student_id', sa.UUID(), nullable=False),
        sa.Column('mymoment_article_id', sa.Integer(), nullable=False),
        sa.Column('version_number', sa.Integer(), nullable=False, server_default=sa.text('1')),
        sa.Column('article_title', sa.String(length=500), nullable=True),
        sa.Column('article_url', sa.String(length=500), nullable=True),
        sa.Column('article_content', sa.Text(), nullable=True),
        sa.Column('article_raw_html', sa.Text(), nullable=True),
        sa.Column('article_status', sa.String(length=100), nullable=True),
        sa.Column('article_visibility', sa.String(length=255), nullable=True),
        sa.Column('article_category', sa.String(length=100), nullable=True),
        sa.Column('article_task', sa.String(length=255), nullable=True),
        sa.Column('article_last_modified', sa.DateTime(timezone=True), nullable=True),
        sa.Column('scraped_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=True),
        sa.Column('extra_metadata', sa.Text(), nullable=True),  # JSON stored as Text for SQLite compatibility
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('1')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tracked_student_id'], ['tracked_students.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_article_versions_user_id'), 'article_versions', ['user_id'], unique=False)
    op.create_index(op.f('ix_article_versions_tracked_student_id'), 'article_versions', ['tracked_student_id'], unique=False)
    op.create_index(op.f('ix_article_versions_mymoment_article_id'), 'article_versions', ['mymoment_article_id'], unique=False)
    op.create_index(op.f('ix_article_versions_content_hash'), 'article_versions', ['content_hash'], unique=False)


def downgrade() -> None:
    """Drop student backup tables."""
    # Drop article_versions table and indexes
    op.drop_index(op.f('ix_article_versions_content_hash'), table_name='article_versions')
    op.drop_index(op.f('ix_article_versions_mymoment_article_id'), table_name='article_versions')
    op.drop_index(op.f('ix_article_versions_tracked_student_id'), table_name='article_versions')
    op.drop_index(op.f('ix_article_versions_user_id'), table_name='article_versions')
    op.drop_table('article_versions')

    # Drop tracked_students table and indexes
    op.drop_index(op.f('ix_tracked_students_mymoment_student_id'), table_name='tracked_students')
    op.drop_index(op.f('ix_tracked_students_mymoment_login_id'), table_name='tracked_students')
    op.drop_index(op.f('ix_tracked_students_user_id'), table_name='tracked_students')
    op.drop_table('tracked_students')