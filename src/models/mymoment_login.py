"""
MyMomentLogin model for yourMoment application.

Stores encrypted login credentials for myMoment platform per user.
Implements FR-017 (encrypted credential storage) and multi-login architecture.
"""

import uuid
from datetime import datetime
from typing import List, TYPE_CHECKING, Optional

from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from src.models.base import Base
from src.config.encryption import encrypt_mymoment_credentials, decrypt_mymoment_credentials

# Avoid circular imports
if TYPE_CHECKING:
    from src.models.user import User
    from src.models.mymoment_session import MyMomentSession
    from src.models.monitoring_process_login import MonitoringProcessLogin


class MyMomentLogin(Base):
    """
    MyMomentLogin model for storing encrypted myMoment platform credentials.

    Implements:
    - FR-017: Encrypted credential storage using Fernet
    - Multi-login architecture (multiple credentials per user)
    - Credential lifecycle management
    - Integration with monitoring processes
    """

    __tablename__ = "mymoment_logins"

    # Primary key
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique login credential identifier"
    )

    # Foreign key to User
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Owner of these credentials"
    )

    # Encrypted credential fields
    username_encrypted = Column(
        String(500),  # Encrypted data is longer than plaintext
        nullable=False,
        doc="Encrypted myMoment username (FR-017)"
    )

    password_encrypted = Column(
        String(500),  # Encrypted data is longer than plaintext
        nullable=False,
        doc="Encrypted myMoment password (FR-017)"
    )

    # User-friendly name for this login
    name = Column(
        String(100),
        nullable=False,
        doc="Friendly name for these credentials"
    )

    # Status fields
    is_active = Column(
        Boolean,
        default=True,
        nullable=False,
        doc="Whether this login is active and usable"
    )

    # Timestamp fields
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="Credential creation timestamp"
    )

    last_used = Column(
        DateTime(timezone=True),
        nullable=True,
        doc="Last time these credentials were used for login"
    )

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        doc="Last credential update timestamp"
    )

    # Relationships
    user = relationship(
        "User",
        back_populates="mymoment_logins",
        doc="User who owns these credentials"
    )

    sessions = relationship(
        "MyMomentSession",
        back_populates="mymoment_login",
        cascade="all, delete-orphan",
        doc="Active sessions using these credentials"
    )

    monitoring_process_logins = relationship(
        "MonitoringProcessLogin",
        back_populates="mymoment_login",
        cascade="all, delete-orphan",
        doc="Monitoring processes using these credentials"
    )

    # AI comments posted using this login
    ai_comments = relationship(
        "AIComment",
        back_populates="mymoment_login",
        doc="AI comments posted using this login"
    )

    def __repr__(self) -> str:
        """String representation of MyMomentLogin (safe - no credentials)."""
        return (f"<MyMomentLogin(id={self.id}, user_id={self.user_id}, "
                f"is_active={self.is_active})>")

    def set_credentials(self, username: str, password: str) -> None:
        """
        Set and encrypt the myMoment credentials.

        Args:
            username: Plaintext myMoment username
            password: Plaintext myMoment password

        Note:
            Credentials are immediately encrypted using Fernet before storage.
            Plaintext credentials are never stored.
        """
        encrypted_username, encrypted_password = encrypt_mymoment_credentials(
            username, password
        )
        self.username_encrypted = encrypted_username
        self.password_encrypted = encrypted_password
        self.updated_at = datetime.utcnow()

    def get_credentials(self) -> tuple[str, str]:
        """
        Decrypt and return the myMoment credentials.

        Returns:
            Tuple of (username, password) in plaintext

        Raises:
            DecryptionError: If credentials cannot be decrypted

        Note:
            Use this method only when actually needed for myMoment login.
            Credentials should not be logged or cached in plaintext.
        """
        return decrypt_mymoment_credentials(
            self.username_encrypted,
            self.password_encrypted
        )

    @property
    def username(self) -> str:
        """
        Get the username for API responses and display purposes.
        Returns:
            Decrypted username (safe to display in UI)
        """
        username, _ = self.get_credentials()
        return username

    def to_dict(self, include_credentials: bool = False) -> dict:
        """
        Convert login to dictionary representation.

        Args:
            include_credentials: Whether to include decrypted credentials
                               Should be False for API responses (security)

        Returns:
            Dictionary representation of the login
        """
        login_dict = {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "username": self.username,  # Safe to include username
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_used": self.last_used.isoformat() if self.last_used else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

        # Only include decrypted credentials if explicitly requested (internal use only)
        if include_credentials:
            username, password = self.get_credentials()
            login_dict["credentials"] = {
                "username": username,
                "password": password
            }

        return login_dict

    def mark_as_used(self) -> None:
        """
        Update the last_used timestamp to current time.

        Should be called whenever these credentials are used for login.
        """
        self.last_used = datetime.utcnow()

    def deactivate(self) -> None:
        """
        Deactivate this login.

        This method sets is_active to False and updates the timestamp.
        Deactivated logins won't be used for new sessions.
        """
        self.is_active = False
        self.updated_at = datetime.utcnow()

    def activate(self) -> None:
        """
        Activate this login.

        This method sets is_active to True and updates the timestamp.
        """
        self.is_active = True
        self.updated_at = datetime.utcnow()

    def has_active_sessions(self) -> bool:
        """
        Check if this login has any active myMoment sessions.
        """
        return any(session.is_active for session in self.sessions or [])

    def is_used_in_monitoring(self) -> bool:
        """
        Check if this login is used in any monitoring processes.
        """
        return len(self.monitoring_process_logins or []) > 0

    def can_be_deleted(self) -> bool:
        """
        Check if this login can be safely deleted.

        Returns:
            True if safe to delete, False if deletion would break dependencies

        Note:
            Logins with active sessions or monitoring processes cannot be deleted.
        """
        return not (self.has_active_sessions() or self.is_used_in_monitoring())