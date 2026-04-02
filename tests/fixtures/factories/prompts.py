"""Factories for prompt template records."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.prompt_template import PromptTemplate

from tests.fixtures.factories._shared import next_sequence, require_owner


DEFAULT_SYSTEM_PROMPT = "You are a careful writing coach."
DEFAULT_USER_PROMPT_TEMPLATE = (
    "Read {article_title}. Use {article_content} and respond to {mymoment_username}."
)


async def create_prompt_template(
    session: AsyncSession,
    *,
    category: str = "USER",
    user: Any = None,
    user_id: Any = None,
    **overrides: Any,
) -> PromptTemplate:
    """Persist a valid `PromptTemplate`."""
    index = next_sequence("prompt_template")
    owner = None
    if category == "USER":
        owner = require_owner(user=user, user_id=user_id)
    elif user is not None or user_id is not None:
        raise ValueError("system prompt fixtures cannot be assigned to a user")

    prompt = PromptTemplate(
        name=overrides.pop("name", f"Prompt {index}"),
        description=overrides.pop("description", f"Prompt template {index}"),
        system_prompt=overrides.pop("system_prompt", DEFAULT_SYSTEM_PROMPT),
        user_prompt_template=overrides.pop("user_prompt_template", DEFAULT_USER_PROMPT_TEMPLATE),
        category=category,
        user=owner["user"] if owner else None,
        user_id=owner["user_id"] if owner else None,
        is_active=overrides.pop("is_active", True),
        **overrides,
    )

    session.add(prompt)
    await session.flush()
    return prompt


async def create_user_prompt_template(
    session: AsyncSession,
    *,
    user: Any = None,
    user_id: Any = None,
    **overrides: Any,
) -> PromptTemplate:
    """Persist a valid user-owned prompt template."""
    return await create_prompt_template(
        session,
        category="USER",
        user=user,
        user_id=user_id,
        **overrides,
    )


async def create_system_prompt_template(
    session: AsyncSession,
    **overrides: Any,
) -> PromptTemplate:
    """Persist a valid system prompt template."""
    return await create_prompt_template(
        session,
        category="SYSTEM",
        **overrides,
    )
