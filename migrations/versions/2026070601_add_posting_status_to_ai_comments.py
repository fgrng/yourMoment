"""add posting status to ai_comments

Revision ID: 2026070601
Revises: 2026041401
Create Date: 2026-07-06 15:20:00.000000

"""
from alembic import op


revision = "2026070601"
down_revision = "2026041401"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Add an explicit in-flight posting status.

    SQLite cannot alter CHECK constraints in place, so recreate ai_comments.
    Any legacy half-claimed rows that used status='posted' without final
    posting metadata are converted to status='posting' during the copy.
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
                CHECK (status IN ('discovered', 'prepared', 'generated', 'posting', 'posted', 'failed', 'deleted')),
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
            UNIQUE (mymoment_comment_id),
            CONSTRAINT uq_ai_comments_article_process_login_prompt
                UNIQUE (mymoment_article_id, monitoring_process_id, mymoment_login_id, prompt_template_id)
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
            comment_content, reasoning_content, is_hidden,
            CASE
                WHEN status = 'posted'
                 AND (posted_at IS NULL OR mymoment_comment_id IS NULL OR mymoment_login_id IS NULL)
                THEN 'posting'
                ELSE status
            END,
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
    """Remove posting status by converting in-flight rows back to generated."""
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
                CHECK ((status IN ('discovered', 'prepared', 'failed')) OR (comment_content IS NOT NULL)),
            CONSTRAINT check_posted_status_has_timestamp
                CHECK ((status != 'posted') OR (status = 'posted' AND posted_at IS NOT NULL)),
            CONSTRAINT check_posted_status_has_comment_id
                CHECK ((status != 'posted') OR (status = 'posted' AND mymoment_comment_id IS NOT NULL)),
            CONSTRAINT check_posted_status_has_login
                CHECK ((status != 'posted') OR (status = 'posted' AND mymoment_login_id IS NOT NULL)),
            CONSTRAINT check_failed_status_has_error
                CHECK ((status != 'failed') OR (status = 'failed' AND error_message IS NOT NULL)),
            UNIQUE (mymoment_comment_id),
            CONSTRAINT uq_ai_comments_article_process_login_prompt
                UNIQUE (mymoment_article_id, monitoring_process_id, mymoment_login_id, prompt_template_id)
        )
    """)

    op.execute("""
        INSERT INTO ai_comments_old (
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
            id, mymoment_article_id,
            CASE WHEN status = 'posting' THEN NULL ELSE mymoment_comment_id END,
            user_id, mymoment_login_id,
            monitoring_process_id, prompt_template_id, llm_provider_id,
            article_title, article_author, article_category, article_task_id, article_url,
            article_content, article_raw_html, article_published_at, article_edited_at,
            article_scraped_at, article_metadata,
            comment_content, reasoning_content, is_hidden,
            CASE WHEN status = 'posting' THEN 'generated' ELSE status END,
            ai_model_name, ai_provider_name, generation_tokens, generation_time_ms,
            created_at,
            CASE WHEN status = 'posting' THEN NULL ELSE posted_at END,
            failed_at, error_message, retry_count, is_active
        FROM ai_comments
    """)

    op.execute("DROP TABLE ai_comments")
    op.execute("ALTER TABLE ai_comments_old RENAME TO ai_comments")

    op.execute("CREATE INDEX ix_ai_comments_mymoment_article_id ON ai_comments (mymoment_article_id)")
    op.execute("CREATE INDEX ix_ai_comments_user_id ON ai_comments (user_id)")
    op.execute("CREATE INDEX ix_ai_comments_mymoment_login_id ON ai_comments (mymoment_login_id)")
    op.execute("CREATE INDEX ix_ai_comments_monitoring_process_id ON ai_comments (monitoring_process_id)")
    op.execute("CREATE INDEX ix_ai_comments_status ON ai_comments (status)")
