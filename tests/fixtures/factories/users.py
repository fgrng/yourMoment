"""Factories for user-owned authentication records."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import User

from tests.fixtures.factories._shared import merge_kwargs, next_sequence


async def create_user(
    session: AsyncSession,
    **overrides: Any,
) -> User:
    """Persist a valid `User` with safe defaults."""
    index = next_sequence("user")
    user = User(
        **merge_kwargs(
            {
                "email": f"user{index}@example.test",
                "password_hash": f"hashed-password-{index}",
                "is_active": True,
                "is_verified": True,
            },
            overrides if isinstance(overrides, Mapping) else None,
        )
    )
    session.add(user)
    await session.flush()
    return user
