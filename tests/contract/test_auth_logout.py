"""Contract tests for POST /api/v1/auth/logout."""

import pytest
from httpx import AsyncClient, ASGITransport

from tests.helper import create_test_app, create_test_user


@pytest.mark.contract
@pytest.mark.asyncio
async def test_logout_success():
    """Authenticated users should be able to log out successfully."""
    app, db_session = await create_test_app()
    email, password = await create_test_user(app, db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password}
        )
        assert login_response.status_code == 200
        token = login_response.json()["access_token"]

        logout_response = await client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert logout_response.status_code == 200
        assert logout_response.json() == {"message": "Successfully logged out"}


@pytest.mark.contract
@pytest.mark.asyncio
async def test_logout_requires_authentication():
    """Logout without credentials should be rejected."""
    app, _ = await create_test_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/auth/logout")
        assert response.status_code == 401
        assert response.json()["detail"] == "No authentication token provided"
