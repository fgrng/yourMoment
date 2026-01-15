"""
AI Comment model - stores AI-generated comments with article snapshots.

This model consolidates article snapshots and AI comments into a single entity.
When an AI comment is generated and posted to myMoment, we capture:
1. The complete article snapshot (title, author, content, HTML) at that moment
2. The AI-generated comment content and metadata
3. Tracking information (login, process, timestamps)

This design ensures:
- Immutable audit trail: article content at comment time is preserved
- Single source of truth: one record = one AI commenting action
- No orphaned data: article snapshot lifecycle tied to comment lifecycle

Status workflow:
- discovered: Article discovered, basic metadata captured (no content yet)
- prepared: Article content fetched and ready for comment generation
- generated: AI comment generated but not yet posted
- posted: Comment successfully posted to myMoment
- failed: Operation failed at any stage
- deleted: Soft-deleted record
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, String, Text, DateTime, Integer, Boolean, UUID, ForeignKey, CheckConstraint, JSON
from sqlalchemy.orm import relationship

from src.models.base import Base, BaseModel
from src.config.settings import get_settings


class AIComment(BaseModel):
    """
    AI Comment stores AI-generated comments with immutable article snapshots.

    Each record represents a single AI commenting action, capturing both:
    - The article content as it appeared when the comment was generated
    - The AI comment itself and all related metadata

    This model replaces the need for separate Article and Comment tables for
    AI-generated comments, as article data is only persisted when we comment on it.
    """

    __tablename__ = "ai_comments"

    # Primary fields
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)

    # myMoment external identifiers
    mymoment_article_id = Column(String(100), nullable=False, index=True)  # Article ID on myMoment
    mymoment_comment_id = Column(String(100), nullable=True, unique=True)  # Comment ID after posting

    # Foreign keys - tracking who/what generated this comment
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    mymoment_login_id = Column(
        UUID(as_uuid=True),
        ForeignKey("mymoment_logins.id", ondelete="SET NULL"),
        nullable=True,  # Set when comment is posted
        index=True
    )
    monitoring_process_id = Column(
        UUID(as_uuid=True),
        ForeignKey("monitoring_processes.id", ondelete="SET NULL"),
        nullable=True,  # Set when generated via monitoring process
        index=True
    )
    prompt_template_id = Column(
        UUID(as_uuid=True),
        ForeignKey("prompt_templates.id", ondelete="SET NULL"),
        nullable=True  # Which prompt template was used
    )
    llm_provider_id = Column(
        UUID(as_uuid=True),
        ForeignKey("llm_provider_configurations.id", ondelete="SET NULL"),
        nullable=True  # Which LLM provider was used
    )

    # ========================================
    # ARTICLE SNAPSHOT FIELDS
    # (captured at comment generation time)
    # ========================================

    # Article metadata
    article_title = Column(Text, nullable=False)
    article_author = Column(String(200), nullable=False)
    article_category = Column(Integer, nullable=True)  # myMoment category ID
    article_task_id = Column(Integer, nullable=True)  # myMoment task/Aufgabe ID
    article_url = Column(String(500), nullable=False)  # myMoment article URL

    # Article content (frozen snapshot)
    # nullable=True to support discovered -> prepared workflow
    article_content = Column(Text, nullable=True)  # Processed text content (populated in 'prepared' stage)
    article_raw_html = Column(Text, nullable=True)  # Original HTML (populated in 'prepared' stage)

    # Article timestamps
    article_published_at = Column(DateTime(timezone=True), nullable=True)  # When published on myMoment
    article_edited_at = Column(DateTime(timezone=True), nullable=True)  # Last edit on myMoment
    article_scraped_at = Column(DateTime(timezone=True), nullable=False)  # When we captured this snapshot

    # Article metadata (optional)
    article_metadata = Column(JSON, nullable=True)  # Additional metadata as JSON

    # ========================================
    # AI COMMENT FIELDS
    # ========================================

    # Comment content (nullable to support discovered->generated->posted workflow)
    comment_content = Column(Text, nullable=True)

    # Comment visibility on myMoment
    is_hidden = Column(Boolean, nullable=False, default=False)  # Whether comment is hidden on myMoment

    # Comment status
    status = Column(
        String(20),
        nullable=False,
        default=lambda: "discovered",
        index=True
    )  # discovered, prepared, generated, posted, failed, deleted

    # Comment generation metadata
    ai_model_name = Column(String(100), nullable=True)  # e.g., "claude-3-opus-20240229"
    ai_provider_name = Column(String(50), nullable=True)  # e.g., "openai", "mistral"
    generation_tokens = Column(Integer, nullable=True)  # Token count for generation
    generation_time_ms = Column(Integer, nullable=True)  # Time taken to generate (milliseconds)

    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)  # When comment generated
    posted_at = Column(DateTime(timezone=True), nullable=True)  # When successfully posted to myMoment
    failed_at = Column(DateTime(timezone=True), nullable=True)  # When posting failed (if applicable)

    # Error tracking
    error_message = Column(Text, nullable=True)  # Error message if posting failed
    retry_count = Column(Integer, nullable=False, default=0)  # Number of posting attempts

    # Soft delete
    is_active = Column(Boolean, nullable=False, default=True)

    # Relationships
    user = relationship("User", back_populates="ai_comments")
    mymoment_login = relationship("MyMomentLogin", back_populates="ai_comments")
    monitoring_process = relationship("MonitoringProcess", back_populates="ai_comments")
    prompt_template = relationship("PromptTemplate", back_populates="ai_comments")
    llm_provider = relationship("LLMProviderConfiguration", back_populates="ai_comments")

    # Constraints
    __table_args__ = (
        CheckConstraint(
            "status IN ('discovered', 'prepared', 'generated', 'posted', 'failed', 'deleted')",
            name="check_ai_comment_status"
        ),
        CheckConstraint(
            "(status IN ('discovered', 'prepared')) OR (comment_content IS NOT NULL)",
            name="check_comment_content_required_after_preparation"
        ),
        CheckConstraint(
            "(status != 'posted') OR (status = 'posted' AND posted_at IS NOT NULL)",
            name="check_posted_status_has_timestamp"
        ),
        CheckConstraint(
            "(status != 'posted') OR (status = 'posted' AND mymoment_comment_id IS NOT NULL)",
            name="check_posted_status_has_comment_id"
        ),
        CheckConstraint(
            "(status != 'posted') OR (status = 'posted' AND mymoment_login_id IS NOT NULL)",
            name="check_posted_status_has_login"
        ),
        CheckConstraint(
            "(status != 'failed') OR (status = 'failed' AND error_message IS NOT NULL)",
            name="check_failed_status_has_error"
        ),
    )

    def __init__(self, **kwargs):
        """Initialize AIComment with default values if not provided."""
        if 'status' not in kwargs:
            kwargs['status'] = 'discovered'
        if 'is_active' not in kwargs:
            kwargs['is_active'] = True
        if 'is_hidden' not in kwargs:
            kwargs['is_hidden'] = False
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return (
            f"<AIComment("
            f"id={self.id}, "
            f"article_id={self.mymoment_article_id}, "
            f"status={self.status}, "
            f"title='{self.article_title[:30]}...'"
            f")>"
        )

    @property
    def is_posted(self) -> bool:
        """Check if this comment was successfully posted to myMoment."""
        return self.status == "posted"

    @property
    def is_failed(self) -> bool:
        """Check if posting this comment failed."""
        return self.status == "failed"

    @property
    def is_discovered(self) -> bool:
        """Check if this article is discovered but comment not yet generated."""
        return self.status == "discovered"

    @property
    def is_prepared(self) -> bool:
        """Check if this article is prepared with full content but comment not yet generated."""
        return self.status == "prepared"

    @property
    def is_generated(self) -> bool:
        """Check if this comment is generated but not yet posted."""
        return self.status == "generated"

    @property
    def has_valid_ai_prefix(self) -> bool:
        """
        Check if this AI comment follows the required German prefix (FR-006).

        All AI-generated comments must start with the configured AI comment prefix.
        """
        if not self.comment_content:
            return False
        settings = get_settings()
        required_prefix = settings.monitoring.AI_COMMENT_PREFIX
        return self.comment_content.startswith(required_prefix)

    @property
    def short_title(self) -> str:
        """Get a shortened version of the article title for display."""
        if len(self.article_title) <= 100:
            return self.article_title
        return self.article_title[:97] + "..."

    @property
    def short_content(self) -> str:
        """Get a shortened version of the comment content for display."""
        if not self.comment_content:
            return "(Comment not yet generated)"
        if len(self.comment_content) <= 200:
            return self.comment_content
        return self.comment_content[:197] + "..."

    @property
    def posting_status_display(self) -> str:
        """Get a display-friendly status."""
        return {
            "discovered": "Article discovered",
            "prepared": "Article content prepared",
            "generated": "Comment generated (not posted)",
            "posted": "Posted to myMoment",
            "failed": "Posting failed",
            "deleted": "Deleted"
        }.get(self.status, "Unknown")

    def mark_as_posted(
        self,
        mymoment_comment_id: str,
        posted_at: Optional[datetime] = None
    ) -> None:
        """
        Mark this comment as successfully posted to myMoment.

        Args:
            mymoment_comment_id: The comment ID returned by myMoment
            posted_at: When the comment was posted (defaults to now)
        """
        self.status = "posted"
        self.mymoment_comment_id = mymoment_comment_id
        self.posted_at = posted_at or datetime.utcnow()
        self.error_message = None

    def mark_as_failed(
        self,
        error_message: str,
        failed_at: Optional[datetime] = None
    ) -> None:
        """
        Mark this comment posting as failed.

        Args:
            error_message: Description of what went wrong
            failed_at: When the failure occurred (defaults to now)
        """
        self.status = "failed"
        self.error_message = error_message
        self.failed_at = failed_at or datetime.utcnow()
        self.retry_count += 1

    def validate_requirements(self) -> dict:
        """
        Validate that this AI comment meets all requirements.

        Returns a dictionary with validation results.
        """
        validation_results = {
            "has_required_prefix": self.has_valid_ai_prefix,
            "has_monitoring_process": self.monitoring_process_id is not None,
            "has_login_if_posted": self.mymoment_login_id is not None if self.is_posted else True,
            "has_comment_id_if_posted": self.mymoment_comment_id is not None if self.is_posted else True,
            "content_not_empty": bool(self.comment_content and self.comment_content.strip()),
            "article_content_not_empty": bool(self.article_content and self.article_content.strip()),
            "article_title_not_empty": bool(self.article_title and self.article_title.strip()),
        }

        validation_results["is_valid"] = all(validation_results.values())
        return validation_results

    def to_article_snapshot_dict(self) -> dict:
        """
        Return the article snapshot as a dictionary.

        Useful for API responses that need article information.
        """
        return {
            "mymoment_article_id": self.mymoment_article_id,
            "title": self.article_title,
            "author": self.article_author,
            "category": self.article_category,
            "task_id": self.article_task_id,
            "url": self.article_url,
            "content": self.article_content,
            "raw_html": self.article_raw_html,
            "published_at": self.article_published_at,
            "edited_at": self.article_edited_at,
            "scraped_at": self.article_scraped_at,
        }

    def to_comment_dict(self) -> dict:
        """
        Return the comment information as a dictionary.

        Useful for API responses that need comment information.
        """
        return {
            "id": self.id,
            "mymoment_comment_id": self.mymoment_comment_id,
            "content": self.comment_content,
            "status": self.status,
            "is_posted": self.is_posted,
            "is_hidden": self.is_hidden,
            "created_at": self.created_at,
            "posted_at": self.posted_at,
            "ai_model_name": self.ai_model_name,
            "ai_provider_name": self.ai_provider_name,
        }
