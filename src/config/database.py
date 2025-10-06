"""Database engine and session management using unified settings."""

import os
from pathlib import Path
from typing import Optional

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
import logging

from src.config.settings import get_settings

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages SQLite database connections and lifecycle."""

    def __init__(self, *, database_url: Optional[str] = None, echo: Optional[bool] = None):
        """Initialize database manager, optionally overriding settings-derived values."""
        self._database_url_override = database_url
        self._echo_override = echo
        self._engine: Optional[AsyncEngine] = None
        self._sessionmaker: Optional[async_sessionmaker] = None

    def _resolve_config(self) -> tuple[str, bool]:
        """Resolve database URL and echo flag from settings with optional overrides."""
        if self._database_url_override is not None:
            database_url = self._database_url_override
        else:
            settings = get_settings()
            sqlite_file = Path(settings.database.DB_SQLITE_FILE)
            if not sqlite_file.is_absolute():
                sqlite_file = (Path(os.getcwd()) / sqlite_file).resolve()
            database_url = f"sqlite+aiosqlite:///{sqlite_file}"

        if self._echo_override is not None:
            echo = self._echo_override
        else:
            settings = get_settings()
            echo = settings.database.DB_ECHO

        return database_url, echo

    async def create_engine(self) -> AsyncEngine:
        """Create and configure the SQLite database engine."""
        if self._engine:
            return self._engine

        logger.info("Creating SQLite database engine")

        database_url, echo = self._resolve_config()

        try:
            self._engine = create_async_engine(
                database_url,
                echo=echo,
                # poolclass=StaticPool,
                connect_args={
                    "check_same_thread": False, # allow use outside creating thread
                    "timeout": 5.0, # busy timeout in seconds
                },
                pool_size=5,
                max_overflow=10
            )

            # Enable foreign key constraints for SQLite
            @event.listens_for(Engine, "connect")
            def set_sqlite_pragma(dbapi_connection, connection_record):
                """Enable foreign key constraints for SQLite."""
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA journal_mode=WAL;")    # concurrent reads during writes
                cursor.execute("PRAGMA synchronous=NORMAL;")  # faster, still safe for WAL
                cursor.execute("PRAGMA busy_timeout=5000;")   # 5s retry on lock
                cursor.close()

            logger.info("SQLite database engine created successfully")
            return self._engine

        except Exception as e:
            logger.error(f"Failed to create database engine: {e}")
            raise

    async def create_sessionmaker(self) -> async_sessionmaker:
        """Create async session factory."""
        if self._sessionmaker:
            return self._sessionmaker

        engine = await self.create_engine()

        self._sessionmaker = async_sessionmaker(
            engine,
            expire_on_commit=False
        )

        logger.info("Database sessionmaker created successfully")
        return self._sessionmaker

    async def close(self):
        """Close database connections and cleanup."""
        if self._engine:
            logger.info("Closing database engine")
            await self._engine.dispose()
            self._engine = None
            self._sessionmaker = None


# Global database manager instance
_database_manager: Optional[DatabaseManager] = None


def get_database_manager() -> DatabaseManager:
    """Get or create the global database manager instance."""
    global _database_manager

    if _database_manager is None:
        _database_manager = DatabaseManager()

    return _database_manager


async def get_engine() -> AsyncEngine:
    """Get the database engine."""
    manager = get_database_manager()
    return await manager.create_engine()


async def get_sessionmaker() -> async_sessionmaker:
    """Get the async session factory."""
    manager = get_database_manager()
    return await manager.create_sessionmaker()


async def get_session():
    """Get a new database session (context manager)."""
    sessionmaker = await get_sessionmaker()
    async with sessionmaker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def close_database():
    """Close database connections."""
    global _database_manager

    if _database_manager:
        await _database_manager.close()
        _database_manager = None


def create_test_database_manager(sqlite_file: str = ":memory:") -> DatabaseManager:
    """Create a database manager for testing."""
    return DatabaseManager(database_url=f"sqlite+aiosqlite:///{sqlite_file}", echo=True)
