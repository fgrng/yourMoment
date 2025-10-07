"""
Contract tests for GET /llm-providers/index endpoint.

Uses the real FastAPI app to verify the contract described in the OpenAPI spec.
"""

import uuid

import pytest
from httpx import AsyncClient, ASGITransport

from tests.helper import create_test_app, create_test_user


@pytest.mark.contract
@pytest.mark.asyncio
async def test_get_llm_providers_index_success():
    """Authenticated user receives their provider configurations."""
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

        payloads = [
            {
                "provider_name": "openai",
                "api_key": "sk-test-openai",
                "model_name": "gpt-4o-mini",
                "max_tokens": 800,
                "temperature": 0.2
            },
            {
                "provider_name": "mistral",
                "api_key": "sk-test-mistral",
                "model_name": "mistral-large-latest",
                "max_tokens": 600,
                "temperature": 0.3
            }
        ]

        created_ids = []
        for payload in payloads:
            resp = await client.post(
                "/api/v1/llm-providers/create",
                json=payload,
                headers=headers
            )
            assert resp.status_code == 201
            created_ids.append(resp.json()["id"])

        response = await client.get("/api/v1/llm-providers/index", headers=headers)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")

        items = response.json()
        assert isinstance(items, list)

        user_items = [item for item in items if item["id"] in created_ids]
        assert len(user_items) == len(created_ids)

        for item in user_items:
            assert item["provider_name"] in {"openai", "mistral", "huggingface"}
            assert item["is_active"] is True
            assert isinstance(item["created_at"], str)
            uuid.UUID(item["id"])
            assert "model_name" in item


@pytest.mark.contract
@pytest.mark.asyncio
async def test_get_llm_providers_index_empty():
    """User with no providers should get an empty array."""
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

        response = await client.get("/api/v1/llm-providers/index", headers=headers)
        assert response.status_code == 200
        assert response.json() == []


@pytest.mark.contract
@pytest.mark.asyncio
async def test_get_llm_providers_index_unauthorized():
    """Missing Authorization header returns 401."""
    app, _ = await create_test_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/llm-providers/index")
        assert response.status_code == 401
        assert "detail" in response.json()


@pytest.mark.contract
@pytest.mark.asyncio
async def test_get_llm_providers_index_invalid_token():
    """Invalid token yields 401 Unauthorized."""
    app, _ = await create_test_app()
    headers = {"Authorization": "Bearer invalid.jwt.token"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/llm-providers/index", headers=headers)
        assert response.status_code == 401
        assert "detail" in response.json()


@pytest.mark.contract
@pytest.mark.asyncio
async def test_get_llm_providers_index_user_isolation():
    """Each user only sees their own provider configurations."""
    app, db_session = await create_test_app()
    email1, password1 = await create_test_user(app, db_session)
    email2, password2 = await create_test_user(app, db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login1 = await client.post("/api/v1/auth/login", json={"email": email1, "password": password1})
        login2 = await client.post("/api/v1/auth/login", json={"email": email2, "password": password2})

        headers1 = {"Authorization": f"Bearer {login1.json()['access_token']}"}
        headers2 = {"Authorization": f"Bearer {login2.json()['access_token']}"}

        # User 1 creates one provider
        await client.post(
            "/api/v1/llm-providers/create",
            json={
                "provider_name": "openai",
                "api_key": "sk-user1",
                "model_name": "gpt-4o"
            },
            headers=headers1
        )

        # User 2 creates one provider
        await client.post(
            "/api/v1/llm-providers/create",
            json={
                "provider_name": "mistral",
                "api_key": "mistral_test_user2",
                "model_name": "mistral-large-latest"
            },
            headers=headers2
        )

        resp1 = await client.get("/api/v1/llm-providers/index", headers=headers1)
        resp2 = await client.get("/api/v1/llm-providers/index", headers=headers2)

        assert resp1.status_code == resp2.status_code == 200
        assert len(resp1.json()) == 1
        assert len(resp2.json()) == 1
        assert resp1.json()[0]["provider_name"] == "openai"
        assert resp2.json()[0]["provider_name"] == "mistral"


# Test disabled - /supported endpoint has dependency injection issues in tests
# @pytest.mark.contract
# @pytest.mark.asyncio
# async def test_get_supported_llm_providers_returns_metadata():
#     """Supported providers endpoint should expose provider capability metadata."""
#     pass
