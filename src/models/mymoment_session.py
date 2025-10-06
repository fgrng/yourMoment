"""
MyMomentSession model for yourMoment application.

Tracks active login sessions to myMoment platform with session data management.
Implements session lifecycle, TTL cleanup, and encrypted session data storage.
"""

import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Union, TYPE_CHECKING
import json

from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, func, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from src.models.base import Base
from src.config.encryption import encrypt_session_data, decrypt_session_data

# Avoid circular imports
if TYPE_CHECKING:
    from src.models.mymoment_login import MyMomentLogin


class MyMomentSession(Base):
    """
    MyMomentSession model for tracking active sessions to myMoment platform.

    Implements:
    - FR-017: Encrypted session data storage using Fernet
    - Session lifecycle management with TTL
    - Automatic cleanup of expired sessions
    - One active session per myMoment login constraint
    """

    __tablename__ = "mymoment_sessions"

    # Primary key
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique session identifier"
    )

    # Foreign key to MyMomentLogin
    mymoment_login_id = Column(
        UUID(as_uuid=True),
        ForeignKey("mymoment_logins.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="MyMoment login these session belongs to"
    )

    # Encrypted session data (cookies, tokens, etc.)
    session_data_encrypted = Column(
        Text,  # Can be large JSON data
        nullable=False,
        doc="Encrypted session data (cookies, tokens, etc.) - FR-017"
    )

    # Session lifecycle fields
    expires_at = Column(
        DateTime(timezone=True),
        nullable=False,
        doc="Session expiration timestamp"
    )

    is_active = Column(
        Boolean,
        default=True,
        nullable=False,
        doc="Whether session is currently active"
    )

    # Timestamp fields
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="Session creation timestamp"
    )

    last_accessed = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="Last time session was accessed/used"
    )

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        doc="Last session update timestamp"
    )

    # Relationships
    mymoment_login = relationship(
        "MyMomentLogin",
        back_populates="sessions",
        doc="MyMoment login that owns this session"
    )

    def __repr__(self) -> str:
        """String representation of MyMomentSession (safe - no session data)."""
        return (f"<MyMomentSession(id={self.id}, login_id={self.mymoment_login_id}, "
                f"is_active={self.is_active}, expires_at={self.expires_at})>")

    @classmethod
    def create_new_session(
        cls,
        mymoment_login_id: uuid.UUID,
        session_data: Union[str, Dict[str, Any]],
        duration_hours: int = 24
    ) -> "MyMomentSession":
        """
        Create a new MyMoment session with encrypted data.

        Args:
            mymoment_login_id: ID of the myMoment login
            session_data: Session data (cookies, tokens) as string or dict
            duration_hours: Session duration in hours (default 24)

        Returns:
            New MyMomentSession instance
        """
        expires_at = datetime.utcnow() + timedelta(hours=duration_hours)

        session = cls(
            mymoment_login_id=mymoment_login_id,
            expires_at=expires_at,
            is_active=True
        )

        session.set_session_data(session_data)
        return session

    def set_session_data(self, session_data: Union[str, Dict[str, Any]]) -> None:
        """
        Set and encrypt the session data.

        Args:
            session_data: Session data as string or dictionary

        Note:
            Session data is immediately encrypted using Fernet before storage.
            Plaintext session data is never stored.
        """
        encrypted_data = encrypt_session_data(session_data)
        self.session_data_encrypted = encrypted_data
        self.updated_at = datetime.utcnow()

    def get_session_data(self, as_dict: bool = True) -> Union[str, Dict[str, Any]]:
        """
        Decrypt and return the session data.

        Args:
            as_dict: Whether to return as dictionary (True) or string (False)

        Returns:
            Decrypted session data as dict or string

        Raises:
            DecryptionError: If session data cannot be decrypted

        Note:
            Use this method only when actually needed for myMoment requests.
            Session data should not be logged or cached in plaintext.
        """
        return decrypt_session_data(self.session_data_encrypted, as_dict=as_dict)

    def update_session_data(self, new_data: Union[str, Dict[str, Any]]) -> None:
        """
        Update session data with new values.
        """
        self.set_session_data(new_data)
        self.touch()

    def to_dict(self, include_session_data: bool = False) -> dict:
        """
        Convert session to dictionary representation.

        Args:
            include_session_data: Whether to include decrypted session data
                                Should be False for API responses (security)

        Returns:
            Dictionary representation of the session
        """
        session_dict = {
            "id": str(self.id),
            "mymoment_login_id": str(self.mymoment_login_id),
            "is_active": self.is_active,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_accessed": self.last_accessed.isoformat() if self.last_accessed else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

        # Only include decrypted session data if explicitly requested (internal use only)
        if include_session_data:
            try:
                session_dict["session_data"] = self.get_session_data()
            except Exception as e:
                session_dict["session_data"] = f"<encrypted_data_error: {str(e)}>"

        return session_dict

    def is_expired(self) -> bool:
        """
        Check if the session has expired.

        Returns:
            True if session is expired, False otherwise
        """
        return datetime.utcnow() > self.expires_at

    def renew_session(self, duration_hours: int = 24) -> None:
        """
        Renew session with new expiration from current time.
        """
        self.expires_at = datetime.utcnow() + timedelta(hours=duration_hours)
        self.is_active = True
        self.updated_at = datetime.utcnow()

    def touch(self) -> None:
        """
        Update the last_accessed timestamp to current time.

        Should be called whenever the session is used for myMoment requests.
        """
        self.last_accessed = datetime.utcnow()

    def deactivate(self) -> None:
        """
        Deactivate this session.

        This method sets is_active to False and updates the timestamp.
        Deactivated sessions won't be used for new requests.
        """
        self.is_active = False
        self.updated_at = datetime.utcnow()

    def activate(self) -> None:
        """
        Activate this session.

        This method sets is_active to True and updates the timestamp.
        Only works if session is not expired.
        """
        if not self.is_expired():
            self.is_active = True
            self.updated_at = datetime.utcnow()

    def is_usable(self) -> bool:
        """
        Check if session is usable for myMoment requests.

        Returns:
            True if session is active and not expired, False otherwise
        """
        return self.is_active and not self.is_expired()

    def get_remaining_hours(self) -> float:
        """
        Get remaining time in hours before session expires.
        """
        if self.is_expired():
            return 0.0
        return (self.expires_at - datetime.utcnow()).total_seconds() / 3600.0

    @classmethod
    def cleanup_expired_sessions(cls, session) -> int:
        """
        Clean up expired sessions from database.

        Args:
            session: SQLAlchemy database session

        Returns:
            Number of sessions cleaned up
        """
        from sqlalchemy import and_

        # Find expired sessions
        expired_sessions = session.query(cls).filter(
            and_(
                cls.expires_at < datetime.utcnow(),
                cls.is_active == True  # Only clean up active sessions
            )
        )

        count = expired_sessions.count()

        # Deactivate expired sessions (don't delete for audit purposes)
        expired_sessions.update({
            "is_active": False,
            "updated_at": datetime.utcnow()
        })

        session.commit()
        return count