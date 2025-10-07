"""
Contract tests for GET /mymoment-credentials endpoints

These tests validate the API contract for retrieving myMoment credentials according to the OpenAPI specification.
Tests follow TDD approach - written before implementation.
"""

import pytest
import uuid
from httpx import AsyncClient, ASGITransport

from tests.helper import create_test_app, create_test_user


@pytest.mark.contract
@pytest.mark.asyncio
async def test_get_credentials_index_success():
    """Test successful retrieval of all user credentials returns 200 with list"""
    # Arrange - setup test database and create user with credentials
    app, db_session = await create_test_app()
    email, password = await create_test_user(app, db_session)

    # Act
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Login to get token
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password}
        )
        token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Create a few credentials first
        credentials_list = [
            {"username": "user1", "password": "pass1", "name": "Account 1"},
            {"username": "user2", "password": "pass2", "name": "Account 2"},
            {"username": "user3", "password": "pass3", "name": "Account 3"}
        ]

        created_ids = []
        for creds in credentials_list:
            create_response = await client.post(
                "/api/v1/mymoment-credentials/create",
                json=creds,
                headers=headers
            )
            assert create_response.status_code == 201
            created_ids.append(create_response.json()["id"])

        # Now get the index
        response = await client.get(
            "/api/v1/mymoment-credentials/index",
            headers=headers
        )

        # Assert
        assert response.status_code == 200
        response_json = response.json()

        # Should return a list
        assert isinstance(response_json, list)
        assert len(response_json) == 3

        # Validate each item has correct schema
        for item in response_json:
            assert "id" in item
            assert "name" in item
            assert "username" in item
            assert "is_active" in item
            assert "created_at" in item
            assert "last_used" in item

            # Password should NOT be included
            assert "password" not in item

            # Validate types
            assert isinstance(item["is_active"], bool)
            assert isinstance(item["created_at"], str)
            uuid.UUID(item["id"])  # Validate UUID format


@pytest.mark.contract
@pytest.mark.asyncio
async def test_get_credentials_index_empty():
    """Test getting credentials index when user has no credentials returns empty list"""
    # Arrange
    app, db_session = await create_test_app()
    email, password = await create_test_user(app, db_session)

    # Act
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Login to get token
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password}
        )
        token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.get(
            "/api/v1/mymoment-credentials/index",
            headers=headers
        )

        # Assert
        assert response.status_code == 200
        response_json = response.json()
        assert isinstance(response_json, list)
        assert len(response_json) == 0


@pytest.mark.contract
@pytest.mark.asyncio
async def test_get_credentials_index_no_authorization():
    """Test getting credentials index without authorization returns 401 Unauthorized"""
    # Arrange
    app, db_session = await create_test_app()

    # Act (no Authorization header)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/mymoment-credentials/index")

        # Assert
        assert response.status_code == 401
        response_json = response.json()
        assert "detail" in response_json


@pytest.mark.contract
@pytest.mark.asyncio
async def test_get_credentials_index_invalid_token():
    """Test getting credentials index with invalid token returns 401 Unauthorized"""
    # Arrange
    app, db_session = await create_test_app()

    invalid_token = "invalid.jwt.token"
    headers = {"Authorization": f"Bearer {invalid_token}"}

    # Act
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/mymoment-credentials/index",
            headers=headers
        )

        # Assert
        assert response.status_code == 401
        response_json = response.json()
        assert "detail" in response_json


@pytest.mark.contract
@pytest.mark.asyncio
async def test_get_credentials_index_isolation():
    """Test that users only see their own credentials (data isolation)"""
    # Arrange - create two users
    app, db_session = await create_test_app()
    email1, password1 = await create_test_user(app, db_session)
    email2, password2 = await create_test_user(app, db_session)

    # Act
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Login as user 1
        login1_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email1, "password": password1}
        )
        token1 = login1_response.json()["access_token"]
        headers1 = {"Authorization": f"Bearer {token1}"}

        # Login as user 2
        login2_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email2, "password": password2}
        )
        token2 = login2_response.json()["access_token"]
        headers2 = {"Authorization": f"Bearer {token2}"}

        # Create credentials for user 1
        await client.post(
            "/api/v1/mymoment-credentials/create",
            json={"username": "user1_account", "password": "pass1", "name": "User 1 Account"},
            headers=headers1
        )

        # Create credentials for user 2
        await client.post(
            "/api/v1/mymoment-credentials/create",
            json={"username": "user2_account", "password": "pass2", "name": "User 2 Account"},
            headers=headers2
        )

        # Get credentials as user 1
        response1 = await client.get(
            "/api/v1/mymoment-credentials/index",
            headers=headers1
        )

        # Get credentials as user 2
        response2 = await client.get(
            "/api/v1/mymoment-credentials/index",
            headers=headers2
        )

        # Assert - each user only sees their own credentials
        assert response1.status_code == 200
        assert response2.status_code == 200

        creds1 = response1.json()
        creds2 = response2.json()

        assert len(creds1) == 1
        assert len(creds2) == 1
        assert creds1[0]["username"] == "user1_account"
        assert creds2[0]["username"] == "user2_account"


