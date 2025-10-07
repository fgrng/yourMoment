"""
Shared pytest configuration and fixtures for yourMoment tests.

This module provides test environment setup, fixtures, and utilities
used across unit, integration, contract, and performance tests.
"""

import os
import sys
from pathlib import Path
from typing import Generator

import pytest
from dotenv import load_dotenv

from src.config.settings import get_settings, reset_settings

# Add src directory to Python path for imports
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def pytest_configure(config):
    """
    Configure pytest environment before tests run.

    This function:
    1. Loads test-specific environment variables from .env.test (if exists)
    2. Falls back to .env file if .env.test doesn't exist
    3. Overrides specific variables for test isolation
    """
    # Determine which .env file to load
    env_test_file = PROJECT_ROOT / ".env.test"
    env_file = PROJECT_ROOT / ".env"

    if env_test_file.exists():
        load_dotenv(env_test_file, override=True)
        print(f"✓ Loaded test environment from {env_test_file}")
    elif env_file.exists():
        load_dotenv(env_file, override=True)
        print(f"✓ Loaded environment from {env_file}")
    else:
        print("⚠ Warning: No .env or .env.test file found")

    # Override critical settings for test isolation
    os.environ.setdefault("TESTING", "true")
    os.environ.setdefault("ENVIRONMENT", "testing")
    os.environ.setdefault("DB_SQLITE_FILE", "yourMoment_testing.db")
    os.environ.setdefault("LOG_LEVEL", "WARNING")
    os.environ.setdefault("LOG_CONSOLE_ENABLED", "false")
    os.environ.setdefault("YOURMOMENT_ENCRYPTION_KEY", "test-encryption-key-not-for-production")
    os.environ.setdefault("YOURMOMENT_KEY_FILE", ".encryption_key.test")
    os.environ.setdefault("JWT_SECRET", "test-jwt-secret")
    os.environ.setdefault("SECRET_KEY", "test-secret-key")

    # Disable external integrations during testing (unless explicitly enabled)
    if os.getenv("ENABLE_LIVE_SCRAPER_TESTS") != "1":
        os.environ.setdefault("MYMOMENT_BASE_URL", "http://localhost:9999")

    # Reset and load settings with the updated environment variables
    reset_settings()
    settings = get_settings()

    print(
        "✓ Test environment configured: "
        f"ENVIRONMENT={settings.app.ENVIRONMENT}, "
        f"DB={settings.database.DB_SQLITE_FILE}, "
        f"JWT_SECRET set={bool(settings.security.JWT_SECRET)}"
    )


@pytest.fixture(scope="session")
def project_root() -> Path:
    """Return the project root directory."""
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def examples_dir(project_root: Path) -> Path:
    """Return the examples directory containing test HTML fixtures."""
    return project_root / "examples"


@pytest.fixture(scope="session")
def venv_dir(project_root: Path) -> Path:
    """Return the virtual environment directory."""
    venv_path = project_root / ".venv"
    if not venv_path.exists():
        pytest.skip(f"Virtual environment not found at {venv_path}")
    return venv_path


@pytest.fixture(scope="function")
def test_env_override() -> Generator[dict, None, None]:
    """
    Fixture to temporarily override environment variables for a single test.

    Usage:
        def test_something(test_env_override):
            test_env_override["MYMOMENT_BASE_URL"] = "https://test.example.com"
            # Your test code here
            # Environment will be restored after test
    """
    original_env = os.environ.copy()

    class EnvOverrides(dict):
        def __setitem__(self, key, value):  # type: ignore[override]
            super().__setitem__(key, value)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = str(value)
            reset_settings()
            get_settings()

    overrides: dict = EnvOverrides()

    yield overrides

    # Restore original environment after test
    os.environ.clear()
    os.environ.update(original_env)
    reset_settings()
    get_settings()


@pytest.fixture(scope="session")
def mymoment_test_credentials():
    """
    Provide myMoment test credentials from environment.

    Checks both:
    1. MYMOMENT_USERNAME / MYMOMENT_PASSWORD (live testing)
    2. MYMOMENT_TEST_USERNAME / MYMOMENT_TEST_PASSWORD (dedicated test account)

    Skips tests if credentials not provided.
    """
    # Prefer dedicated test credentials
    username = os.getenv("MYMOMENT_TEST_USERNAME") or os.getenv("MYMOMENT_USERNAME")
    password = os.getenv("MYMOMENT_TEST_PASSWORD") or os.getenv("MYMOMENT_PASSWORD")

    if not username or not password:
        pytest.skip(
            "myMoment credentials not provided. Set MYMOMENT_TEST_USERNAME and "
            "MYMOMENT_TEST_PASSWORD (or MYMOMENT_USERNAME/MYMOMENT_PASSWORD) "
            "environment variables to run live tests."
        )

    return {
        "username": username,
        "password": password,
    }


@pytest.fixture(autouse=True, scope="function")
def isolate_test_database():
    """
    Ensure each test uses an isolated database.

    This fixture runs automatically for all tests and ensures
    test database isolation.
    """
    settings = get_settings()
    if not settings.is_testing:
        raise RuntimeError("Tests must run in testing environment configuration")


# Pytest markers for test categorization
def pytest_collection_modifyitems(config, items):
    """
    Automatically mark tests based on their location.

    This ensures consistent test categorization:
    - tests/unit/* -> @pytest.mark.unit
    - tests/integration/* -> @pytest.mark.integration
    - tests/contract/* -> @pytest.mark.contract
    - tests/performance/* -> @pytest.mark.performance
    """
    for item in items:
        test_path = Path(item.fspath)

        # Auto-mark based on directory
        if "unit" in test_path.parts:
            item.add_marker(pytest.mark.unit)
        elif "integration" in test_path.parts:
            item.add_marker(pytest.mark.integration)
        elif "contract" in test_path.parts:
            item.add_marker(pytest.mark.contract)
        elif "performance" in test_path.parts:
            item.add_marker(pytest.mark.performance)
            item.add_marker(pytest.mark.slow)
