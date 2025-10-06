"""
LLMProviderConfiguration model for yourMoment application.

Manages user-specific LLM provider settings and encrypted API credentials.
Implements FR-002 (encrypted API key storage) and multi-provider support.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional, Dict, Any

from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from src.models.base import Base
from src.config.encryption import encrypt_api_key, decrypt_api_key

# Avoid circular imports
if TYPE_CHECKING:
    from src.models.user import User


class LLMProviderConfiguration(Base):
    """
    LLMProviderConfiguration model for user-specific LLM provider settings.

    Implements:
    - FR-002: Encrypted API key storage using Fernet
    - Multi-provider support (OpenAI, Mistral, HuggingFace)
    - Provider-specific configuration parameters
    - User data isolation
    """

    __tablename__ = "llm_provider_configurations"

    # Primary key
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique provider configuration identifier"
    )

    # Foreign key to User
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Owner of this LLM provider configuration"
    )

    # Provider identification
    provider_name = Column(
        String(50),
        nullable=False,
        doc="LLM provider name (openai, mistral, huggingface)"
    )

    # Encrypted API credentials
    api_key_encrypted = Column(
        String(500),  # Encrypted data is longer than plaintext
        nullable=False,
        doc="Encrypted API key (FR-002)"
    )

    # Model configuration
    model_name = Column(
        String(100),
        nullable=False,
        doc="Specific model to use (e.g., gpt-4o, mistral-large-latest)"
    )

    max_tokens = Column(
        Integer,
        nullable=True,
        doc="Maximum tokens for responses (provider-specific default if null)"
    )

    temperature = Column(
        Float,
        nullable=True,
        doc="Temperature for response generation (0.0-1.0, provider default if null)"
    )

    # Status fields
    is_active = Column(
        Boolean,
        default=True,
        nullable=False,
        doc="Whether this provider configuration is active"
    )

    # Timestamp fields
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="Configuration creation timestamp"
    )

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        doc="Last configuration update timestamp"
    )

    last_used = Column(
        DateTime(timezone=True),
        nullable=True,
        doc="Last time this provider was used for generation"
    )

    # Relationships
    user = relationship(
        "User",
        back_populates="llm_providers",
        doc="User who owns this provider configuration"
    )
    ai_comments = relationship("AIComment", back_populates="llm_provider")
    monitoring_processes = relationship("MonitoringProcess", back_populates="llm_provider")

    def __repr__(self) -> str:
        """String representation of LLMProviderConfiguration (safe - no API key)."""
        return (f"<LLMProviderConfiguration(id={self.id}, user_id={self.user_id}, "
                f"provider={self.provider_name}, model={self.model_name})>")

    def set_api_key(self, api_key: str) -> None:
        """
        Set and encrypt the API key.

        Args:
            api_key: Plaintext API key

        Note:
            API key is immediately encrypted using Fernet before storage.
            Plaintext API key is never stored in database.
        """
        self.api_key_encrypted = encrypt_api_key(api_key)
        self.updated_at = datetime.utcnow()

    def get_api_key(self) -> str:
        """
        Decrypt and return the API key.

        Returns:
            Decrypted API key in plaintext

        Raises:
            DecryptionError: If API key cannot be decrypted

        Note:
            Use this method only when making actual LLM API calls.
            API key should not be logged or cached in plaintext.
        """
        return decrypt_api_key(self.api_key_encrypted)

    def to_dict(self, include_api_key: bool = False) -> dict:
        """
        Convert provider configuration to dictionary representation.

        Args:
            include_api_key: Whether to include decrypted API key
                           Should be False for API responses (security)

        Returns:
            Dictionary representation of the provider configuration
        """
        config_dict = {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "provider_name": self.provider_name,
            "model_name": self.model_name,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "last_used": self.last_used.isoformat() if self.last_used else None,
        }

        # Only include decrypted API key if explicitly requested (internal use only)
        if include_api_key:
            try:
                config_dict["api_key"] = self.get_api_key()
            except Exception as e:
                config_dict["api_key"] = f"<decryption_error: {str(e)}>"

        return config_dict

    def get_generation_config(self) -> Dict[str, Any]:
        """
        Get configuration parameters for LLM generation.

        Returns:
            Dictionary of generation parameters

        Note:
            This includes the decrypted API key for actual LLM calls.
            Use only when making generation requests.
        """
        config = {
            "provider_name": self.provider_name,
            "model_name": self.model_name,
            "api_key": self.get_api_key(),
        }

        # Add optional parameters if specified
        if self.max_tokens is not None:
            config["max_tokens"] = self.max_tokens

        if self.temperature is not None:
            config["temperature"] = self.temperature

        return config

    def mark_as_used(self) -> None:
        """
        Update the last_used timestamp to current time.

        Should be called whenever this provider is used for generation.
        """
        self.last_used = datetime.utcnow()

    def update_configuration(self, **kwargs) -> None:
        """
        Update provider configuration parameters.

        Args:
            **kwargs: Configuration parameters to update
                     (model_name, max_tokens, temperature, etc.)
        """
        updatable_fields = ["model_name", "max_tokens", "temperature"]

        for field, value in kwargs.items():
            if field in updatable_fields and hasattr(self, field):
                setattr(self, field, value)

        self.updated_at = datetime.utcnow()

    def deactivate(self) -> None:
        """
        Deactivate this provider configuration.

        Deactivated providers won't be used for new generation requests.
        """
        self.is_active = False
        self.updated_at = datetime.utcnow()

    def activate(self) -> None:
        """
        Activate this provider configuration.
        """
        self.is_active = True
        self.updated_at = datetime.utcnow()

    def get_default_max_tokens(self) -> int:
        """
        Get default max tokens for this provider if not specified.
        """
        if self.max_tokens is not None:
            return self.max_tokens

        # Provider-specific defaults
        defaults = {
            "openai": 1500,
            "mistral": 2000,
            "huggingface": 1000,
        }

        return defaults.get(self.provider_name.lower(), 1000)

    def get_default_temperature(self) -> float:
        """
        Get default temperature for this provider if not specified.
        """
        return self.temperature if self.temperature is not None else 0.7
