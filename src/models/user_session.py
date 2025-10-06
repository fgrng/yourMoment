"""
UserSession model for managing yourMoment application user sessions.

Minimal session approach focused on core functionality without tracking
client information for privacy and simplicity.
"""

import uuid
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import Column, String, DateTime, Boolean, UUID, ForeignKey, Index, func
from sqlalchemy.orm import relationship

from src.models.base import Base


class UserSession(Base):
    """Minimal UserSession for JWT token management and session lifecycle."""

    __tablename__ = "user_sessions"

    # Primary fields
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # Session identification
    token_hash = Column(String(255), nullable=False, unique=True)  # Hashed JWT token

    # Session timing
    expires_at = Column(DateTime(timezone=True), nullable=False)
    last_activity = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Status
    is_active = Column(Boolean, nullable=False, default=True)

    # Relationships
    user = relationship("User", back_populates="user_sessions")

    # Indexes for performance
    __table_args__ = (
        Index("ix_user_sessions_token_hash", "token_hash"),
        Index("ix_user_sessions_user_id_active", "user_id", "is_active"),
        Index("ix_user_sessions_expires_at", "expires_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<UserSession("
            f"id={self.id}, "
            f"user_id={self.user_id}, "
            f"is_active={self.is_active}, "
            f"expires_at={self.expires_at}"
            f")>"
        )

    @property
    def is_expired(self) -> bool:
        """Check if the session has expired."""
        return datetime.utcnow() >= self.expires_at

    @property
    def is_valid(self) -> bool:
        """Check if the session is valid (active and not expired)."""
        return self.is_active and not self.is_expired

    @property
    def time_until_expiry(self) -> timedelta:
        """Get the time remaining until session expiry."""
        if self.is_expired:
            return timedelta(0)
        return self.expires_at - datetime.utcnow()

    @property
    def time_since_last_activity(self) -> timedelta:
        """Get the time elapsed since last activity."""
        return datetime.utcnow() - self.last_activity

    def update_last_activity(self) -> None:
        """Update the last activity timestamp to now."""
        self.last_activity = datetime.utcnow()

    def extend_session(self, additional_time: timedelta) -> None:
        """
        Extend the session expiry time.

        Args:
            additional_time: Additional time to add to the current expiry
        """
        self.expires_at = max(self.expires_at, datetime.utcnow()) + additional_time
        self.update_last_activity()

    def revoke(self) -> None:
        """Revoke the session by marking it inactive."""
        self.is_active = False

    @classmethod
    def create_session(
        cls,
        user_id: uuid.UUID,
        token_hash: str,
        session_duration: timedelta = timedelta(hours=24)
    ) -> "UserSession":
        """
        Create a new user session.

        Args:
            user_id: ID of the user this session belongs to
            token_hash: Hashed JWT token for this session
            session_duration: How long the session should last

        Returns:
            New UserSession instance
        """
        now = datetime.utcnow()
        return cls(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=now + session_duration,
            last_activity=now,
            is_active=True
        )