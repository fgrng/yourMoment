"""Fix AIComment constraints for prepared status

Revision ID: f8f3ae517756
Revises: 126e5931a1ba
Create Date: 2025-10-09 20:04:52.272031

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f8f3ae517756'
down_revision = '126e5931a1ba'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Update AIComment table to support 'prepared' status workflow:
    1. Make article_content and article_raw_html nullable (for 'discovered' stage)
    2. Update constraint to allow NULL comment_content for both 'discovered' and 'prepared' statuses

    SQLite doesn't support ALTER COLUMN or DROP CONSTRAINT, so we need to:
    1. Create new table with updated schema
    2. Copy data
    3. Drop old table
    4. Rename new table
    """

    # Step 0: Drop temp table if it exists from previous failed migration
    op.execute("DROP TABLE IF EXISTS ai_comments_new")

    # Step 1: Create new table with correct schema
    op.execute("""
        CREATE TABLE ai_comments_new (
            id UUID NOT NULL PRIMARY KEY,
            mymoment_article_id VARCHAR(100) NOT NULL,
            mymoment_comment_id VARCHAR(100),
            user_id UUID NOT NULL,
            mymoment_login_id UUID,
            monitoring_process_id UUID,
            prompt_template_id UUID,
            llm_provider_id UUID,
            article_title TEXT NOT NULL,
            article_author VARCHAR(200) NOT NULL,
            article_category INTEGER,
            article_url VARCHAR(500) NOT NULL,
            article_content TEXT,
            article_raw_html TEXT,
            article_published_at DATETIME,
            article_edited_at DATETIME,
            article_scraped_at DATETIME NOT NULL,
            article_metadata JSON,
            comment_content TEXT,
            status VARCHAR(20) NOT NULL DEFAULT 'discovered',
            ai_model_name VARCHAR(100),
            ai_provider_name VARCHAR(50),
            generation_tokens INTEGER,
            generation_time_ms INTEGER,
            created_at DATETIME NOT NULL,
            posted_at DATETIME,
            failed_at DATETIME,
            error_message TEXT,
            retry_count INTEGER NOT NULL DEFAULT 0,
            is_active BOOLEAN NOT NULL DEFAULT 1,
            FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
            FOREIGN KEY(mymoment_login_id) REFERENCES mymoment_logins (id) ON DELETE SET NULL,
            FOREIGN KEY(monitoring_process_id) REFERENCES monitoring_processes (id) ON DELETE SET NULL,
            FOREIGN KEY(prompt_template_id) REFERENCES prompt_templates (id) ON DELETE SET NULL,
            FOREIGN KEY(llm_provider_id) REFERENCES llm_provider_configurations (id) ON DELETE SET NULL,
            CONSTRAINT check_ai_comment_status CHECK (status IN ('discovered', 'prepared', 'generated', 'posted', 'failed', 'deleted')),
            CONSTRAINT check_comment_content_required_after_preparation CHECK ((status IN ('discovered', 'prepared')) OR (comment_content IS NOT NULL)),
            CONSTRAINT check_posted_status_has_timestamp CHECK ((status != 'posted') OR (status = 'posted' AND posted_at IS NOT NULL)),
            CONSTRAINT check_posted_status_has_comment_id CHECK ((status != 'posted') OR (status = 'posted' AND mymoment_comment_id IS NOT NULL)),
            CONSTRAINT check_posted_status_has_login CHECK ((status != 'posted') OR (status = 'posted' AND mymoment_login_id IS NOT NULL)),
            CONSTRAINT check_failed_status_has_error CHECK ((status != 'failed') OR (status = 'failed' AND error_message IS NOT NULL)),
            UNIQUE (mymoment_comment_id)
        )
    """)

    # Step 2: Copy data from old table to new table with explicit column names
    op.execute("""
        INSERT INTO ai_comments_new (
            id, mymoment_article_id, mymoment_comment_id, user_id, mymoment_login_id,
            monitoring_process_id, prompt_template_id, llm_provider_id,
            article_title, article_author, article_category, article_url,
            article_content, article_raw_html, article_published_at, article_edited_at,
            article_scraped_at, article_metadata,
            comment_content, status, ai_model_name, ai_provider_name,
            generation_tokens, generation_time_ms,
            created_at, posted_at, failed_at, error_message, retry_count, is_active
        )
        SELECT
            id, mymoment_article_id, mymoment_comment_id, user_id, mymoment_login_id,
            monitoring_process_id, prompt_template_id, llm_provider_id,
            article_title, article_author, article_category, article_url,
            article_content, article_raw_html, article_published_at, article_edited_at,
            article_scraped_at, article_metadata,
            comment_content, status, ai_model_name, ai_provider_name,
            generation_tokens, generation_time_ms,
            created_at, posted_at, failed_at, error_message, retry_count, is_active
        FROM ai_comments
    """)

    # Step 3: Drop old table
    op.execute("DROP TABLE ai_comments")

    # Step 4: Rename new table to original name
    op.execute("ALTER TABLE ai_comments_new RENAME TO ai_comments")

    # Step 5: Recreate indexes
    op.execute("CREATE INDEX ix_ai_comments_mymoment_article_id ON ai_comments (mymoment_article_id)")
    op.execute("CREATE INDEX ix_ai_comments_user_id ON ai_comments (user_id)")
    op.execute("CREATE INDEX ix_ai_comments_mymoment_login_id ON ai_comments (mymoment_login_id)")
    op.execute("CREATE INDEX ix_ai_comments_monitoring_process_id ON ai_comments (monitoring_process_id)")
    op.execute("CREATE INDEX ix_ai_comments_status ON ai_comments (status)")


