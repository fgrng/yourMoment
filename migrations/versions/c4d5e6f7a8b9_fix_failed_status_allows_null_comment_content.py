"""Fix failed status: allow NULL comment_content when status='failed'

The check_comment_content_required_after_preparation constraint previously
required comment_content IS NOT NULL for any status outside
('discovered', 'prepared'). This prevented marking a comment as failed
when generation failed before content was produced (i.e. the record was
still in 'prepared' state with comment_content=NULL).

New constraint adds 'failed' to the exemption list so that generation
failures can always be recorded regardless of whether content exists.

Revision ID: c4d5e6f7a8b9
Revises: 9c0b8ec3260d
Create Date: 2026-04-01 10:30:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'c4d5e6f7a8b9'
down_revision = '9c0b8ec3260d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Update check_comment_content_required_after_preparation to also
    allow NULL comment_content when status='failed'.

    SQLite does not support ALTER CONSTRAINT, so we recreate the table.
    """

    op.execute("DROP TABLE IF EXISTS ai_comments_new")

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
            article_task_id INTEGER,
            article_url VARCHAR(500) NOT NULL,
            article_content TEXT,
            article_raw_html TEXT,
            article_published_at DATETIME,
            article_edited_at DATETIME,
            article_scraped_at DATETIME NOT NULL,
            article_metadata JSON,
            comment_content TEXT,
            reasoning_content TEXT,
            is_hidden BOOLEAN NOT NULL DEFAULT 0,
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
            CONSTRAINT check_ai_comment_status
                CHECK (status IN ('discovered', 'prepared', 'generated', 'posted', 'failed', 'deleted')),
            CONSTRAINT check_comment_content_required_after_preparation
                CHECK ((status IN ('discovered', 'prepared', 'failed')) OR (comment_content IS NOT NULL)),
            CONSTRAINT check_posted_status_has_timestamp
                CHECK ((status != 'posted') OR (status = 'posted' AND posted_at IS NOT NULL)),
            CONSTRAINT check_posted_status_has_comment_id
                CHECK ((status != 'posted') OR (status = 'posted' AND mymoment_comment_id IS NOT NULL)),
            CONSTRAINT check_posted_status_has_login
                CHECK ((status != 'posted') OR (status = 'posted' AND mymoment_login_id IS NOT NULL)),
            CONSTRAINT check_failed_status_has_error
                CHECK ((status != 'failed') OR (status = 'failed' AND error_message IS NOT NULL)),
            UNIQUE (mymoment_comment_id)
        )
    """)

    op.execute("""
        INSERT INTO ai_comments_new (
            id, mymoment_article_id, mymoment_comment_id, user_id, mymoment_login_id,
            monitoring_process_id, prompt_template_id, llm_provider_id,
            article_title, article_author, article_category, article_task_id, article_url,
            article_content, article_raw_html, article_published_at, article_edited_at,
            article_scraped_at, article_metadata,
            comment_content, reasoning_content, is_hidden, status,
            ai_model_name, ai_provider_name, generation_tokens, generation_time_ms,
            created_at, posted_at, failed_at, error_message, retry_count, is_active
        )
        SELECT
            id, mymoment_article_id, mymoment_comment_id, user_id, mymoment_login_id,
            monitoring_process_id, prompt_template_id, llm_provider_id,
            article_title, article_author, article_category, article_task_id, article_url,
            article_content, article_raw_html, article_published_at, article_edited_at,
            article_scraped_at, article_metadata,
            comment_content, reasoning_content, is_hidden, status,
            ai_model_name, ai_provider_name, generation_tokens, generation_time_ms,
            created_at, posted_at, failed_at, error_message, retry_count, is_active
        FROM ai_comments
    """)

    op.execute("DROP TABLE ai_comments")
    op.execute("ALTER TABLE ai_comments_new RENAME TO ai_comments")

    op.execute("CREATE INDEX ix_ai_comments_mymoment_article_id ON ai_comments (mymoment_article_id)")
    op.execute("CREATE INDEX ix_ai_comments_user_id ON ai_comments (user_id)")
    op.execute("CREATE INDEX ix_ai_comments_mymoment_login_id ON ai_comments (mymoment_login_id)")
    op.execute("CREATE INDEX ix_ai_comments_monitoring_process_id ON ai_comments (monitoring_process_id)")
    op.execute("CREATE INDEX ix_ai_comments_status ON ai_comments (status)")


def downgrade() -> None:
    """Revert to constraint that does not allow NULL comment_content for status='failed'."""

    op.execute("DROP TABLE IF EXISTS ai_comments_old")

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
            article_task_id INTEGER,
            article_url VARCHAR(500) NOT NULL,
            article_content TEXT,
            article_raw_html TEXT,
            article_published_at DATETIME,
            article_edited_at DATETIME,
            article_scraped_at DATETIME NOT NULL,
            article_metadata JSON,
            comment_content TEXT,
            reasoning_content TEXT,
            is_hidden BOOLEAN NOT NULL DEFAULT 0,
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
            CONSTRAINT check_ai_comment_status
                CHECK (status IN ('discovered', 'prepared', 'generated', 'posted', 'failed', 'deleted')),
            CONSTRAINT check_comment_content_required_after_preparation
                CHECK ((status IN ('discovered', 'prepared')) OR (comment_content IS NOT NULL)),
            CONSTRAINT check_posted_status_has_timestamp
                CHECK ((status != 'posted') OR (status = 'posted' AND posted_at IS NOT NULL)),
            CONSTRAINT check_posted_status_has_comment_id
                CHECK ((status != 'posted') OR (status = 'posted' AND mymoment_comment_id IS NOT NULL)),
            CONSTRAINT check_posted_status_has_login
                CHECK ((status != 'posted') OR (status = 'posted' AND mymoment_login_id IS NOT NULL)),
            CONSTRAINT check_failed_status_has_error
                CHECK ((status != 'failed') OR (status = 'failed' AND error_message IS NOT NULL)),
            UNIQUE (mymoment_comment_id)
        )
    """)

    op.execute("INSERT INTO ai_comments_old SELECT * FROM ai_comments")
    op.execute("DROP TABLE ai_comments")
    op.execute("ALTER TABLE ai_comments_old RENAME TO ai_comments")

    op.execute("CREATE INDEX ix_ai_comments_mymoment_article_id ON ai_comments (mymoment_article_id)")
    op.execute("CREATE INDEX ix_ai_comments_user_id ON ai_comments (user_id)")
    op.execute("CREATE INDEX ix_ai_comments_mymoment_login_id ON ai_comments (mymoment_login_id)")
    op.execute("CREATE INDEX ix_ai_comments_monitoring_process_id ON ai_comments (monitoring_process_id)")
    op.execute("CREATE INDEX ix_ai_comments_status ON ai_comments (status)")
