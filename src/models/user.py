"""
User model for yourMoment application.

Represents registered users with authentication fields as specified in data-model.md.
Implements FR-001 (email/password authentication) and security requirements.
"""

import uuid
from datetime import datetime
from typing import List, TYPE_CHECKING

from sqlalchemy import Column, String, Boolean, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from src.models.base import Base

# Avoid circular imports
if TYPE_CHECKING:
    from src.models.llm_provider import LLMProviderConfiguration
    from src.models.monitoring_process import MonitoringProcess
    from src.models.mymoment_login import MyMomentLogin
    from src.models.user_session import UserSession
    from src.models.prompt_template import PromptTemplate
    from src.models.tracked_student import TrackedStudent
    from src.models.article_version import ArticleVersion


class User(Base):
    """
    User model for yourMoment application authentication and profile management.

    Implements:
    - FR-001: Email/password authentication
    - FR-017: Secure password storage (hashed, not plaintext)
    - Email uniqueness constraint
    - User activation and verification status
    - Timestamp tracking for audit purposes
    """

    __tablename__ = "users"

    # Primary key
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique user identifier"
    )

    # Authentication fields
    email = Column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
        doc="User email address - unique across system"
    )

    password_hash = Column(
        String(255),
        nullable=False,
        doc="Bcrypt hashed password - never store plaintext (FR-017)"
    )

    # User status fields
    is_active = Column(
        Boolean,
        default=True,
        nullable=False,
        doc="Whether user account is active"
    )

    is_verified = Column(
        Boolean,
        default=False,
        nullable=False,
        doc="Whether user email has been verified"
    )

    # Timestamp fields for audit and tracking
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="Account creation timestamp"
    )

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        doc="Last account update timestamp"
    )

    # Relationships to other entities
    llm_providers = relationship(
        "LLMProviderConfiguration",
        back_populates="user",
        cascade="all, delete-orphan",
        doc="User's LLM provider configurations"
    )

    monitoring_processes = relationship(
        "MonitoringProcess",
        back_populates="user",
        cascade="all, delete-orphan",
        doc="User's monitoring processes"
    )

    mymoment_logins = relationship(
        "MyMomentLogin",
        back_populates="user",
        cascade="all, delete-orphan",
        doc="User's myMoment platform login credentials"
    )

    user_sessions = relationship(
        "UserSession",
        back_populates="user",
        cascade="all, delete-orphan",
        doc="User's application sessions"
    )

    prompt_templates = relationship(
        "PromptTemplate",
        back_populates="user",
        cascade="all, delete-orphan",
        doc="User's custom prompt templates"
    )

    ai_comments = relationship(
        "AIComment",
        back_populates="user",
        cascade="all, delete-orphan",
        doc="User's AI-generated comments with article snapshots"
    )

    # Student Backup feature relationships
    tracked_students = relationship(
        "TrackedStudent",
        back_populates="user",
        cascade="all, delete-orphan",
        doc="User's tracked students for backup"
    )

    article_versions = relationship(
        "ArticleVersion",
        back_populates="user",
        cascade="all, delete-orphan",
        doc="User's backed up article versions"
    )

    def __repr__(self) -> str:
        """String representation of User (safe - no sensitive data)."""
        return f"<User(id={self.id}, email={self.email}, is_active={self.is_active})>"

    def to_dict(self, include_sensitive: bool = False) -> dict:
        """
        Convert user to dictionary representation.

        Args:
            include_sensitive: Whether to include sensitive fields (password_hash)
                              Should be False for API responses

        Returns:
            Dictionary representation of user
        """
        user_dict = {
            "id": str(self.id),
            "email": self.email,
            "is_active": self.is_active,
            "is_verified": self.is_verified,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

        # Only include password_hash if explicitly requested (for internal use only)
        if include_sensitive:
            user_dict["password_hash"] = self.password_hash

        return user_dict

    @classmethod
    def validate_email(cls, email: str) -> bool:
        """
        Validate email format using Pydantic EmailStr.

        Args:
            email: Email address to validate

        Returns:
            True if email format is valid, False otherwise
        """
        from pydantic import BaseModel, EmailStr
        class EmailDummy(BaseModel):
            email: EmailStr

        try:
            EmailDummy(email = email)
            return True
        except ValueError:
            return False

    def is_password_valid(self, password_hash: str) -> bool:
        """
        Check if provided password hash matches stored hash.

        Args:
            password_hash: Bcrypt hash to compare

        Returns:
            True if password matches, False otherwise

        Note:
            This method compares hashes, not plaintext passwords.
            Actual password verification should be done in the service layer.
        """
        return self.password_hash == password_hash

    def can_access_resource(self, resource_user_id: uuid.UUID) -> bool:
        """
        Check if this user can access a resource belonging to another user.

        Args:
            resource_user_id: User ID that owns the resource

        Returns:
            True if access is allowed, False otherwise

        Note:
            Basic implementation - only users can access their own resources.
            Can be extended for admin roles, shared resources, etc.
        """
        return self.id == resource_user_id

    def get_active_mymoment_logins_count(self) -> int:
        """
        Get count of active myMoment logins for this user.

        Returns:
            Number of active myMoment logins

        Note:
            This is a computed property that requires the relationship to be loaded.
        """
        if not self.mymoment_logins:
            return 0

        return sum(1 for login in self.mymoment_logins if login.is_active)

    def get_active_monitoring_processes_count(self) -> int:
        """
        Get count of active monitoring processes for this user.

        Returns:
            Number of active monitoring processes

        Note:
            This is a computed property that requires the relationship to be loaded.
        """
        if not self.monitoring_processes:
            return 0

        return sum(1 for process in self.monitoring_processes if process.is_active)

    def has_llm_provider_configured(self) -> bool:
        """
        Check if user has at least one active LLM provider configured.

        Returns:
            True if user has active LLM provider, False otherwise
        """
        if not self.llm_providers:
            return False

        return any(provider.is_active for provider in self.llm_providers)

    def deactivate(self) -> None:
        """
        Deactivate user account.

        This method sets is_active to False and updates the timestamp.
        It does not delete the user record for audit purposes.
        """
        self.is_active = False
        self.updated_at = datetime.utcnow()

    def activate(self) -> None:
        """
        Activate user account.

        This method sets is_active to True and updates the timestamp.
        """
        self.is_active = True
        self.updated_at = datetime.utcnow()

    def verify_email(self) -> None:
        """
        Mark user email as verified.

        This method sets is_verified to True and updates the timestamp.
        """
        self.is_verified = True
        self.updated_at = datetime.utcnow()
