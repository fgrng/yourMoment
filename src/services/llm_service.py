"""
LLM Provider service for yourMoment application.

Implements secure LLM provider configuration management with encrypted API key storage
according to FR-002 (encrypted API key storage) and multi-provider support requirements.
"""

import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any

import instructor
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select, and_, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from src.models.llm_provider import LLMProviderConfiguration
from src.config.encryption import EncryptionError, DecryptionError
import logging

logger = logging.getLogger(__name__)


class LLMProviderError(Exception):
    """Base exception for LLM provider operations."""
    pass


class LLMProviderNotFoundError(LLMProviderError):
    """Raised when LLM provider configuration is not found."""
    pass


class LLMProviderValidationError(LLMProviderError):
    """Raised when LLM provider configuration validation fails."""
    pass


class PydanticComment(BaseModel):
    content: str = Field(description="AI-generated comment on myMoment article")

class LLMProviderService:
    """
    Service for managing LLM provider configurations.

    Implements:
    - Encrypted API key storage (FR-002)
    - Multi-provider support (OpenAI, Mistral)
    - Unified instructor-based generation with JSON mode for token efficiency
    - User data isolation (each user manages their own providers)
    - Configuration validation and management

    Note: HuggingFace support temporarily removed - will be re-added via LiteLLM integration
    """

    # Supported LLM providers
    # Note: HuggingFace temporarily removed - will be re-added via LiteLLM integration
    SUPPORTED_PROVIDERS = {
        "openai": {
            "default_models": ["gpt-5-nano", "gpt-5", "gpt-4.1"],
            "api_key_prefix": "sk-"
        },
        "mistral": {
            "default_models": ["mistral-small-latest", "magistral-small-latest", "magistral-medium-latest", "mistral-medium-latest"],
            "api_key_prefix": ""
        }
    }

    def __init__(self, db_session: AsyncSession):
        """
        Initialize LLM provider service.

        Args:
            db_session: Database session for operations
        """
        self.db_session = db_session

    async def create_provider_configuration(
        self,
        user_id: uuid.UUID,
        provider_name: str,
        api_key: str,
        model_name: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None
    ) -> LLMProviderConfiguration:
        """
        Create new LLM provider configuration for user.

        Args:
            user_id: ID of the user creating the configuration
            provider_name: Name of the LLM provider (openai, mistral)
            api_key: API key for the provider (will be encrypted)
            model_name: Specific model to use
            max_tokens: Maximum tokens for responses (optional)
            temperature: Temperature for generation (0.0-1.0, optional)

        Returns:
            Created LLMProviderConfiguration instance

        Raises:
            LLMProviderValidationError: If validation fails
            LLMProviderError: If creation fails
        """
        try:
            # Validate provider name
            if provider_name not in self.SUPPORTED_PROVIDERS:
                raise LLMProviderValidationError(
                    f"Unsupported provider: {provider_name}. "
                    f"Supported providers: {list(self.SUPPORTED_PROVIDERS.keys())}"
                )

            # Validate API key format if provider has prefix requirement
            provider_info = self.SUPPORTED_PROVIDERS[provider_name]
            if provider_info["api_key_prefix"] and not api_key.startswith(provider_info["api_key_prefix"]):
                logger.warning(f"API key format may be invalid for {provider_name}")

            # Validate temperature range
            if temperature is not None and not (0.0 <= temperature <= 1.0):
                raise LLMProviderValidationError("Temperature must be between 0.0 and 1.0")

            # Create new provider configuration
            provider_config = LLMProviderConfiguration(
                user_id=user_id,
                provider_name=provider_name,
                model_name=model_name,
                max_tokens=max_tokens,
                temperature=temperature,
                is_active=True
            )

            # Set encrypted API key (this handles encryption automatically)
            provider_config.set_api_key(api_key)

            # Save to database
            self.db_session.add(provider_config)
            await self.db_session.commit()
            await self.db_session.refresh(provider_config)

            logger.info(f"Created LLM provider configuration for user {user_id}: {provider_name}/{model_name}")
            return provider_config

        except EncryptionError as e:
            logger.error(f"Failed to encrypt API key for provider {provider_name}: {e}")
            raise LLMProviderError(f"Failed to secure API key: {e}")
        except IntegrityError as e:
            logger.error(f"Database integrity error creating provider config: {e}")
            await self.db_session.rollback()
            raise LLMProviderError("Failed to create provider configuration")
        except Exception as e:
            logger.error(f"Unexpected error creating provider config: {e}")
            await self.db_session.rollback()
            raise LLMProviderError(f"Failed to create provider configuration: {e}")

    async def get_user_providers(self, user_id: uuid.UUID) -> List[LLMProviderConfiguration]:
        """
        Get all LLM provider configurations for a user.

        Args:
            user_id: ID of the user

        Returns:
            List of user's LLM provider configurations
        """
        try:
            stmt = select(LLMProviderConfiguration).where(
                LLMProviderConfiguration.user_id == user_id
            ).order_by(LLMProviderConfiguration.created_at.desc())

            result = await self.db_session.execute(stmt)
            providers = result.scalars().all()

            logger.debug(f"Retrieved {len(providers)} provider configurations for user {user_id}")
            return list(providers)

        except Exception as e:
            logger.error(f"Failed to retrieve provider configurations for user {user_id}: {e}")
            raise LLMProviderError(f"Failed to retrieve provider configurations: {e}")

    async def get_provider_by_id(self, provider_id: uuid.UUID, user_id: uuid.UUID) -> LLMProviderConfiguration:
        """
        Get specific LLM provider configuration by ID (with user ownership check).

        Args:
            provider_id: ID of the provider configuration
            user_id: ID of the requesting user (for ownership validation)

        Returns:
            LLMProviderConfiguration instance

        Raises:
            LLMProviderNotFoundError: If provider not found or user doesn't own it
        """
        try:
            stmt = select(LLMProviderConfiguration).where(
                and_(
                    LLMProviderConfiguration.id == provider_id,
                    LLMProviderConfiguration.user_id == user_id
                )
            )

            result = await self.db_session.execute(stmt)
            provider = result.scalar_one_or_none()

            if not provider:
                raise LLMProviderNotFoundError(f"Provider configuration {provider_id} not found for user {user_id}")

            return provider

        except Exception as e:
            if isinstance(e, LLMProviderNotFoundError):
                raise
            logger.error(f"Failed to retrieve provider {provider_id} for user {user_id}: {e}")
            raise LLMProviderError(f"Failed to retrieve provider configuration: {e}")

    async def update_provider_configuration(
        self,
        provider_id: uuid.UUID,
        user_id: uuid.UUID,
        **updates
    ) -> LLMProviderConfiguration:
        """
        Update LLM provider configuration.

        Args:
            provider_id: ID of the provider configuration
            user_id: ID of the user (for ownership validation)
            **updates: Fields to update (api_key, model_name, max_tokens, temperature)

        Returns:
            Updated LLMProviderConfiguration instance

        Raises:
            LLMProviderNotFoundError: If provider not found
            LLMProviderValidationError: If validation fails
        """
        # Get existing provider (validates ownership)
        provider = await self.get_provider_by_id(provider_id, user_id)

        try:
            # Validate updates
            if "temperature" in updates:
                temp = updates["temperature"]
                if temp is not None and not (0.0 <= temp <= 1.0):
                    raise LLMProviderValidationError("Temperature must be between 0.0 and 1.0")

            # Handle special fields
            if "api_key" in updates:
                provider.set_api_key(updates.pop("api_key"))

            # Update other fields
            updatable_fields = ["model_name", "max_tokens", "temperature"]
            for field, value in updates.items():
                if field in updatable_fields:
                    setattr(provider, field, value)

            provider.updated_at = datetime.utcnow()

            await self.db_session.commit()
            await self.db_session.refresh(provider)

            logger.info(f"Updated provider configuration {provider_id} for user {user_id}")
            return provider

        except EncryptionError as e:
            logger.error(f"Failed to encrypt updated API key: {e}")
            await self.db_session.rollback()
            raise LLMProviderError(f"Failed to secure API key: {e}")
        except Exception as e:
            logger.error(f"Failed to update provider {provider_id}: {e}")
            await self.db_session.rollback()
            raise LLMProviderError(f"Failed to update provider configuration: {e}")

    async def delete_provider_configuration(self, provider_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        """
        Delete LLM provider configuration.

        Args:
            provider_id: ID of the provider configuration
            user_id: ID of the user (for ownership validation)

        Returns:
            True if deleted successfully

        Raises:
            LLMProviderNotFoundError: If provider not found
        """
        try:
            # Check if provider exists and user owns it
            await self.get_provider_by_id(provider_id, user_id)

            # Delete the provider configuration
            stmt = delete(LLMProviderConfiguration).where(
                and_(
                    LLMProviderConfiguration.id == provider_id,
                    LLMProviderConfiguration.user_id == user_id
                )
            )

            result = await self.db_session.execute(stmt)
            await self.db_session.commit()

            if result.rowcount == 0:
                raise LLMProviderNotFoundError(f"Provider configuration {provider_id} not found for user {user_id}")

            logger.info(f"Deleted provider configuration {provider_id} for user {user_id}")
            return True

        except Exception as e:
            if isinstance(e, LLMProviderNotFoundError):
                raise
            logger.error(f"Failed to delete provider {provider_id}: {e}")
            await self.db_session.rollback()
            raise LLMProviderError(f"Failed to delete provider configuration: {e}")

    async def get_provider_for_generation(
        self,
        provider_id: uuid.UUID,
        user_id: uuid.UUID
    ) -> Dict[str, Any]:
        """
        Get provider configuration prepared for LLM generation.

        Args:
            provider_id: ID of the provider configuration
            user_id: ID of the user

        Returns:
            Dictionary with generation configuration including decrypted API key

        Raises:
            LLMProviderNotFoundError: If provider not found or inactive
        """
        provider = await self.get_provider_by_id(provider_id, user_id)

        if not provider.is_active:
            raise LLMProviderNotFoundError(f"Provider configuration {provider_id} is inactive")

        try:
            # Mark provider as used
            provider.mark_as_used()
            await self.db_session.commit()

            # Get generation configuration (includes decrypted API key)
            return provider.get_generation_config()

        except DecryptionError as e:
            logger.error(f"Failed to decrypt API key for provider {provider_id}: {e}")
            raise LLMProviderError(f"Failed to access provider credentials: {e}")
        except Exception as e:
            logger.error(f"Failed to prepare provider {provider_id} for generation: {e}")
            raise LLMProviderError(f"Failed to prepare provider for generation: {e}")

    def get_supported_providers(self) -> Dict[str, Any]:
        """
        Get information about supported LLM providers.

        Returns:
            Dictionary with provider information
        """
        return self.SUPPORTED_PROVIDERS.copy()

    async def get_active_providers(self, user_id: uuid.UUID) -> List[LLMProviderConfiguration]:
        """
        Get active LLM provider configurations for a user.

        Args:
            user_id: ID of the user

        Returns:
            List of active provider configurations
        """
        try:
            stmt = select(LLMProviderConfiguration).where(
                and_(
                    LLMProviderConfiguration.user_id == user_id,
                    LLMProviderConfiguration.is_active == True
                )
            ).order_by(LLMProviderConfiguration.created_at.desc())

            result = await self.db_session.execute(stmt)
            providers = result.scalars().all()

            logger.debug(f"Retrieved {len(providers)} active provider configurations for user {user_id}")
            return list(providers)

        except Exception as e:
            logger.error(f"Failed to retrieve active providers for user {user_id}: {e}")
            raise LLMProviderError(f"Failed to retrieve active providers: {e}")

    async def _get_instructor_client(
        self,
        provider_name: str,
        api_key: str
    ) -> instructor.Instructor:
        """
        Initialize instructor client for specified provider.

        Args:
            provider_name: Name of LLM provider (openai, mistral)
            api_key: Decrypted API key

        Returns:
            Instructor-wrapped client

        Raises:
            LLMProviderError: If client initialization fails
        """
        try:
            if provider_name == "openai":
                try:
                    from openai import AsyncOpenAI
                except ImportError as exc:
                    raise LLMProviderError(
                        "openai package is required for OpenAI support"
                    ) from exc

                base_client = AsyncOpenAI(api_key=api_key)
                return instructor.from_openai(
                    base_client,
                    mode=instructor.Mode.JSON
                )

            elif provider_name == "mistral":
                try:
                    from mistralai import Mistral
                except ImportError as exc:
                    raise LLMProviderError(
                        "mistralai package is required for Mistral support"
                    ) from exc

                base_client = Mistral(api_key=api_key)
                return instructor.from_mistral(
                    base_client,
                    mode=instructor.Mode.MISTRAL_STRUCTURED_OUTPUTS,
                    use_async=True
                )

            else:
                raise LLMProviderError(f"Unsupported provider: {provider_name}")

        except Exception as e:
            logger.error(f"Failed to initialize instructor client for {provider_name}: {e}")
            raise LLMProviderError(f"Client initialization failed: {e}")

    async def _generate_with_instructor(
        self,
        client: instructor.Instructor,
        user_prompt: str,
        model: str,
        max_tokens: int,
        temperature: float,
        system_prompt: Optional[str] = None
    ) -> str:
        """
        Generate completion using instructor client with structured output.

        Uses JSON mode with PydanticComment for minimal token overhead while
        maintaining structured validation.

        Args:
            client: Instructor-wrapped client
            user_prompt: User prompt text
            model: Model name
            max_tokens: Maximum tokens
            temperature: Temperature setting
            system_prompt: Optional system prompt to guide the model

        Returns:
            Generated text string

        Raises:
            LLMProviderError: If generation fails
        """
        try:
            # Build messages list
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": user_prompt})

            # Use instructor with JSON mode for structured output
            params = {
                "model": model,
                "messages": messages,
                "response_model": PydanticComment,
            }

            if max_tokens is not None:
                params["max_tokens"] = max_tokens

            if temperature is not None:
                params["temperature"] = temperature

            response = await client.chat.completions.create(**params)

            # Extract content from structured response
            return response.content.strip()

        except Exception as e:
            logger.error(f"Instructor generation failed: {e}")
            raise LLMProviderError(f"Generation failed: {e}")

    async def generate_completion(
        self,
        user_prompt: str,
        provider_config: LLMProviderConfiguration,
        system_prompt: Optional[str] = None
    ) -> str:
        """
        Generate LLM completion using specified provider configuration.

        Uses instructor library with JSON mode for structured output and minimal token overhead.

        Args:
            user_prompt: The prompt text to send to the LLM
            provider_config: LLM provider configuration to use
            system_prompt: Optional system prompt to guide the model

        Returns:
            Generated text completion from LLM

        Raises:
            LLMProviderError: If generation fails
        """
        try:
            # Use config values or overrides
            final_max_tokens = provider_config.max_tokens
            final_temperature = provider_config.temperature

            # Get decrypted API key
            decrypted_key = provider_config.get_api_key()

            # Initialize instructor client
            client = await self._get_instructor_client(
                provider_config.provider_name,
                decrypted_key
            )

            # Generate using unified instructor method
            return await self._generate_with_instructor(
                client,
                user_prompt,
                provider_config.model_name,
                final_max_tokens,
                final_temperature,
                system_prompt
            )

        except Exception as e:
            logger.error(f"LLM generation failed with {provider_config.provider_name}: {e}")
            raise LLMProviderError(f"Generation failed: {e}")


