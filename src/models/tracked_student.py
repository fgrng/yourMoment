"""
TrackedStudent model for yourMoment Student Backup feature.

Stores information about students whose articles should be backed up and versioned.
Each tracked student is associated with a user (who tracks them) and an admin login
(which has access to the student's dashboard on myMoment).
"""

import uuid
from datetime import datetime
from typing import List, TYPE_CHECKING, Optional

from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, Text, func, UUID
from sqlalchemy.orm import relationship, validates

from src.models.base import Base

# Avoid circular imports
if TYPE_CHECKING:
    from src.models.user import User
    from src.models.mymoment_login import MyMomentLogin
    from src.models.article_version import ArticleVersion


class TrackedStudent(Base):
    """
    TrackedStudent model for tracking students whose articles should be backed up.

    Implements the Student Backup feature which allows users to:
    - Track specific students by their myMoment user ID
    - Use admin credentials to access student dashboards
    - Periodically backup and version student articles

    Important constraints:
    - Only admin logins (is_admin=True) can be used for tracking
    - Each student can only be tracked once per user
    """

    __tablename__ = "tracked_students"

    # Primary key
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique identifier for the tracked student record"
    )

    # Foreign key to User (who is tracking this student)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="User who is tracking this student"
    )

    # Foreign key to MyMomentLogin (admin account for scraping)
    mymoment_login_id = Column(
        UUID(as_uuid=True),
        ForeignKey("mymoment_logins.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Admin login credentials for accessing student dashboard"
    )

    # myMoment student ID (the student being tracked)
    mymoment_student_id = Column(
        Integer,
        nullable=False,
        index=True,
        doc="Student's user ID on myMoment platform (e.g., 1417)"
    )

    # Optional display name for easy identification
    display_name = Column(
        String(255),
        nullable=True,
        doc="Optional friendly name for this tracked student"
    )

    # Optional notes
    notes = Column(
        Text,
        nullable=True,
        doc="Optional notes about this tracked student"
    )

    # Status fields
    is_active = Column(
        Boolean,
        default=True,
        nullable=False,
        doc="Whether this tracking is active"
    )

    # Timestamp fields
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="When tracking was created"
    )

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        doc="Last update timestamp"
    )

    last_backup_at = Column(
        DateTime(timezone=True),
        nullable=True,
        doc="When the last successful backup was performed"
    )

    # Relationships
    user = relationship(
        "User",
        back_populates="tracked_students",
        doc="User who owns this tracking"
    )

    mymoment_login = relationship(
        "MyMomentLogin",
        back_populates="tracked_students",
        doc="Admin login used for accessing student dashboard"
    )

    article_versions = relationship(
        "ArticleVersion",
        back_populates="tracked_student",
        cascade="all, delete-orphan",
        doc="Versioned articles for this tracked student"
    )

    def __repr__(self) -> str:
        """String representation of TrackedStudent."""
        return (
            f"<TrackedStudent(id={self.id}, user_id={self.user_id}, "
            f"mymoment_student_id={self.mymoment_student_id}, is_active={self.is_active})>"
        )

    def to_dict(self) -> dict:
        """
        Convert tracked student to dictionary representation.

        Returns:
            Dictionary representation of the tracked student
        """
        return {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "mymoment_login_id": str(self.mymoment_login_id) if self.mymoment_login_id else None,
            "mymoment_student_id": self.mymoment_student_id,
            "display_name": self.display_name,
            "notes": self.notes,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "last_backup_at": self.last_backup_at.isoformat() if self.last_backup_at else None,
        }

    def mark_backup_completed(self) -> None:
        """Mark the last backup timestamp as now."""
        self.last_backup_at = datetime.utcnow()

    def deactivate(self) -> None:
        """Deactivate this tracking."""
        self.is_active = False
        self.updated_at = datetime.utcnow()

    def activate(self) -> None:
        """Activate this tracking."""
        self.is_active = True
        self.updated_at = datetime.utcnow()

    def get_article_count(self) -> int:
        """
        Get count of unique articles tracked for this student.

        Returns:
            Number of unique mymoment_article_ids
        """
        if 'article_versions' not in self.__dict__:
            return 0

        if not self.article_versions:
            return 0

        unique_articles = set(
            av.mymoment_article_id for av in self.article_versions if av.is_active
        )
        return len(unique_articles)

    def get_total_versions_count(self) -> int:
        """
        Get total count of article versions for this student.

        Returns:
            Total number of active article versions
        """
        if 'article_versions' not in self.__dict__:
            return 0

        if not self.article_versions:
            return 0

        return sum(1 for av in self.article_versions if av.is_active)

    @property
    def dashboard_url(self) -> str:
        """
        Get the myMoment dashboard URL for this student.

        Returns:
            Full URL to the student's dashboard on myMoment
        """
        return f"https://www.mymoment.ch/dashboard/user/{self.mymoment_student_id}/"