def downgrade() -> None:
    """
    Revert to previous schema where:
    - article_content and article_raw_html are NOT NULL
    - Only 'discovered' status allows NULL comment_content
    """

    # This is a destructive downgrade - any 'prepared' status records will fail
    # Create old table schema
    op.execute("""
        CREATE TABLE ai_comments_old (
            id UUID NOT NULL PRIMARY KEY,
            mymoment_article_id VARCHAR(100) NOT NULL,
            mymoment_comment_id VARCHAR(100),
            user_id UUID NOT NULL,
            mymoment_login_id UUID,
            monitoring_process_id UUID,
            prompt_template_id UUID,
            llm_provider_id UUID,
            article_title TEXT NOT NULL,
            article_author VARCHAR(200) NOT NULL,
            article_category INTEGER,
            article_url VARCHAR(500) NOT NULL,
            article_content TEXT NOT NULL,
            article_raw_html TEXT NOT NULL,
            article_published_at DATETIME,
            article_edited_at DATETIME,
            article_scraped_at DATETIME NOT NULL,
            article_metadata JSON,
            comment_content TEXT,
            status VARCHAR(20) NOT NULL DEFAULT 'discovered',
            ai_model_name VARCHAR(100),
            ai_provider_name VARCHAR(50),
            generation_tokens INTEGER,
            generation_time_ms INTEGER,
            created_at DATETIME NOT NULL,
            posted_at DATETIME,
            failed_at DATETIME,
            error_message TEXT,
            retry_count INTEGER NOT NULL DEFAULT 0,
            is_active BOOLEAN NOT NULL DEFAULT 1,
            FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
            FOREIGN KEY(mymoment_login_id) REFERENCES mymoment_logins (id) ON DELETE SET NULL,
            FOREIGN KEY(monitoring_process_id) REFERENCES monitoring_processes (id) ON DELETE SET NULL,
            FOREIGN KEY(prompt_template_id) REFERENCES prompt_templates (id) ON DELETE SET NULL,
            FOREIGN KEY(llm_provider_id) REFERENCES llm_provider_configurations (id) ON DELETE SET NULL,
            CONSTRAINT check_ai_comment_status CHECK (status IN ('discovered', 'prepared', 'generated', 'posted', 'failed', 'deleted')),
            CONSTRAINT check_comment_content_required_after_discovery CHECK ((status = 'discovered') OR (comment_content IS NOT NULL)),
            CONSTRAINT check_posted_status_has_timestamp CHECK ((status != 'posted') OR (status = 'posted' AND posted_at IS NOT NULL)),
            CONSTRAINT check_posted_status_has_comment_id CHECK ((status != 'posted') OR (status = 'posted' AND mymoment_comment_id IS NOT NULL)),
            CONSTRAINT check_posted_status_has_login CHECK ((status != 'posted') OR (status = 'posted' AND mymoment_login_id IS NOT NULL)),
            CONSTRAINT check_failed_status_has_error CHECK ((status != 'failed') OR (status = 'failed' AND error_message IS NOT NULL)),
            UNIQUE (mymoment_comment_id)
        )
    """)

    # Copy data (will fail if any records have NULL article_content/article_raw_html)
    op.execute("INSERT INTO ai_comments_old SELECT * FROM ai_comments")

    # Drop new table and rename old
    op.execute("DROP TABLE ai_comments")
    op.execute("ALTER TABLE ai_comments_old RENAME TO ai_comments")

    # Recreate indexes
    op.execute("CREATE INDEX ix_ai_comments_mymoment_article_id ON ai_comments (mymoment_article_id)")
    op.execute("CREATE INDEX ix_ai_comments_user_id ON ai_comments (user_id)")
    op.execute("CREATE INDEX ix_ai_comments_mymoment_login_id ON ai_comments (mymoment_login_id)")
    op.execute("CREATE INDEX ix_ai_comments_monitoring_process_id ON ai_comments (monitoring_process_id)")
    op.execute("CREATE INDEX ix_ai_comments_status ON ai_comments (status)")