"""
ArticleVersion model for yourMoment Student Backup feature.

Stores versioned snapshots of student articles from myMoment.
Each version captures the article content at a specific point in time,
enabling tracking of revision activity over time.
"""

import uuid
import hashlib
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, Text, func, UUID, JSON
from sqlalchemy.orm import relationship

from src.models.base import Base

# Avoid circular imports
if TYPE_CHECKING:
    from src.models.user import User
    from src.models.tracked_student import TrackedStudent


class ArticleVersion(Base):
    """
    ArticleVersion model for storing versioned snapshots of student articles.

    Implements the versioning aspect of the Student Backup feature:
    - Captures article content at specific points in time
    - Uses SHA-256 content hash to detect changes
    - Maintains version history with sequential version numbers
    - Stores both plain text and raw HTML content
    """

    __tablename__ = "article_versions"

    # Primary key
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique identifier for this article version"
    )

    # Foreign key to User (who owns this backup)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="User who owns this backup"
    )

    # Foreign key to TrackedStudent
    tracked_student_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tracked_students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Tracked student this article belongs to"
    )

    # myMoment article ID
    mymoment_article_id = Column(
        Integer,
        nullable=False,
        index=True,
        doc="Article ID on myMoment platform (e.g., 2695)"
    )

    # Version number (sequential per article)
    version_number = Column(
        Integer,
        nullable=False,
        default=1,
        doc="Sequential version number for this article"
    )

    # Article metadata
    article_title = Column(
        String(500),
        nullable=True,
        doc="Article title"
    )

    article_url = Column(
        String(500),
        nullable=True,
        doc="View URL for the article (e.g., /article/2695/)"
    )

    # Article content
    article_content = Column(
        Text,
        nullable=True,
        doc="Plain text content of the article"
    )

    article_raw_html = Column(
        Text,
        nullable=True,
        doc="Original HTML content of the article"
    )

    # Article status and visibility
    article_status = Column(
        String(100),
        nullable=True,
        doc="Publication status (Publiziert, Entwurf, Lehrpersonenkontrolle)"
    )

    article_visibility = Column(
        String(255),
        nullable=True,
        doc="Visibility/class info (e.g., '3. Klasse (Primarschule Schachen)')"
    )

    article_category = Column(
        String(100),
        nullable=True,
        doc="Article category (e.g., 'Unterhalten', 'Informieren')"
    )

    article_task = Column(
        String(255),
        nullable=True,
        doc="Writing task if article was published to a task"
    )

    # Timestamps from myMoment
    article_last_modified = Column(
        DateTime(timezone=True),
        nullable=True,
        doc="Last modification timestamp from myMoment"
    )

    # Scraping metadata
    scraped_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="When this version was captured"
    )

    # Content hash for change detection
    content_hash = Column(
        String(64),
        nullable=True,
        index=True,
        doc="SHA-256 hash of article_content for change detection"
    )

    # Additional metadata (JSON)
    extra_metadata = Column(
        JSON,
        nullable=True,
        doc="Additional metadata as JSON"
    )

    # Status
    is_active = Column(
        Boolean,
        default=True,
        nullable=False,
        doc="Whether this version is active (soft delete)"
    )

    # Relationships
    user = relationship(
        "User",
        back_populates="article_versions",
        doc="User who owns this backup"
    )

    tracked_student = relationship(
        "TrackedStudent",
        back_populates="article_versions",
        doc="Tracked student this article belongs to"
    )

    def __repr__(self) -> str:
        """String representation of ArticleVersion."""
        return (
            f"<ArticleVersion(id={self.id}, article_id={self.mymoment_article_id}, "
            f"version={self.version_number}, title='{self.article_title[:30] if self.article_title else 'N/A'}...')>"
        )

    def to_dict(self, include_content: bool = False) -> dict:
        """
        Convert article version to dictionary representation.

        Args:
            include_content: Whether to include full content fields

        Returns:
            Dictionary representation of the article version
        """
        result = {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "tracked_student_id": str(self.tracked_student_id),
            "mymoment_article_id": self.mymoment_article_id,
            "version_number": self.version_number,
            "article_title": self.article_title,
            "article_url": self.article_url,
            "article_status": self.article_status,
            "article_visibility": self.article_visibility,
            "article_category": self.article_category,
            "article_task": self.article_task,
            "article_last_modified": (
                self.article_last_modified.isoformat() if self.article_last_modified else None
            ),
            "scraped_at": self.scraped_at.isoformat() if self.scraped_at else None,
            "content_hash": self.content_hash,
            "is_active": self.is_active,
        }

        if include_content:
            result["article_content"] = self.article_content
            result["article_raw_html"] = self.article_raw_html
            result["extra_metadata"] = self.extra_metadata

        return result

    @staticmethod
    def compute_content_hash(content: str) -> str:
        """
        Compute SHA-256 hash of content for change detection.

        Args:
            content: The content to hash

        Returns:
            Hexadecimal SHA-256 hash string
        """
        if not content:
            return hashlib.sha256(b"").hexdigest()
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def set_content(self, content: str, raw_html: Optional[str] = None) -> None:
        """
        Set article content and compute hash.

        Args:
            content: Plain text content
            raw_html: Optional raw HTML content
        """
        self.article_content = content
        self.article_raw_html = raw_html
        self.content_hash = self.compute_content_hash(content)

    def has_content_changed(self, new_content: str) -> bool:
        """
        Check if new content is different from current content.

        Args:
            new_content: New content to compare

        Returns:
            True if content has changed, False otherwise
        """
        new_hash = self.compute_content_hash(new_content)
        return new_hash != self.content_hash

    def deactivate(self) -> None:
        """Soft delete this version."""
        self.is_active = False

    @property
    def view_url(self) -> str:
        """
        Get the myMoment view URL for this article.

        Returns:
            Full URL to view the article on myMoment
        """
        return f"https://www.mymoment.ch/article/{self.mymoment_article_id}/"

    @property
    def edit_url(self) -> str:
        """
        Get the myMoment edit URL for this article.

        Returns:
            Full URL to edit the article on myMoment
        """
        return f"https://www.mymoment.ch/article/edit/{self.mymoment_article_id}/"

    @property
    def content_preview(self) -> str:
        """
        Get a preview of the article content.

        Returns:
            First 200 characters of content with ellipsis if truncated
        """
        if not self.article_content:
            return ""
        if len(self.article_content) <= 200:
            return self.article_content
        return self.article_content[:200] + "..."