@pytest.mark.contract
@pytest.mark.asyncio
async def test_get_credential_by_id_success():
    """Test successful retrieval of specific credential by ID returns 200 with credential data"""
    # Arrange
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
        # Login to get token
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password}
        )
        token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Create a credential first
        create_response = await client.post(
            "/api/v1/mymoment-credentials/create",
            json=credentials_data,
            headers=headers
        )
        assert create_response.status_code == 201
        credential_id = create_response.json()["id"]

        # Get the credential by ID
        response = await client.get(
            f"/api/v1/mymoment-credentials/{credential_id}",
            headers=headers
        )

        # Assert
        assert response.status_code == 200
        response_json = response.json()

        # Validate schema
        assert "id" in response_json
        assert "name" in response_json
        assert "username" in response_json
        assert "is_active" in response_json
        assert "created_at" in response_json
        assert "last_used" in response_json

        # Validate values
        assert response_json["id"] == credential_id
        assert response_json["name"] == credentials_data["name"]
        assert response_json["username"] == credentials_data["username"]
        assert isinstance(response_json["is_active"], bool)

        # Password should NOT be included
        assert "password" not in response_json


@pytest.mark.contract
@pytest.mark.asyncio
async def test_get_credential_by_id_not_found():
    """Test getting non-existent credential by ID returns 404 Not Found"""
    # Arrange
    app, db_session = await create_test_app()
    email, password = await create_test_user(app, db_session)

    non_existent_id = str(uuid.uuid4())

    # Act
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Login to get token
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password}
        )
        token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.get(
            f"/api/v1/mymoment-credentials/{non_existent_id}",
            headers=headers
        )

        # Assert
        assert response.status_code == 404
        response_json = response.json()
        assert "detail" in response_json


@pytest.mark.contract
@pytest.mark.asyncio
async def test_get_credential_by_id_no_authorization():
    """Test getting credential by ID without authorization returns 401 Unauthorized"""
    # Arrange
    app, db_session = await create_test_app()
    fake_id = str(uuid.uuid4())

    # Act (no Authorization header)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/mymoment-credentials/{fake_id}")

        # Assert
        assert response.status_code == 401
        response_json = response.json()
        assert "detail" in response_json


@pytest.mark.contract
@pytest.mark.asyncio
async def test_get_credential_by_id_invalid_token():
    """Test getting credential by ID with invalid token returns 401 Unauthorized"""
    # Arrange
    app, db_session = await create_test_app()
    fake_id = str(uuid.uuid4())

    invalid_token = "invalid.jwt.token"
    headers = {"Authorization": f"Bearer {invalid_token}"}

    # Act
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/mymoment-credentials/{fake_id}",
            headers=headers
        )

        # Assert
        assert response.status_code == 401
        response_json = response.json()
        assert "detail" in response_json


@pytest.mark.contract
@pytest.mark.asyncio
async def test_get_credential_by_id_invalid_uuid():
    """Test getting credential with invalid UUID format returns 422 Unprocessable"""
    # Arrange
    app, db_session = await create_test_app()
    email, password = await create_test_user(app, db_session)

    invalid_uuid = "not-a-valid-uuid"

    # Act
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Login to get token
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password}
        )
        token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.get(
            f"/api/v1/mymoment-credentials/{invalid_uuid}",
            headers=headers
        )

        # Assert - FastAPI validates UUID in path
        assert response.status_code == 422
        response_json = response.json()
        assert "detail" in response_json


@pytest.mark.contract
@pytest.mark.asyncio
async def test_get_credential_by_id_other_user():
    """Test that user cannot access another user's credentials (authorization check)"""
    # Arrange - create two users
    app, db_session = await create_test_app()
    email1, password1 = await create_test_user(app, db_session)
    email2, password2 = await create_test_user(app, db_session)

    # Act
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Login as user 1
        login1_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email1, "password": password1}
        )
        token1 = login1_response.json()["access_token"]
        headers1 = {"Authorization": f"Bearer {token1}"}

        # Login as user 2
        login2_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email2, "password": password2}
        )
        token2 = login2_response.json()["access_token"]
        headers2 = {"Authorization": f"Bearer {token2}"}

        # Create credential as user 1
        create_response = await client.post(
            "/api/v1/mymoment-credentials/create",
            json={"username": "user1_account", "password": "pass1", "name": "User 1 Account"},
            headers=headers1
        )
        assert create_response.status_code == 201
        credential_id = create_response.json()["id"]

        # Try to access user 1's credential as user 2
        response = await client.get(
            f"/api/v1/mymoment-credentials/{credential_id}",
            headers=headers2
        )

        # Assert - should return 404 (not exposing that credential exists)
        assert response.status_code == 404
        response_json = response.json()
        assert "detail" in response_json
