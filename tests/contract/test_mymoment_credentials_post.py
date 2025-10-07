"""
Contract tests for POST /mymoment-credentials endpoint

These tests validate the API contract for adding myMoment credentials according to the OpenAPI specification.
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
async def test_create_mymoment_credentials_success():
    """Test successful creation of myMoment credentials returns 201 with credential data"""
    # Arrange - setup test database and create user first
    app, db_session = await create_test_app()
    email, password = await create_test_user(app, db_session)

    credentials_data = {
        "username": "mymoment_user",
        "password": "mymoment_password123",
        "name": "My Test Login"
    }

    # Act
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # First register and login to get real token
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password}
        )
        valid_token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {valid_token}"}
        response = await client.post(
            "/api/v1/mymoment-credentials/create",
            json=credentials_data,
            headers=headers
        )

        # Assert
        assert response.status_code == 201
        response_json = response.json()

        # Validate MyMomentCredentialsResponse schema
        assert "id" in response_json
        assert "name" in response_json
        assert "username" in response_json
        assert "is_active" in response_json
        assert "created_at" in response_json
        assert "last_used" in response_json

        assert response_json["name"] == credentials_data["name"]
        assert response_json["username"] == credentials_data["username"]
        assert isinstance(response_json["is_active"], bool)
        assert isinstance(response_json["created_at"], str)
        assert response_json["last_used"] is None  # Should be None initially

        # Password should NOT be included in response
        assert "password" not in response_json

        # Validate UUID format for id
        import uuid
        uuid.UUID(response_json["id"])  # Should not raise exception for valid UUID


@pytest.mark.contract
@pytest.mark.asyncio
async def test_create_mymoment_credentials_no_authorization():
    """Test creating myMoment credentials without authorization returns 401 Unauthorized"""
    # Arrange
    app, db_session = await create_test_app()

    credentials_data = {
        "username": "mymoment_user",
        "password": "mymoment_password123",
        "name": "Test Login"
    }

    # Act (no Authorization header)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/mymoment-credentials/create", json=credentials_data)

        # Assert
        assert response.status_code == 401
        response_json = response.json()

        # Validate ErrorResponse schema
        assert "detail" in response_json


@pytest.mark.contract
@pytest.mark.asyncio
async def test_create_mymoment_credentials_invalid_token():
    """Test creating myMoment credentials with invalid token returns 401 Unauthorized"""
    # Arrange
    app, db_session = await create_test_app()

    invalid_token = "invalid.jwt.token"
    headers = {"Authorization": f"Bearer {invalid_token}"}

    credentials_data = {
        "username": "mymoment_user",
        "password": "mymoment_password123",
        "name": "Test Login"
    }

    # Act
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/mymoment-credentials/create",
            json=credentials_data,
            headers=headers
        )

        # Assert
        assert response.status_code == 401
        response_json = response.json()

        # Validate ErrorResponse schema
        assert "detail" in response_json


@pytest.mark.contract
@pytest.mark.asyncio
async def test_create_mymoment_credentials_missing_username():
    """Test creating myMoment credentials without username returns 422 Unprocessable"""
    # Arrange
    app, db_session = await create_test_app()

    import time
    unique_email = f"test{int(time.time())}@example.com"
    password = "Valid!Password123"

    credentials_data = {
        "password": "mymoment_password123",
        "name": "Test Login"
        # Missing required username field
    }

    # Act
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Register and get token
        register_response = await client.post(
            "/api/v1/auth/register",
            json={"email": unique_email, "password": password}
        )
        valid_token = register_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {valid_token}"}

        response = await client.post(
            "/api/v1/mymoment-credentials/create",
            json=credentials_data,
            headers=headers
        )

        # Assert
        assert response.status_code == 422
        response_json = response.json()

        # Validate ErrorResponse schema
        assert "detail" in response_json


@pytest.mark.contract
@pytest.mark.asyncio
async def test_create_mymoment_credentials_missing_password():
    """Test creating myMoment credentials without password returns 422 Unprocessable"""
    # Arrange
    app, db_session = await create_test_app()

    import time
    unique_email = f"test{int(time.time())}@example.com"
    password = "Valid!Password123"

    credentials_data = {
        "username": "mymoment_user",
        "name": "Test Login"
        # Missing required password field
    }

    # Act
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Register and get token
        register_response = await client.post(
            "/api/v1/auth/register",
            json={"email": unique_email, "password": password}
        )
        valid_token = register_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {valid_token}"}

        response = await client.post(
            "/api/v1/mymoment-credentials/create",
            json=credentials_data,
            headers=headers
        )

        # Assert
        assert response.status_code == 422
        response_json = response.json()

        # Validate ErrorResponse schema
        assert "detail" in response_json


@pytest.mark.contract
@pytest.mark.asyncio
async def test_create_mymoment_credentials_empty_username():
    """Test creating myMoment credentials with empty username returns 422 Unprocessable"""
    # Arrange
    app, db_session = await create_test_app()

    import time
    unique_email = f"test{int(time.time())}@example.com"
    password = "Valid!Password123"

    credentials_data = {
        "username": "",  # Empty username
        "password": "mymoment_password123",
        "name": "Test Login"
    }

    # Act
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Register and get token
        register_response = await client.post(
            "/api/v1/auth/register",
            json={"email": unique_email, "password": password}
        )
        valid_token = register_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {valid_token}"}

        response = await client.post(
            "/api/v1/mymoment-credentials/create",
            json=credentials_data,
            headers=headers
        )

        # Assert
        assert response.status_code == 422
        response_json = response.json()

        # Validate ErrorResponse schema
        assert "detail" in response_json


@pytest.mark.contract
@pytest.mark.asyncio
async def test_create_mymoment_credentials_empty_password():
    """Test creating myMoment credentials with empty password returns 422 Unprocessable"""
    # Arrange
    app, db_session = await create_test_app()

    import time
    unique_email = f"test{int(time.time())}@example.com"
    password = "Valid!Password123"

    credentials_data = {
        "username": "mymoment_user",
        "password": "",  # Empty password
        "name": "Test Login"
    }

    # Act
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Register and get token
        register_response = await client.post(
            "/api/v1/auth/register",
            json={"email": unique_email, "password": password}
        )
        valid_token = register_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {valid_token}"}

        response = await client.post(
            "/api/v1/mymoment-credentials/create",
            json=credentials_data,
            headers=headers
        )

        # Assert
        assert response.status_code == 422
        response_json = response.json()

        # Validate ErrorResponse schema
        assert "detail" in response_json


@pytest.mark.contract
@pytest.mark.asyncio
async def test_create_mymoment_credentials_empty_body():
    """Test creating myMoment credentials with empty request body returns 422 Unprocessable"""
    # Arrange
    app, db_session = await create_test_app()

    import time
    unique_email = f"test{int(time.time())}@example.com"
    password = "Valid!Password123"

    # Act
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Register and get token
        register_response = await client.post(
            "/api/v1/auth/register",
            json={"email": unique_email, "password": password}
        )
        valid_token = register_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {valid_token}"}

        response = await client.post(
            "/api/v1/mymoment-credentials/create",
            json={},
            headers=headers
        )

        # Assert
        assert response.status_code == 422
        response_json = response.json()

        # Validate ErrorResponse schema
        assert "detail" in response_json


@pytest.mark.contract
@pytest.mark.asyncio
async def test_create_mymoment_credentials_malformed_json():
    """Test creating myMoment credentials with malformed JSON returns 400 Bad Request"""
    # Arrange
    app, db_session = await create_test_app()

    import time
    unique_email = f"test{int(time.time())}@example.com"
    password = "Valid!Password123"

    # Act
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Register and get token
        register_response = await client.post(
            "/api/v1/auth/register",
            json={"email": unique_email, "password": password}
        )
        valid_token = register_response.json()["access_token"]
        headers = {
            "Authorization": f"Bearer {valid_token}",
            "Content-Type": "application/json"
        }

        response = await client.post(
            "/api/v1/mymoment-credentials/create",
            content="invalid json",
            headers=headers
        )

        # Assert
        assert response.status_code == 400


@pytest.mark.contract
@pytest.mark.asyncio
async def test_create_mymoment_credentials_extra_fields():
    """Test creating myMoment credentials with extra fields should ignore them"""
    # Arrange
    app, db_session = await create_test_app()

    import time
    unique_email = f"test{int(time.time())}@example.com"
    password = "Valid!Password123"

    credentials_data = {
        "username": "mymoment_user",
        "password": "mymoment_password123",
        "name": "Test Login",
        "extra_field": "should_be_ignored",  # Extra field not in schema
        "another_extra": 123
    }

    # Act
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Register and get token
        register_response = await client.post(
            "/api/v1/auth/register",
            json={"email": unique_email, "password": password}
        )
        valid_token = register_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {valid_token}"}

        response = await client.post(
            "/api/v1/mymoment-credentials/create",
            json=credentials_data,
            headers=headers
        )

        # Assert
        assert response.status_code == 201
        response_json = response.json()

        # Should contain only the expected fields
        assert "username" in response_json
        assert response_json["username"] == credentials_data["username"]

        # Extra fields should not be in response
        assert "extra_field" not in response_json
        assert "another_extra" not in response_json
