"""DB-backed tests for the cookie store of the myMoment adapter."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.services.mymoment_session_service import MyMomentSessionCookieStore
from tests.fixtures.factories.users import create_user
from tests.fixtures.factories.mymoment import (
    create_mymoment_login,
    create_expired_mymoment_session,
)


def _cookie_store(db_engine):
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def new_session():
        return session_factory()

    return MyMomentSessionCookieStore(new_session)


async def test_cookie_store_loads_what_it_saved(db_session: AsyncSession, db_engine):
    user = await create_user(db_session)
    login = await create_mymoment_login(db_session, user=user)
    await db_session.commit()
    store = _cookie_store(db_engine)

    await store.save(login.id, {"cookies": [{"name": "sessionid", "value": "abc"}]})
    await store.save(login.id, {"cookies": [{"name": "sessionid", "value": "def"}]})

    assert await store.load(login.id) == {"cookies": [{"name": "sessionid", "value": "def"}]}


async def test_cookie_store_ignores_expired_sessions(db_session: AsyncSession, db_engine):
    user = await create_user(db_session)
    login = await create_mymoment_login(db_session, user=user)
    await create_expired_mymoment_session(db_session, mymoment_login=login)
    await db_session.commit()

    assert await _cookie_store(db_engine).load(login.id) is None


async def test_cookie_store_save_replaces_an_expired_session(db_session: AsyncSession, db_engine):
    user = await create_user(db_session)
    login = await create_mymoment_login(db_session, user=user)
    await create_expired_mymoment_session(db_session, mymoment_login=login)
    await db_session.commit()
    store = _cookie_store(db_engine)

    await store.save(login.id, {"cookies": [{"name": "sessionid", "value": "fresh"}]})

    assert await store.load(login.id) == {"cookies": [{"name": "sessionid", "value": "fresh"}]}


async def test_cookie_store_discard_drops_the_stored_session(db_session: AsyncSession, db_engine):
    user = await create_user(db_session)
    login = await create_mymoment_login(db_session, user=user)
    await db_session.commit()
    store = _cookie_store(db_engine)
    await store.save(login.id, {"cookies": [{"name": "sessionid", "value": "abc"}]})

    await store.discard(login.id)

    assert await store.load(login.id) is None

