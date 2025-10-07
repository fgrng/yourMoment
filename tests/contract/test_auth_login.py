"""
Contract tests for POST /auth/login endpoint

These tests validate the API contract for user authentication according to the OpenAPI specification.
Tests MUST fail initially since no implementation exists yet (TDD requirement).
"""

import pytest
import os
import tempfile
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from tests.helper import create_test_app, create_test_user

@pytest.mark.contract
@pytest.mark.asyncio
async def test_login_success():
    """Test successful user login returns 200 with auth tokens"""
    # Arrange - setup test database and create user first
    app, db_session = await create_test_app()
    unique_email, password = await create_test_user(app, db_session)

    # Act
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # test login
        login_data = {"email": unique_email, "password": password}
        response = await client.post("/api/v1/auth/login", json=login_data)

        # Assert
        assert response.status_code == 200
        response_json = response.json()

        # Validate AuthResponse schema
        assert "access_token" in response_json
        assert "token_type" in response_json
        assert "expires_in" in response_json
        assert "user" in response_json

        assert isinstance(response_json["access_token"], str)
        assert response_json["token_type"] == "bearer"
        assert isinstance(response_json["expires_in"], int)

        # Validate nested UserResponse schema
        user = response_json["user"]
        assert "id" in user
        assert "email" in user
        assert "is_active" in user
        assert "is_verified" in user
        assert "created_at" in user

        assert user["email"] == login_data["email"]
        assert isinstance(user["is_active"], bool)
        assert isinstance(user["is_verified"], bool)


@pytest.mark.contract
@pytest.mark.asyncio
async def test_login_invalid_credentials():
    """Test login with incorrect password returns 401 Unauthorized"""
    # Arrange - setup test database and create user first
    app, db_session = await create_test_app()
    email, password = await create_test_user(app, db_session)

    login_data = {
        "email": email,
        "password": "wrongpassword"
    }

    # Act
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/auth/login", json=login_data)

        # Assert
        assert response.status_code == 401
        response_json = response.json()

        # Validate ErrorResponse schema
        assert "detail" in response_json


@pytest.mark.contract
@pytest.mark.asyncio
async def test_login_nonexistent_user():
    """Test login with non-existent email returns 401 Unauthorized"""
    # Arrange - setup test database and create user first
    app, db_session = await create_test_app()
    email, password = await create_test_user(app, db_session)

    login_data = {
        "email": "nonexistent@example.com",
        "password": password
    }

    # Act
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/auth/login", json=login_data)

        # Assert
        assert response.status_code == 401
        response_json = response.json()

        # Validate ErrorResponse schema
        assert "detail" in response_json

@pytest.mark.contract
@pytest.mark.asyncio
async def test_login_invalid_email_format():
    """Test login with invalid email format returns 400 Bad Request"""
    # Arrange - setup test database and create user first
    app, db_session = await create_test_app()

    login_data = {
        "email": "invalid-email-format",  # Invalid email format
        "password": "Valid!Password123"
    }

    # Act
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/auth/login", json=login_data)

        # Assert
        assert response.status_code == 422
        response_json = response.json()

        # Validate ErrorResponse schema
        assert "detail" in response_json


@pytest.mark.contract
@pytest.mark.asyncio
async def test_login_missing_email():
    """Test login without email returns 400 Bad Request"""
    # Arrange - setup test database and create user first
    app, db_session = await create_test_app()

    login_data = {
        "password": "Valid!Password123"
        # Missing required email field
    }

    # Act
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/auth/login", json=login_data)

        # Assert
        assert response.status_code == 422
        response_json = response.json()

        # Validate ErrorResponse schema
        assert "detail" in response_json


@pytest.mark.contract
@pytest.mark.asyncio
async def test_login_missing_password():
    """Test login without password returns 400 Bad Request"""
    # Arrange - setup test database and create user first
    app, db_session = await create_test_app()

    login_data = {
        "email": "test@example.com"
        # Missing required password field
    }

    # Act
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/auth/login", json=login_data)

        # Assert
        assert response.status_code == 422
        response_json = response.json()

        # Validate ErrorResponse schema
        assert "detail" in response_json


@pytest.mark.contract
@pytest.mark.asyncio
async def test_login_empty_body():
    """Test login with empty request body returns 400 Bad Request"""
    # Arrange - setup test database and create user first
    app, db_session = await create_test_app()

    # Act
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/auth/login", json={})

        # Assert
        assert response.status_code == 422
        response_json = response.json()

        # Validate ErrorResponse schema
        assert "detail" in response_json


@pytest.mark.contract
@pytest.mark.asyncio
async def test_login_malformed_json():
    """Test login with malformed JSON returns 400 Bad Request"""
    # Arrange - setup test database and create user first
    app, db_session = await create_test_app()

    # Act
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/login",
            content="invalid json",
            headers={"Content-Type": "application/json"}
        )

        # Assert
        assert response.status_code == 400


@pytest.mark.contract
@pytest.mark.asyncio
async def test_login_inactive_user():
    """Test login with inactive user account returns 401 Unauthorized"""
    # Arrange - setup test database and create user first
    app, db_session = await create_test_app()

    # Login Data
    email = "inactive@example.com"
    password = "Valid!Password123"

    # Create inactive user directly
    from src.models.user import User
    import bcrypt

    async with db_session() as session:
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
        password_hash = hashed.decode('utf-8')
        inactive_user = User(
            email=email,
            password_hash=password_hash,
            is_active=False,
            is_verified=False
        )
        session.add(inactive_user)
        await session.commit()

    login_data = {
        "email": email,
        "password": password
    }

    # Act
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/auth/login", json=login_data)

        # Assert
        assert response.status_code == 401
        response_json = response.json()

        # Validate ErrorResponse schema
        assert "detail" in response_json

