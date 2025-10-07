"""Helper methods for test environment setup using the unified settings layer."""

import os
from pathlib import Path
from typing import Tuple

from src.config.settings import get_settings, reset_settings
from src.config.database import get_database_manager, close_database


async def create_test_app() -> Tuple:
    """
    Create a FastAPI test application with a clean database.

    This function:
    1. Uses environment variables already configured by conftest.py
    2. Creates/recreates the test database schema
    3. Returns the FastAPI app and a database session maker

    Environment variables used (set by conftest.py):
    - TESTING: Should be "true"
    - ENVIRONMENT: Should be "testing"
    - DB_SQLITE_FILE: Test database file (default: yourMoment_testing.db)
    - JWT_SECRET: Test JWT secret
    - SECRET_KEY: Test secret key

    Returns:
        Tuple[FastAPI, sessionmaker]: The app instance and database session maker
    """
    # Ensure core environment variables are set for testing
    os.environ.setdefault("ENVIRONMENT", "testing")
    os.environ.setdefault("TESTING", "true")
    os.environ.setdefault("DB_SQLITE_FILE", "yourMoment_testing.db")
    os.environ.setdefault("YOURMOMENT_ENCRYPTION_KEY", "bzD6gWQK3pWoaVuv5-YW_EdS-gtnznuaVD91nBZ2e1w=")
    os.environ.setdefault("YOURMOMENT_KEY_FILE", ".encryption_key.test")
    os.environ.setdefault("JWT_SECRET", "test-jwt-secret")
    os.environ.setdefault("SECRET_KEY", "test-secret-key")

    # Normalize SQLite file path and database URL for the test run
    db_file = Path(os.environ["DB_SQLITE_FILE"]).resolve()
    os.environ["DB_SQLITE_FILE"] = str(db_file)
    os.environ.setdefault("DB_DATABASE_URL", f"sqlite+aiosqlite:///{db_file}")

    # Reset and preload settings so downstream imports see the updated configuration
    reset_settings()
    settings = get_settings()
    if not settings.is_testing:
        raise RuntimeError("create_test_app must run with ENVIRONMENT=testing")

    # Reset database manager state for a clean schema
    await close_database()

    from src.models.base import Base

    db_manager = get_database_manager()
    engine = await db_manager.create_engine()

    # Drop and recreate all tables for clean test state
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    # Create session maker
    db_session = await db_manager.create_sessionmaker()

    # Use real app implementation
    from src.main import create_app
    app = create_app()

    return app, db_session

async def create_test_user(app, db_session) -> Tuple[str, str]:
    """
    Create a verified test user via the registration API.

    This function:
    1. Generates a unique email address (timestamp + random number)
    2. Registers the user via POST /api/v1/auth/register
    3. Manually verifies the user's email in the database
    4. Returns credentials for use in login tests

    Args:
        app: FastAPI application instance
        db_session: Database session maker from create_test_app()

    Returns:
        Tuple[str, str]: (email, password) credentials for the created user

    Example:
        app, db_session = await create_test_app()
        email, password = await create_test_user(app, db_session)
        # Use email/password for login tests
    """
    import time
    import random
    import uuid
    from httpx import AsyncClient, ASGITransport
    from sqlalchemy import select
    from src.models.user import User

    # Generate unique email to avoid conflicts
    unique_email = f"login{int(time.time())}_{random.randint(1000, 9999)}@example.com"
    password = "Valid!Password123"

    # Register user via API
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/register",
            json={"email": unique_email, "password": password}
        )

        if response.status_code != 201:
            raise RuntimeError(
                f"Failed to create test user. Status: {response.status_code}, "
                f"Response: {response.text}"
            )

        # Extract user ID from registration response
        response_json = response.json()
        user_id = response_json["user"]["id"]

    # Manually verify the user's email (bypass email verification requirement)
    await verify_user_email(db_session, unique_email)

    return unique_email, password


async def verify_user_email(db_session, email: str) -> None:
    """Mark a user as verified in the database for testing convenience."""
    from sqlalchemy import select
    from src.models.user import User

    async with db_session() as session:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if not user:
            raise RuntimeError(f"User {email} not found in database for verification")
        user.is_verified = True
        await session.commit()
