"""
Contract tests for POST /mymoment-credentials/{credentials_id}/test endpoint.

Verifies authentication requirements, error handling, and the success response
using the real FastAPI application helpers.
"""

import uuid

import pytest
from httpx import AsyncClient, ASGITransport

from tests.helper import create_test_app, create_test_user


@pytest.mark.contract
@pytest.mark.asyncio
async def test_credentials_test_endpoint_requires_authentication():
    """Requests without Authorization header must be rejected with 401."""
    app, _ = await create_test_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/mymoment-credentials/{uuid.uuid4()}/test"
        )

        assert response.status_code == 401
        body = response.json()
        assert "detail" in body


@pytest.mark.contract
@pytest.mark.asyncio
async def test_credentials_test_endpoint_returns_404_for_missing_credentials():
    """Non-existent credential IDs should yield a 404 error response."""
    app, db_session = await create_test_app()
    email, password = await create_test_user(app, db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password}
        )
        token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.post(
            f"/api/v1/mymoment-credentials/{uuid.uuid4()}/test",
            headers=headers
        )

        assert response.status_code == 404
        body = response.json()
        # assert body.get("error") == "not_found" #
        assert "detail" in body


@pytest.mark.contract
@pytest.mark.asyncio
async def test_credentials_test_endpoint_rejects_invalid_uuid():
    """Path parameter must be a valid UUID (FastAPI should return 422)."""
    app, db_session = await create_test_app()
    email, password = await create_test_user(app, db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password}
        )
        token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.post(
            "/api/v1/mymoment-credentials/not-a-uuid/test",
            headers=headers
        )

        assert response.status_code == 422
        body = response.json()
        assert "detail" in body


@pytest.mark.contract
@pytest.mark.asyncio
async def test_credentials_test_endpoint_success(monkeypatch):
    """A valid credential should return 200 with the success message."""
    app, db_session = await create_test_app()
    email, password = await create_test_user(app, db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password}
        )
        token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Create credentials so the endpoint can act on real data
        create_response = await client.post(
            "/api/v1/mymoment-credentials/create",
            json={
                "username": "demo-user",
                "password": "demo-password",
                "name": "Demo credentials"
            },
            headers=headers
        )
        assert create_response.status_code == 201
        credentials_id = create_response.json()["id"]

        # Patch out the scraper authentication flow so the test focuses on the API contract
        async def fake_validate_credentials(self, credentials_id: uuid.UUID, user_id: uuid.UUID | None = None):
            return True, None

        class FakeCredentials:
            def __init__(self, data):
                self.id = uuid.UUID(data["id"])
                self.username = data["username"]

        async def fake_get_credentials_by_id(self, credentials_id: uuid.UUID, user_id: uuid.UUID | None = None):
            return FakeCredentials(create_response.json())

        async def fake_initialize_session(self, credentials_id: uuid.UUID, user_id: uuid.UUID):
            class Context:
                def __init__(self):
                    self.is_authenticated = True
                    self.session_id = None

            return Context()

        async def fake_cleanup_session(self, credentials_id: uuid.UUID):
            return None

        from src.services import mymoment_credentials_service as cred_service
        from src.services import scraper_service as scraper_service_module

        monkeypatch.setattr(
            cred_service.MyMomentCredentialsService,
            "validate_credentials",
            fake_validate_credentials,
        )
        monkeypatch.setattr(
            cred_service.MyMomentCredentialsService,
            "get_credentials_by_id",
            fake_get_credentials_by_id,
        )
        monkeypatch.setattr(
            scraper_service_module.ScraperService,
            "_initialize_single_session",
            fake_initialize_session,
        )
        monkeypatch.setattr(
            scraper_service_module.ScraperService,
            "cleanup_session",
            fake_cleanup_session,
        )

        response = await client.post(
            f"/api/v1/mymoment-credentials/{credentials_id}/test",
            headers=headers
        )

        assert response.status_code == 200
        body = response.json()
        assert body == {
            "message": "Authentication successful",
            "username": "demo-user",
            "platform": "myMoment"
        }
