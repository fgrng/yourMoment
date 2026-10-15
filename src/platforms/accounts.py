"""Builds the decrypted platform account that adapters receive."""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import get_settings
from src.models.mymoment_login import MyMomentLogin
from src.platforms.types import PlatformAccount


def platform_account_from_login(login: MyMomentLogin) -> PlatformAccount:
    """Decrypt a stored myMoment login into a PlatformAccount."""
    username, password = login.get_credentials()
    return PlatformAccount(
        id=login.id,
        base_url=get_settings().scraper.MYMOMENT_BASE_URL,
        username=username,
        password=password,
        role="admin" if login.is_admin else "user",
    )


async def load_platform_account(
    db_session: AsyncSession,
    login_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Optional[PlatformAccount]:
    """Return the user's active platform account, or None if there is none."""
    result = await db_session.execute(
        select(MyMomentLogin).where(
            and_(
                MyMomentLogin.id == login_id,
                MyMomentLogin.user_id == user_id,
                MyMomentLogin.is_active == True,
            )
        )
    )
    login = result.scalar_one_or_none()
    return platform_account_from_login(login) if login else None
