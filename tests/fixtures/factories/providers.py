"""Factories for encrypted LLM provider records."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.llm_provider import LLMProviderConfiguration

from tests.fixtures.factories._shared import next_sequence, require_owner


async def create_llm_provider(
    session: AsyncSession,
    *,
    user: Any = None,
    user_id: Any = None,
    api_key: str | None = None,
    **overrides: Any,
) -> LLMProviderConfiguration:
    """Persist a valid `LLMProviderConfiguration` using `set_api_key()`."""
    owner = require_owner(user=user, user_id=user_id)
    index = next_sequence("llm_provider")

    provider = LLMProviderConfiguration(
        user=owner["user"],
        user_id=owner["user_id"],
        provider_name=overrides.pop("provider_name", "openai"),
        model_name=overrides.pop("model_name", "gpt-4o-mini"),
        max_tokens=overrides.pop("max_tokens", 512),
        temperature=overrides.pop("temperature", 0.2),
        is_active=overrides.pop("is_active", True),
        last_used=overrides.pop("last_used", None),
        **overrides,
    )
    provider.set_api_key(api_key or f"sk-test-{index:04d}")

    session.add(provider)
    await session.flush()
    return provider
