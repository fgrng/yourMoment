"""
Contract tests for POST /auth/register endpoint

These tests validate the API contract for user registration according to the OpenAPI specification.
Tests MUST fail initially since no implementation exists yet (TDD requirement).
"""

import pytest
import os
import tempfile
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from tests.helper import create_test_app

@pytest.mark.contract
@pytest.mark.asyncio
async def test_register_success():
    """Test successful user registration returns 201 with user data"""
    # # Arrange - setup test database
    # with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp_file:
    #     db_path = tmp_file.name

    # os.environ['DB_DATABASE_URL'] = f'sqlite+aiosqlite:///{db_path}'
    # os.environ['JWT_SECRET'] = 'test-secret-for-contract-test'
    # os.environ['ENVIRONMENT'] = 'development'
    app, db_session = await create_test_app()

    import time
    registration_data = {
        "email": f"test{int(time.time())}@example.com",
        "password": "Valid!Password123"
    }

    # Act
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/auth/register", json=registration_data)

        # Assert
        assert response.status_code == 201
        response_json = response.json()

        # Our API returns AuthResponse with nested user data
        assert "access_token" in response_json
        assert "user" in response_json
        user_data = response_json["user"]

        # Validate UserResponse schema
        assert "id" in user_data
        assert "email" in user_data
        assert "is_active" in user_data
        assert "is_verified" in user_data
        assert "created_at" in user_data

        assert user_data["email"] == registration_data["email"]
        assert isinstance(user_data["is_active"], bool)
        assert isinstance(user_data["is_verified"], bool)


@pytest.mark.contract
@pytest.mark.asyncio
async def test_register_invalid_email():
    """Test registration with invalid email returns 422 Unprocessable"""
    # Arrange - setup test database
    app, db_session = await create_test_app()

    registration_data = {
        "email": "invalid-email",  # Invalid email format
        "password": "Valid!Password123"
    }

    # Act
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/auth/register", json=registration_data)

        # Assert
        assert response.status_code == 422
        response_json = response.json()

        # Validate Pydantic error response format
        assert "detail" in response_json


@pytest.mark.contract
@pytest.mark.asyncio
async def test_register_short_password():
    """Test registration with password < 8 characters returns 422 Unprocessable"""
    # Arrange - setup test database
    app, db_session = await create_test_app()

    import time
    registration_data = {
        "email": f"test{int(time.time())}@example.com",
        "password": "short"
    }

    # Act
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/auth/register", json=registration_data)

        # Assert
        assert response.status_code == 422
        response_json = response.json()

        # Validate Pydantic error response format
        assert "detail" in response_json


@pytest.mark.contract
@pytest.mark.asyncio
async def test_register_missing_email():
    """Test registration without email returns 422 Unprocessable"""
    # Arrange - setup test database
    app, db_session = await create_test_app()

    registration_data = {
        "password": "Valid!Password123"
        # Missing required email field
    }

    # Act
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/auth/register", json=registration_data)

        # Assert
        assert response.status_code == 422
        response_json = response.json()

        # Validate Pydantic error response format
        assert "detail" in response_json



@pytest.mark.contract
@pytest.mark.asyncio
async def test_register_missing_password():
    """Test registration without password returns 422 Unprocessable"""
    # Arrange - setup test database
    app, db_session = await create_test_app()

    import time
    registration_data = {
        "email": f"test{int(time.time())}@example.com",
        # Missing required password field
    }

    # Act
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/auth/register", json=registration_data)

        # Assert
        assert response.status_code == 422
        response_json = response.json()

        # Validate Pydantic error response format
        assert "detail" in response_json



@pytest.mark.contract
@pytest.mark.asyncio
async def test_register_duplicate_email():
    """Test registration with existing email returns 409 Conflict"""
    # Arrange - setup test database
    app, db_session = await create_test_app()

    import time
    email = f"duplicate{int(time.time())}@example.com"
    registration_data = {
        "email": email,
        "password": "Valid!Password123"
    }

    # Act
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # First registration - should succeed
        response1 = await client.post("/api/v1/auth/register", json=registration_data)
        response1_json = response1.json()
        user_id1 = response1_json["user"]["id"]
        created_at1 = response1_json["user"]["created_at"]
        assert response1.status_code == 201

        # Second registration with same email - should fail
        response = await client.post("/api/v1/auth/register", json=registration_data)

        # Assert
        assert response.status_code == 409
        response_json = response.json()

        # Validate error response has detail key
        assert "detail" in response_json

        # Validate old user still present
        from sqlalchemy import select
        from src.models.user import User
        import uuid
        # Query database
        async with db_session() as session:
            # Find user by email
            if isinstance(user_id1, str):
                user_id1 = uuid.UUID(user_id1)
            stmt = select(User).where(User.id == user_id1)
            result = await session.execute(stmt)
            user1 = result.scalar_one_or_none()
            assert user1.created_at.isoformat() == created_at1


@pytest.mark.contract
@pytest.mark.asyncio
async def test_register_empty_body():
    """Test registration with empty request body returns 422 Unprocessable"""
    # Arrange - setup test database
    app, db_session = await create_test_app()

    # Act
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/auth/register", json={})

        # Assert - Empty body means missing required fields (email, password)
        assert response.status_code == 422
        response_json = response.json()

        # Validate Pydantic error response format
        assert "detail" in response_json


@pytest.mark.contract
@pytest.mark.asyncio
async def test_register_malformed_json():
    """Test registration with malformed JSON returns 400 Bad Request"""
    # Arrange - setup test database
    app, db_session = await create_test_app()

    # Act
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/register",
            content="invalid json",
            headers={"Content-Type": "application/json"}
        )

        # Assert - Malformed JSON caught by middleware/FastAPI
        assert response.status_code == 400
