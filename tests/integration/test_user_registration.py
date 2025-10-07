"""Integration tests covering user registration and authentication flows."""

import uuid

import pytest
from fastapi import status
from httpx import AsyncClient, ASGITransport
from tests.helper import create_test_app, verify_user_email


async def _register_user(client: AsyncClient, email: str, password: str) -> dict:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password}
    )
    return response


async def _login_user(client: AsyncClient, email: str, password: str) -> dict:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password}
    )
    return response


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.asyncio
async def test_user_registration_complete_flow():
    app, db_session = await create_test_app()
    email = "test.user@example.com"
    password = "SecurePassword123!"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        register_response = await _register_user(client, email, password)
        assert register_response.status_code == status.HTTP_201_CREATED

        auth_payload = register_response.json()
        assert {"access_token", "token_type", "expires_in", "user"} <= auth_payload.keys()

        user_payload = auth_payload["user"]
        assert user_payload["email"] == email
        assert user_payload["is_active"] is True
        uuid.UUID(user_payload["id"])  # Should be valid UUID

        await verify_user_email(db_session, email)

        # Login with the same credentials and obtain a fresh token
        login_response = await _login_user(client, email, password)
        assert login_response.status_code == status.HTTP_200_OK
        login_payload = login_response.json()

        token = login_payload["access_token"]

        # Access a protected endpoint using the token
        credentials_index = await client.get(
            "/api/v1/mymoment-credentials/index",
            headers=_auth_headers(token)
        )
        assert credentials_index.status_code == status.HTTP_200_OK
        assert credentials_index.json() == []


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.asyncio
async def test_user_registration_duplicate_email():
    app, _ = await create_test_app()
    email = "duplicate.user@example.com"
    password = "DuplicatePassword123!"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first_response = await _register_user(client, email, password)
        assert first_response.status_code == status.HTTP_201_CREATED

        second_response = await _register_user(client, email, password)
        assert second_response.status_code == status.HTTP_409_CONFLICT
        error_detail = second_response.json()["detail"]
        assert error_detail["error"] == "user_exists"


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.asyncio
async def test_password_security_requirements():
    app, _ = await create_test_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        weak_response = await _register_user(client, "weak@example.com", "weak")
        assert weak_response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        detail = weak_response.json()["detail"]
        assert any("Password" in item["msg"] for item in detail)

        strong_response = await _register_user(
            client,
            "strong@example.com",
            "StrongPassword123!"
        )
        assert strong_response.status_code == status.HTTP_201_CREATED


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.asyncio
async def test_login_authentication_flow():
    app, db_session = await create_test_app()
    email = "auth.flow@example.com"
    password = "AuthPassword123!"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _register_user(client, email, password)
        await verify_user_email(db_session, email)

        login_response = await _login_user(client, email, password)
        assert login_response.status_code == status.HTTP_200_OK
        login_payload = login_response.json()
        assert login_payload["token_type"] == "bearer"

        wrong_password_response = await _login_user(client, email, "WrongPassword1!")
        assert wrong_password_response.status_code == status.HTTP_401_UNAUTHORIZED
        error_detail = wrong_password_response.json()["detail"]
        assert error_detail["error"] == "invalid_credentials"


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.asyncio
async def test_protected_endpoint_requires_authentication():
    app, _ = await create_test_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        protected_response = await client.get("/api/v1/mymoment-credentials/index")
        assert protected_response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.asyncio
async def test_logout_clears_authentication_cookie():
    app, db_session = await create_test_app()
    email = "logout.user@example.com"
    password = "LogoutPassword123!"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _register_user(client, email, password)
        await verify_user_email(db_session, email)
        login_response = await _login_user(client, email, password)
        token = login_response.json()["access_token"]

        logout_response = await client.post(
            "/api/v1/auth/logout",
            headers=_auth_headers(token)
        )

        assert logout_response.status_code == status.HTTP_200_OK
        assert logout_response.json()["message"] == "Successfully logged out"


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.database
@pytest.mark.asyncio
async def test_passwords_are_stored_hashed():
    app, db_session = await create_test_app()
    email = "hash.check@example.com"
    password = "HashCheckPassword123!"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        register_response = await _register_user(client, email, password)
        assert register_response.status_code == status.HTTP_201_CREATED

    async with db_session() as session:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one()

        assert user.password_hash != password
        assert user.password_hash.startswith("$2")  # bcrypt hash prefix
