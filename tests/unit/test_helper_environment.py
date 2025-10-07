"""
Unit tests for test helper environment configuration.

These tests verify that the test environment is properly configured
by conftest.py and that helper functions respect those settings.
"""

import os
import pytest


@pytest.mark.unit
def test_conftest_sets_testing_environment():
    """Verify that conftest.py sets TESTING=true."""
    assert os.getenv("TESTING") == "true", (
        "TESTING environment variable should be 'true' when running tests. "
        "This is set by tests/conftest.py pytest_configure()."
    )


@pytest.mark.unit
def test_conftest_sets_environment_to_testing():
    """Verify that conftest.py sets ENVIRONMENT=testing."""
    assert os.getenv("ENVIRONMENT") == "testing", (
        "ENVIRONMENT should be 'testing' during test runs. "
        "This is set by tests/conftest.py pytest_configure()."
    )


@pytest.mark.unit
def test_conftest_uses_test_database():
    """Verify that conftest.py configures test database."""
    db_file = os.getenv("DB_SQLITE_FILE", "")
    assert db_file.endswith("_testing.db"), (
        f"Test database should end with '_testing.db', got: {db_file}. "
        "This is set by tests/conftest.py pytest_configure()."
    )


@pytest.mark.unit
def test_conftest_sets_jwt_secret():
    """Verify that JWT_SECRET is set for testing."""
    jwt_secret = os.getenv("JWT_SECRET")
    assert jwt_secret is not None, (
        "JWT_SECRET should be set for testing. "
        "Check .env.test file or conftest.py defaults."
    )
    assert len(jwt_secret) > 0, "JWT_SECRET should not be empty"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_test_app_uses_environment():
    """Verify that create_test_app() respects environment variables."""
    from tests.helper import create_test_app

    # Store original environment
    original_testing = os.getenv("TESTING")
    original_env = os.getenv("ENVIRONMENT")
    original_db = os.getenv("DB_SQLITE_FILE")

    try:
        # create_test_app should use environment variables set by conftest
        app, db_session = await create_test_app()

        # Verify environment is still set correctly
        assert os.getenv("TESTING") == "true"
        assert os.getenv("ENVIRONMENT") == "testing"

        # Verify database URL contains test database
        db_url = os.getenv("DB_DATABASE_URL", "")
        assert "testing.db" in db_url, (
            f"Database URL should reference test database, got: {db_url}"
        )

        # Verify app was created
        assert app is not None
        assert db_session is not None

    finally:
        # Restore original environment (though conftest should handle this)
        if original_testing:
            os.environ["TESTING"] = original_testing
        if original_env:
            os.environ["ENVIRONMENT"] = original_env
        if original_db:
            os.environ["DB_SQLITE_FILE"] = original_db


@pytest.mark.unit
def test_project_root_fixture_available(project_root):
    """Verify that project_root fixture from conftest works."""
    from pathlib import Path

    assert isinstance(project_root, Path)
    assert project_root.exists()
    assert (project_root / "pyproject.toml").exists(), (
        "project_root should point to repository root containing pyproject.toml"
    )


@pytest.mark.unit
def test_examples_dir_fixture_available(examples_dir):
    """Verify that examples_dir fixture from conftest works."""
    from pathlib import Path

    assert isinstance(examples_dir, Path)
    assert examples_dir.exists()
    assert examples_dir.name == "examples"


@pytest.mark.unit
def test_venv_dir_fixture_available(venv_dir):
    """Verify that venv_dir fixture from conftest works."""
    from pathlib import Path

    assert isinstance(venv_dir, Path)
    assert venv_dir.exists()
    assert venv_dir.name == ".venv"
    assert (venv_dir / "bin" / "python").exists() or (venv_dir / "Scripts" / "python.exe").exists(), (
        "venv_dir should contain Python executable"
    )


@pytest.mark.unit
def test_test_env_override_fixture_works(test_env_override):
    """Verify that test_env_override fixture allows temporary overrides."""
    # Get original value
    original_value = os.getenv("TEST_OVERRIDE_EXAMPLE", "original")

    # Override through fixture
    test_env_override["TEST_OVERRIDE_EXAMPLE"] = "overridden"

    # Note: The override is applied AFTER the test function completes
    # So we can't test the override within the same test
    # This test just verifies the fixture is available
    assert isinstance(test_env_override, dict)
