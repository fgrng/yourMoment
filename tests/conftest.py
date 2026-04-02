"""
Root conftest: environment contract, singleton resets, and shared fixtures.

This file is loaded by pytest before any test module is imported, so
setting os.environ here guarantees that pydantic-settings and os.getenv()
calls inside the app read the correct test values on first access.
"""

import os

# ---------------------------------------------------------------------------
# Test environment contract — set before any app module is imported.
# Using setdefault so explicit CI overrides are respected.
# ---------------------------------------------------------------------------
os.environ["ENVIRONMENT"] = "testing"

# Valid Fernet key used across the test suite (from .env.test).
# Using a fixed key makes encrypted-field round trips deterministic.
os.environ.setdefault(
    "YOURMOMENT_ENCRYPTION_KEY",
    "bzD6gWQK3pWoaVuv5-YW_EdS-gtnznuaVD91nBZ2e1w=",
)
os.environ.setdefault("YOURMOMENT_KEY_FILE", ".encryption_key.test")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-not-for-production")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")

# Suppress all logging noise during tests.
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("LOG_CONSOLE_ENABLED", "false")
os.environ.setdefault("LOG_FILE_ENABLED", "false")

# ---------------------------------------------------------------------------
# Pull in DB fixtures so all test modules can declare db_engine / db_session
# without importing from tests.support directly.
# ---------------------------------------------------------------------------
pytest_plugins = ["tests.support.database"]

# ---------------------------------------------------------------------------
# Imports after env-var setup so app code reads the right values.
# ---------------------------------------------------------------------------
import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_singletons():
    """
    Reset cached Settings / EncryptionManager / DatabaseManager between
    every test so no stale state leaks from one test to the next.

    Pure tests benefit because a badly-configured Settings instance from a
    previous test can't corrupt a later one.  DB-backed tests already use
    per-test in-memory engines (db_engine fixture), so the global manager
    reset here is just an additional safety net.
    """
    from tests.support.runtime import reset_all_singletons

    reset_all_singletons()
    yield
    reset_all_singletons()
