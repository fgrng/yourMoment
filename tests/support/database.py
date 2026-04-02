"""
Reusable async SQLite fixtures for DB-backed unit tests.

All fixtures are function-scoped (one ephemeral SQLite database file per test)
so that no state leaks between tests.

Fixtures are opt-in: a test only receives a session if it declares
``db_session`` (or ``db_engine``) in its signature.

Usage:
    async def test_something(db_session):
        user = User(email="a@b.com", ...)
        db_session.add(user)
        await db_session.flush()
        ...
"""

import os
import tempfile

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.config.database import create_test_database_manager


@pytest_asyncio.fixture(scope="function")
async def db_engine() -> AsyncEngine:
    """
    Ephemeral SQLite engine backed by a temporary file.

    Creates all tables before the test and drops them afterwards.
    Importing ``src.models`` ensures every model is registered on
    ``Base.metadata`` before ``create_all`` runs.
    """
    import src.models  # noqa: F401 – registers all models on Base.metadata
    from src.models.base import Base

    db_fd, db_path = tempfile.mkstemp(prefix="yourmoment-test-", suffix=".db")
    os.close(db_fd)

    manager = create_test_database_manager(db_path)
    engine = await manager.create_engine()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await manager.close()
    try:
        os.remove(db_path)
    except FileNotFoundError:
        pass


@pytest_asyncio.fixture(scope="function")
async def db_session(db_engine: AsyncEngine) -> AsyncSession:
    """
    Per-test async session.

    The session is rolled back after the test so that each test starts
    with an empty database.
    """
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()
