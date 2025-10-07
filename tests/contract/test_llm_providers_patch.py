"""Contract tests for updating LLM provider configurations."""

import pytest
from httpx import AsyncClient, ASGITransport

from tests.helper import create_test_app, create_test_user


async def _authenticate(client: AsyncClient, email: str, password: str) -> dict:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password}
    )
    assert response.status_code == 200
    data = response.json()
    return {
        "Authorization": f"Bearer {data['access_token']}"
    }


@pytest.mark.contract
@pytest.mark.asyncio
async def test_patch_llm_provider_updates_model_name():
    app, db_session = await create_test_app()
    email, password = await create_test_user(app, db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _authenticate(client, email, password)

        create_response = await client.post(
            "/api/v1/llm-providers/create",
            json={
                "provider_name": "openai",
                "api_key": "sk-test-openai",
                "model_name": "gpt-4o-mini"
            },
            headers=headers
        )
        assert create_response.status_code == 201
        provider_id = create_response.json()["id"]

        patch_response = await client.patch(
            f"/api/v1/llm-providers/{provider_id}",
            json={"model_name": "gpt-4o"},
            headers=headers
        )
        assert patch_response.status_code == 200
        assert patch_response.json()["model_name"] == "gpt-4o"


@pytest.mark.contract
@pytest.mark.asyncio
async def test_patch_llm_provider_requires_fields():
    app, db_session = await create_test_app()
    email, password = await create_test_user(app, db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _authenticate(client, email, password)

        create_response = await client.post(
            "/api/v1/llm-providers/create",
            json={
                "provider_name": "mistral",
                "api_key": "sk-test-mistral",
                "model_name": "mistral-small"
            },
            headers=headers
        )
        provider_id = create_response.json()["id"]

        response = await client.patch(
            f"/api/v1/llm-providers/{provider_id}",
            json={},
            headers=headers
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "No valid update fields provided"


@pytest.mark.contract
@pytest.mark.asyncio
async def test_patch_llm_provider_requires_authentication():
    app, db_session = await create_test_app()
    email, password = await create_test_user(app, db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _authenticate(client, email, password)
        create_response = await client.post(
            "/api/v1/llm-providers/create",
            json={
                "provider_name": "openai",
                "api_key": "sk-test-key",
                "model_name": "gpt-4o"
            },
            headers=headers
        )
        assert create_response.status_code == 201, f"Failed to create provider: {create_response.json()}"
        provider_id = create_response.json()["id"]

    # Use a new client without authentication to test auth requirement
    async with AsyncClient(transport=transport, base_url="http://test") as unauthenticated_client:
        response = await unauthenticated_client.patch(
            f"/api/v1/llm-providers/{provider_id}",
            json={"model_name": "gpt-4o-mini"}
        )
        assert response.status_code == 401
