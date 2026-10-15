"""
Cookie store of the myMoment adapter.

Persists the serialized cookie jar of a platform account as an encrypted
MyMomentSession row: load and save per account, plus discard when myMoment
rejects the credentials.
"""

import uuid
from typing import Awaitable, Callable, Optional, Dict, Any

from sqlalchemy import Select, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.mymoment_session import MyMomentSession
from src.config.database import get_database_manager
from src.utils.datetimes import utcnow


async def _new_db_session() -> AsyncSession:
    sessionmaker = await get_database_manager().create_sessionmaker()
    return sessionmaker()


def _active_sessions_of(account_id: uuid.UUID) -> Select:
    return select(MyMomentSession).where(
        and_(
            MyMomentSession.mymoment_login_id == account_id,
            MyMomentSession.is_active == True,
        )
    )


async def _usable_session(
    db_session: AsyncSession, account_id: uuid.UUID
) -> Optional[MyMomentSession]:
    stmt = (
        _active_sessions_of(account_id)
        .where(MyMomentSession.expires_at > utcnow())
        .order_by(MyMomentSession.created_at.desc())
        .limit(1)
    )
    result = await db_session.execute(stmt)
    record = result.scalar_one_or_none()
    if record is None or not record.is_usable():
        return None
    return record


async def _deactivate_sessions(db_session: AsyncSession, account_id: uuid.UUID) -> None:
    result = await db_session.execute(_active_sessions_of(account_id))
    for record in result.scalars().all():
        record.deactivate()


class MyMomentSessionCookieStore:
    """
    Cookie store of the myMoment adapter, backed by encrypted MyMomentSession rows.

    Each call opens its own short-lived DB session, so no DB connection is
    held while the adapter talks HTTP.
    """

    def __init__(
        self, new_db_session: Callable[[], Awaitable[AsyncSession]] = _new_db_session
    ):
        self._new_db_session = new_db_session

    async def load(self, account_id: uuid.UUID) -> Optional[Dict[str, Any]]:
        """Return the stored cookie data of the account's usable session, or None."""
        db_session = await self._new_db_session()
        async with db_session:
            record = await _usable_session(db_session, account_id)
            if record is None:
                return None
            return record.get_session_data(as_dict=True)

    async def save(self, account_id: uuid.UUID, data: Dict[str, Any]) -> None:
        """Store cookie data and renew the account's session (replace it if unusable)."""
        db_session = await self._new_db_session()
        async with db_session:
            record = await _usable_session(db_session, account_id)
            if record is None:
                await _deactivate_sessions(db_session, account_id)
                db_session.add(
                    MyMomentSession.create_new_session(
                        mymoment_login_id=account_id, session_data=data
                    )
                )
            else:
                record.update_session_data(data)
                record.renew_session()
            await db_session.commit()

    async def discard(self, account_id: uuid.UUID) -> None:
        """Deactivate the account's stored sessions so their cookies are not reused."""
        db_session = await self._new_db_session()
        async with db_session:
            await _deactivate_sessions(db_session, account_id)
            await db_session.commit()
