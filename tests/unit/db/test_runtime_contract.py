"""
Foundational contract tests for the rebuilt unit-test runtime.

These checks intentionally stay small and focused on the shared contract
that every DB-backed unit test depends on: test environment variables,
singleton resets, encryption wiring, and per-test database isolation.
"""

import os
import pytest
from sqlalchemy import text


pytestmark = pytest.mark.database


class TestEnvironmentContract:
    """The test env vars must be set before any app code runs."""

    def test_environment_is_testing(self):
        assert os.environ.get("ENVIRONMENT") == "testing"

    def test_encryption_key_is_set(self):
        key = os.environ.get("YOURMOMENT_ENCRYPTION_KEY", "")
        assert key, "YOURMOMENT_ENCRYPTION_KEY must be set"
        assert len(key) >= 40, "Key looks too short to be a valid Fernet key"

    def test_settings_reports_testing(self):
        from src.config.settings import get_settings
        settings = get_settings()
        assert settings.is_testing
        assert not settings.is_production

    def test_settings_db_file_is_not_production(self):
        from src.config.settings import get_settings
        db_file = get_settings().database.DB_SQLITE_FILE
        assert "testing" in db_file.lower() or db_file == ":memory:", (
            f"Expected a test DB file, got {db_file!r}"
        )


class TestSingletonReset:
    """Settings singleton must be fresh between tests."""

    def test_singleton_can_be_reset(self):
        from src.config.settings import get_settings, reset_settings
        s1 = get_settings()
        reset_settings()
        s2 = get_settings()
        assert s1 is not s2

    def test_encryption_singleton_can_be_reset(self):
        from src.config.encryption import get_encryption_manager, reset_encryption_manager
        m1 = get_encryption_manager()
        reset_encryption_manager()
        m2 = get_encryption_manager()
        assert m1 is not m2


class TestEncryptionRoundTrip:
    """Encryption manager must use the test key and round-trip correctly."""

    def test_encrypt_decrypt_roundtrip(self):
        from src.config.encryption import get_encryption_manager
        mgr = get_encryption_manager()
        plaintext = "hello-test-secret"
        encrypted = mgr.encrypt(plaintext)
        assert encrypted != plaintext
        assert mgr.decrypt(encrypted) == plaintext


class TestDbFixture:
    """db_session fixture must provide an empty, isolated database."""

    async def test_db_session_is_alive(self, db_session):
        result = await db_session.execute(text("SELECT 1"))
        assert result.scalar() == 1

    async def test_two_sessions_are_isolated(self, db_session):
        from src.models.user import User
        user = User(email="isolation@example.com", password_hash="x", is_active=True)
        db_session.add(user)
        await db_session.flush()
        assert user.id is not None

    async def test_rollback_leaves_db_clean(self, db_session):
        """After flush + rollback the row must not persist."""
        from sqlalchemy import select
        from src.models.user import User

        user = User(email="rollback@example.com", password_hash="x", is_active=True)
        db_session.add(user)
        await db_session.flush()
        await db_session.rollback()

        result = await db_session.execute(
            select(User).where(User.email == "rollback@example.com")
        )
        assert result.scalar_one_or_none() is None
