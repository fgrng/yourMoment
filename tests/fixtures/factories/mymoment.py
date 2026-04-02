"""Factories for encrypted myMoment records."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.mymoment_login import MyMomentLogin
from src.models.mymoment_session import MyMomentSession

from tests.fixtures.factories._shared import ensure_same_user, next_sequence, require_owner


async def create_mymoment_login(
    session: AsyncSession,
    *,
    user: Any = None,
    user_id: Any = None,
    username: str | None = None,
    password: str | None = None,
    **overrides: Any,
) -> MyMomentLogin:
    """Persist a valid `MyMomentLogin` using `set_credentials()`."""
    owner = require_owner(user=user, user_id=user_id)
    index = next_sequence("mymoment_login")

    login = MyMomentLogin(
        user=owner["user"],
        user_id=owner["user_id"],
        name=overrides.pop("name", f"Login {index}"),
        is_active=overrides.pop("is_active", True),
        is_admin=overrides.pop("is_admin", False),
        last_used=overrides.pop("last_used", None),
        **overrides,
    )
    login.set_credentials(
        username or f"student{index}",
        password or f"Password-{index}!",
    )

    session.add(login)
    await session.flush()
    return login


async def create_mymoment_session(
    session: AsyncSession,
    *,
    mymoment_login: MyMomentLogin | None = None,
    mymoment_login_id: Any = None,
    session_data: dict[str, Any] | str | None = None,
    expires_at: datetime | None = None,
    duration_hours: int = 24,
    **overrides: Any,
) -> MyMomentSession:
    """Persist a valid `MyMomentSession` with encrypted session data."""
    if mymoment_login is None and mymoment_login_id is None:
        raise ValueError("mymoment_session fixtures require mymoment_login or mymoment_login_id")
    if mymoment_login is not None and mymoment_login_id is not None and mymoment_login.id != mymoment_login_id:
        raise ValueError("mymoment_login and mymoment_login_id refer to different logins")

    login_id = mymoment_login.id if mymoment_login is not None else mymoment_login_id
    index = next_sequence("mymoment_session")
    session_record = MyMomentSession.create_new_session(
        mymoment_login_id=login_id,
        session_data=session_data or {"cookie": f"session-{index}"},
        duration_hours=duration_hours,
    )
    if mymoment_login is not None:
        session_record.mymoment_login = mymoment_login

    if expires_at is not None:
        session_record.expires_at = expires_at

    for field, value in overrides.items():
        setattr(session_record, field, value)

    session.add(session_record)
    await session.flush()
    return session_record


async def create_expired_mymoment_session(
    session: AsyncSession,
    *,
    mymoment_login: MyMomentLogin | None = None,
    mymoment_login_id: Any = None,
    **overrides: Any,
) -> MyMomentSession:
    """Persist an already expired `MyMomentSession`."""
    return await create_mymoment_session(
        session,
        mymoment_login=mymoment_login,
        mymoment_login_id=mymoment_login_id,
        expires_at=overrides.pop("expires_at", datetime.utcnow() - timedelta(hours=1)),
        **overrides,
    )
