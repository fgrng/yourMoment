"""Contract tests for updating, patching, deleting, and validating myMoment credentials."""

import uuid

import pytest
from httpx import AsyncClient, ASGITransport

from sqlalchemy import select

from tests.helper import create_test_app, create_test_user
from src.models.mymoment_login import MyMomentLogin


async def _login(client: AsyncClient, email: str, password: str) -> dict:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _create_credentials(client: AsyncClient, headers: dict, name: str = "Primary") -> str:
    response = await client.post(
        "/api/v1/mymoment-credentials/create",
        json={
            "name": f"{name} Credentials",
            "username": f"{name.lower()}_user",
            "password": "Secur3Password!"
        },
        headers=headers
    )
    assert response.status_code == 201
    return response.json()["id"]


@pytest.mark.contract
@pytest.mark.asyncio
async def test_update_credentials_put_success():
    app, db_session = await create_test_app()
    email, password = await create_test_user(app, db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _login(client, email, password)
        credential_id = await _create_credentials(client, headers)

        update_response = await client.put(
            f"/api/v1/mymoment-credentials/{credential_id}",
            json={
                "name": "Updated Credentials",
                "username": "updated_user",
                "password": "UpdatedPassword123!"
            },
            headers=headers
        )
        assert update_response.status_code == 200
        payload = update_response.json()
        assert payload["name"] == "Updated Credentials"
        assert payload["username"] == "updated_user"


@pytest.mark.contract
@pytest.mark.asyncio
async def test_update_credentials_patch_success():
    app, db_session = await create_test_app()
    email, password = await create_test_user(app, db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _login(client, email, password)
        credential_id = await _create_credentials(client, headers, name="Patch")

        patch_response = await client.patch(
            f"/api/v1/mymoment-credentials/{credential_id}",
            json={
                "name": "Patched Credentials",
                "username": "patched_user",
                "password": "PatchedPassword123!"
            },
            headers=headers
        )
        assert patch_response.status_code == 200
        assert patch_response.json()["name"] == "Patched Credentials"


@pytest.mark.contract
@pytest.mark.asyncio
async def test_delete_credentials_success():
    app, db_session = await create_test_app()
    email, password = await create_test_user(app, db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _login(client, email, password)
        credential_id = await _create_credentials(client, headers, name="Delete")

        delete_response = await client.delete(
            f"/api/v1/mymoment-credentials/{credential_id}",
            headers=headers
        )
        assert delete_response.status_code == 204

        check_response = await client.get(
            f"/api/v1/mymoment-credentials/{credential_id}",
            headers=headers
        )
        assert check_response.status_code == 404

        async with db_session() as session:
            result = await session.execute(
                select(MyMomentLogin).where(MyMomentLogin.id == uuid.UUID(credential_id))
            )
            credential = result.scalar_one_or_none()

            assert credential is not None
            assert credential.is_active is False


@pytest.mark.contract
@pytest.mark.asyncio
async def test_validate_credentials_success():
    app, db_session = await create_test_app()
    email, password = await create_test_user(app, db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _login(client, email, password)
        credential_id = await _create_credentials(client, headers, name="Validate")

        validate_response = await client.post(
            f"/api/v1/mymoment-credentials/{credential_id}/validate",
            headers=headers
        )
        assert validate_response.status_code == 200
        assert validate_response.json()["message"] == "Credentials are valid"


@pytest.mark.contract
@pytest.mark.asyncio
async def test_credentials_write_endpoints_require_authentication():
    app, _ = await create_test_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response_put = await client.put(
            f"/api/v1/mymoment-credentials/{uuid.uuid4()}",
            json={"name": "n", "username": "u", "password": "p"}
        )
        assert response_put.status_code == 401

        response_patch = await client.patch(
            f"/api/v1/mymoment-credentials/{uuid.uuid4()}",
            json={"name": "n", "username": "u", "password": "p"}
        )
        assert response_patch.status_code == 401

        response_delete = await client.delete(f"/api/v1/mymoment-credentials/{uuid.uuid4()}")
        assert response_delete.status_code == 401

        response_validate = await client.post(
            f"/api/v1/mymoment-credentials/{uuid.uuid4()}/validate"
        )
        assert response_validate.status_code == 401
