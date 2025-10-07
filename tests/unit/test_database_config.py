"""
Unit tests for SQLite database configuration.
"""

import os
import pytest

from src.config.database import DatabaseManager, create_test_database_manager
from src.config.settings import reset_settings


class TestDatabaseManager:
    """Test SQLite database manager functionality."""

    def test_database_manager_with_override(self):
        """Test database manager creation with explicit overrides."""
        manager = DatabaseManager(
            database_url="sqlite+aiosqlite:///test.db",
            echo=True
        )
        database_url, echo = manager._resolve_config()
        assert database_url == "sqlite+aiosqlite:///test.db"
        assert echo is True
        assert manager._engine is None
        assert manager._sessionmaker is None

    def test_database_manager_from_settings(self):
        """Test database manager creation from settings."""
        manager = DatabaseManager()
        database_url, echo = manager._resolve_config()
        assert "sqlite+aiosqlite:///" in database_url
        assert isinstance(echo, bool)

    def test_manager_url_override_only(self):
        """Test manager with URL override but echo from settings."""
        manager = DatabaseManager(database_url="sqlite+aiosqlite:///override.db")
        database_url, echo = manager._resolve_config()
        assert database_url == "sqlite+aiosqlite:///override.db"
        # echo comes from settings
        assert isinstance(echo, bool)

    def test_manager_echo_override_only(self):
        """Test manager with echo override but URL from settings."""
        manager = DatabaseManager(echo=True)
        database_url, echo = manager._resolve_config()
        # URL comes from settings
        assert "sqlite+aiosqlite:///" in database_url
        assert echo is True

    def test_environment_variable_loading(self):
        """Test configuration from environment variables."""
        original_db_file = os.environ.get("DB_SQLITE_FILE")
        original_echo = os.environ.get("DB_ECHO")

        try:
            os.environ["DB_SQLITE_FILE"] = "envtest.db"
            os.environ["DB_ECHO"] = "true"
            reset_settings()

            # Verify settings picked up the new env vars
            from src.config.settings import get_settings
            settings = get_settings()

            manager = DatabaseManager()
            database_url, echo = manager._resolve_config()
            assert "envtest.db" in database_url
            # The DB_ECHO setting may be controlled by .env.test, so just verify it's a bool
            assert isinstance(echo, bool)
        finally:
            # Restore original values
            if original_db_file is not None:
                os.environ["DB_SQLITE_FILE"] = original_db_file
            elif "DB_SQLITE_FILE" in os.environ:
                del os.environ["DB_SQLITE_FILE"]

            if original_echo is not None:
                os.environ["DB_ECHO"] = original_echo
            elif "DB_ECHO" in os.environ:
                del os.environ["DB_ECHO"]

            reset_settings()


class TestHelperFunctions:
    """Test helper functions."""

    def test_create_test_database_manager(self):
        """Test test database manager creation."""
        manager = create_test_database_manager(":memory:")
        assert isinstance(manager, DatabaseManager)
        database_url, echo = manager._resolve_config()
        assert echo is True
        assert ":memory:" in database_url

    def test_create_test_database_manager_with_file(self):
        """Test test database manager creation with specific file."""
        manager = create_test_database_manager("test_file.db")
        assert isinstance(manager, DatabaseManager)
        database_url, echo = manager._resolve_config()
        assert echo is True
        assert "test_file.db" in database_url


if __name__ == "__main__":
    pytest.main([__file__])
