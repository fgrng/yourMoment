"""
Integration tests for SQLite database configuration.

Tests actual SQLite database connections and functionality.
"""

import os
import tempfile

import pytest
from sqlalchemy import text

from src.config.database import DatabaseManager, close_database, get_database_manager
from src.config.settings import get_settings, reset_settings


class TestDatabaseIntegration:
    """Integration tests for database functionality."""

    @pytest.fixture(autouse=True)
    async def cleanup_database(self):
        """Cleanup database connections after each test."""
        yield
        await close_database()

    @pytest.mark.asyncio
    async def test_sqlite_connection(self):
        """Test SQLite database connection."""
        # Create temporary SQLite file
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            sqlite_path = tmp.name

        try:
            manager = DatabaseManager(
                database_url=f"sqlite+aiosqlite:///{sqlite_path}",
                echo=False
            )

            # Test engine creation
            engine = await manager.create_engine()
            assert engine is not None

            # Test session creation
            sessionmaker = await manager.create_sessionmaker()
            assert sessionmaker is not None

            # Test actual session usage
            async with sessionmaker() as session:
                # Test a simple query
                result = await session.execute(text("SELECT 1 as test_value"))
                row = result.fetchone()
                assert row[0] == 1

        finally:
            # Cleanup
            await manager.close()
            if os.path.exists(sqlite_path):
                os.unlink(sqlite_path)

    @pytest.mark.asyncio
    async def test_database_manager_singleton(self):
        """Test that get_database_manager returns the same instance."""
        # Reset any existing manager
        await close_database()

        manager1 = get_database_manager()
        manager2 = get_database_manager()

        assert manager1 is manager2

    @pytest.mark.asyncio
    async def test_database_connection_lifecycle(self):
        """Test database connection creation and cleanup."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            sqlite_path = tmp.name

        try:
            manager = DatabaseManager(
                database_url=f"sqlite+aiosqlite:///{sqlite_path}"
            )

            # Initially no engine
            assert manager._engine is None
            assert manager._sessionmaker is None

            # Create engine
            engine = await manager.create_engine()
            assert manager._engine is not None
            assert engine is manager._engine

            # Create sessionmaker
            sessionmaker = await manager.create_sessionmaker()
            assert manager._sessionmaker is not None
            assert sessionmaker is manager._sessionmaker

            # Close connections
            await manager.close()
            assert manager._engine is None
            assert manager._sessionmaker is None

        finally:
            if os.path.exists(sqlite_path):
                os.unlink(sqlite_path)

    @pytest.mark.asyncio
    async def test_database_url_validation(self):
        """Test SQLite database URL configuration."""
        # Test valid SQLite URL with explicit override
        manager = DatabaseManager(database_url="sqlite+aiosqlite:///test.db")
        database_url, echo = manager._resolve_config()
        assert database_url == "sqlite+aiosqlite:///test.db"

        # Test URL built from environment variable DB_SQLITE_FILE
        original_db_file = os.environ.get("DB_SQLITE_FILE")
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            test_db_file = tmp.name

        try:
            os.environ["DB_SQLITE_FILE"] = test_db_file
            reset_settings()

            settings = get_settings()
            assert settings.database.DB_SQLITE_FILE == test_db_file

            manager = DatabaseManager()
            database_url, _ = manager._resolve_config()
            assert test_db_file in database_url
            assert database_url.startswith("sqlite+aiosqlite:///")
        finally:
            if original_db_file is not None:
                os.environ["DB_SQLITE_FILE"] = original_db_file
            elif "DB_SQLITE_FILE" in os.environ:
                del os.environ["DB_SQLITE_FILE"]
            reset_settings()

            if os.path.exists(test_db_file):
                os.unlink(test_db_file)

    @pytest.mark.asyncio
    async def test_connection_error_handling(self):
        """Test handling of connection errors."""
        # Test with completely invalid database URL
        manager = DatabaseManager(database_url="invalid://not-a-real-db")

        # Engine creation should fail with invalid URL scheme
        with pytest.raises(Exception):
            await manager.create_engine()

    @pytest.mark.asyncio
    async def test_engine_configuration_sqlite(self):
        """Test SQLite engine configuration."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            sqlite_path = tmp.name

        manager: DatabaseManager | None = None
        try:
            manager = DatabaseManager(database_url=f"sqlite+aiosqlite:///{sqlite_path}")

            # Create engine and verify it works
            engine = await manager.create_engine()
            assert engine is not None

            # Verify SQLite foreign key constraints are enabled
            async with engine.begin() as conn:
                result = await conn.execute(text("PRAGMA foreign_keys"))
                foreign_keys_enabled = result.fetchone()[0]
                assert foreign_keys_enabled == 1  # Foreign keys should be ON

        finally:
            if manager:
                await manager.close()
            if os.path.exists(sqlite_path):
                os.unlink(sqlite_path)


if __name__ == "__main__":
    pytest.main([__file__])
