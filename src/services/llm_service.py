"""
LLM Provider service for yourMoment application.

Implements secure LLM provider configuration management with encrypted API key storage
according to FR-002 (encrypted API key storage) and multi-provider support requirements.
"""

import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any

import litellm
import litellm.exceptions
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
    reasoning: Optional[str] = Field(
        None,
        description=(
            "Internal reasoning for comment generation on the myMoment platform. "
            "Think step-by-step. This is not visible by the author. "
            "Write your reasoning here."
        )
    )
    content: str = Field(
        description=(
            "Generated comment for publishing on the myMoment platform. "
            "This is visible by the author of the article commented upon. "
            "Write your comment here."
        )
    )


# Provider-level metadata not available in litellm.model_cost
_PROVIDER_META: dict[str, dict] = {
    "openai": {"api_key_prefix": "sk-"},
    "mistral": {"api_key_prefix": ""},
}


class LLMProviderService:
    """
    Service for managing LLM provider configurations.

    Implements:
    - Encrypted API key storage (FR-002)
    - Multi-provider support (OpenAI, Mistral) via LiteLLM
    - Unified generation with LiteLLM native structured output
    - User data isolation (each user manages their own providers)
    - Configuration validation and management
    """

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
            provider_name: Name of the LLM provider (openai, mistral, huggingface)
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
            if provider_name not in _PROVIDER_META:
                raise LLMProviderValidationError(
                    f"Unsupported provider: {provider_name}. "
                    f"Supported providers: {list(_PROVIDER_META.keys())}"
                )

            # Validate API key format if provider has prefix requirement
            prefix = _PROVIDER_META[provider_name]["api_key_prefix"]
            if prefix and not api_key.startswith(prefix):
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
        Return model catalog for supported providers.

        Filters litellm.model_cost to OpenAI and Mistral models that support
        structured output (supports_response_schema=True). Each entry includes
        capability flags and provider metadata relevant to this project.

        Returns:
            Dict keyed by litellm model identifier (e.g. "openai/gpt-4o")
        """
        catalog: Dict[str, Any] = {}
        for model_key, info in litellm.model_cost.items():
            provider = info.get("litellm_provider", "")
            if provider not in _PROVIDER_META:
                continue
            if not info.get("supports_response_schema"):
                continue
            catalog[model_key] = {
                "provider": provider,
                "supports_response_schema": True,
                "supports_reasoning": bool(info.get("supports_reasoning", False)),
                "api_key_prefix": _PROVIDER_META[provider]["api_key_prefix"],
                "max_input_tokens": info.get("max_input_tokens"),
                "max_output_tokens": info.get("max_output_tokens"),
            }
        return dict(sorted(catalog.items()))

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

    async def _generate_with_instructor(
        self,
        user_prompt: str,
        provider_name: str,
        model: str,
        api_key: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        system_prompt: Optional[str] = None
    ) -> tuple[str, Optional[str]]:
        """
        Generate completion using LiteLLM with Pydantic structured output.

        Args:
            user_prompt: User prompt text
            provider_name: Provider name (to determine LiteLLM model prefix)
            model: Model name
            api_key: Decrypted API key
            max_tokens: Maximum tokens
            temperature: Temperature setting
            system_prompt: Optional system prompt to guide the model

        Returns:
            Tuple of (generated text, reasoning_content or None)

        Raises:
            LLMProviderError: If generation fails
        """
        try:
            # Determine LiteLLM model string (format: "provider/model")
            # Strip any accidental provider prefix the caller may have included
            bare_model = model.removeprefix(f"{provider_name}/")
            litellm_model = f"{provider_name}/{bare_model}"

            # Build messages list
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": user_prompt})

            params = {
                "model": litellm_model,
                "messages": messages,
                "response_model": PydanticComment,
                "api_key": api_key
            }

            is_reasoning_model = any(m in litellm_model.lower() for m in ["o1-", "o3-", "gpt-5", "magistral"])
            if not is_reasoning_model:
                if max_tokens is not None:
                    params["max_tokens"] = max_tokens
                if temperature is not None:
                    params["temperature"] = temperature
            else:
                if max_tokens is not None:
                    params["max_completion_tokens"] = max_tokens
                params["temperature"] = 1.0

            response = await litellm.acompletion(**params)
            parsed = PydanticComment.model_validate_json(response.choices[0].message.content)

            # Extract reasoning content if present
            # Priority 1: native reasoning tokens (o-series, Magistral)
            # Priority 2: CoT from structured output field (non-reasoning models)
            reasoning_content = None
            try:
                message = response.choices[0].message
                if hasattr(message, "reasoning_content") and message.reasoning_content:
                    reasoning_content = message.reasoning_content
                elif isinstance(message, dict) and message.get("reasoning_content"):
                    reasoning_content = message["reasoning_content"]
                elif parsed.reasoning:
                    reasoning_content = parsed.reasoning
            except Exception:
                pass

            return parsed.content.strip(), reasoning_content

        except litellm.exceptions.AuthenticationError as e:
            logger.error(f"LiteLLM authentication failed for {provider_name}/{model}: {e}")
            raise LLMProviderError(f"Invalid API key or authentication failed: {e}")
        except litellm.exceptions.RateLimitError as e:
            logger.warning(f"LiteLLM rate limit hit for {provider_name}/{model}: {e}")
            raise LLMProviderError(f"Rate limit exceeded — try again later: {e}")
        except litellm.exceptions.ContextWindowExceededError as e:
            logger.error(f"LiteLLM context window exceeded for {provider_name}/{model}: {e}")
            raise LLMProviderError(f"Prompt exceeds model context window: {e}")
        except litellm.exceptions.APIConnectionError as e:
            logger.error(f"LiteLLM connection error for {provider_name}/{model}: {e}")
            raise LLMProviderError(f"Could not reach LLM provider API: {e}")
        except litellm.exceptions.Timeout as e:
            logger.error(f"LiteLLM request timed out for {provider_name}/{model}: {e}")
            raise LLMProviderError(f"LLM request timed out: {e}")
        except litellm.exceptions.ServiceUnavailableError as e:
            logger.error(f"LiteLLM provider unavailable for {provider_name}/{model}: {e}")
            raise LLMProviderError(f"LLM provider temporarily unavailable: {e}")
        except (ValidationError, ValueError) as e:
            logger.error(f"Failed to parse structured output from {provider_name}/{model}: {e}")
            raise LLMProviderError(f"Model returned invalid structured output: {e}")
        except Exception as e:
            logger.error(f"LiteLLM generation failed for {provider_name}/{model}: {e}")
            raise LLMProviderError(f"Generation failed: {e}")

    async def generate_completion(
        self,
        user_prompt: str,
        provider_config: LLMProviderConfiguration,
        system_prompt: Optional[str] = None
    ) -> tuple[str, Optional[str]]:
        """
        Generate LLM completion using specified provider configuration.

        Args:
            user_prompt: The prompt text to send to the LLM
            provider_config: LLM provider configuration to use
            system_prompt: Optional system prompt to guide the model

        Returns:
            Tuple of (generated text, reasoning_content or None)

        Raises:
            LLMProviderError: If generation fails
        """
        try:
            decrypted_key = provider_config.get_api_key()

            return await self._generate_with_instructor(
                user_prompt=user_prompt,
                provider_name=provider_config.provider_name,
                model=provider_config.model_name,
                api_key=decrypted_key,
                max_tokens=provider_config.max_tokens,
                temperature=provider_config.temperature,
                system_prompt=system_prompt
            )

        except Exception as e:
            logger.error(f"LLM generation failed with {provider_config.provider_name}: {e}")
            raise LLMProviderError(f"Generation failed: {e}")


