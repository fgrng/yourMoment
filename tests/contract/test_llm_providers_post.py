"""
Contract tests for POST /llm-providers/create endpoint.

Verifies request validation, response schema, and authorization behaviour.
"""

import uuid

import pytest
from httpx import AsyncClient, ASGITransport

from tests.helper import create_test_app, create_test_user


@pytest.mark.contract
@pytest.mark.asyncio
async def test_create_llm_provider_success():
    """Valid payload creates a provider and returns response schema."""
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

        payload = {
            "provider_name": "openai",
            "api_key": "sk-test-openai",
            "model_name": "gpt-4o-mini",
            "max_tokens": 900,
            "temperature": 0.4
        }

        response = await client.post(
            "/api/v1/llm-providers/create",
            json=payload,
            headers=headers
        )

        assert response.status_code == 201
        data = response.json()

        uuid.UUID(data["id"])
        assert data["provider_name"] == payload["provider_name"]
        assert data["model_name"] == payload["model_name"]
        assert data["max_tokens"] == payload["max_tokens"]
        assert data["temperature"] == payload["temperature"]
        assert data["is_active"] is True
        assert isinstance(data["created_at"], str)


@pytest.mark.contract
@pytest.mark.asyncio
async def test_create_llm_provider_minimal_payload():
    """Optional fields can be omitted and default to null."""
    app, db_session = await create_test_app()
    email, password = await create_test_user(app, db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password}
        )
        headers = {"Authorization": f"Bearer {login_response.json()['access_token']}"}

        payload = {
            "provider_name": "mistral",
            "api_key": "sk-test-mistral",
            "model_name": "mistral-large-latest"
        }

        response = await client.post(
            "/api/v1/llm-providers/create",
            json=payload,
            headers=headers
        )

        assert response.status_code == 201
        data = response.json()
        assert data["max_tokens"] is None
        assert data["temperature"] is None


@pytest.mark.contract
@pytest.mark.asyncio
async def test_create_llm_provider_missing_required_fields():
    """Missing required fields produce validation errors (422)."""
    app, db_session = await create_test_app()
    email, password = await create_test_user(app, db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password}
        )
        headers = {"Authorization": f"Bearer {login_response.json()['access_token']}"}

        invalid_payloads = [
            {},
            {"provider_name": "openai"},
            {"api_key": "sk"},
            {"model_name": "gpt-4o"},
            {"provider_name": "openai", "api_key": "sk"},
            {"provider_name": "openai", "model_name": "gpt-4"},
            {"api_key": "sk", "model_name": "gpt-4"}
        ]

        for payload in invalid_payloads:
            response = await client.post(
                "/api/v1/llm-providers/create",
                json=payload,
                headers=headers
            )
            assert response.status_code == 422
            assert "detail" in response.json()


@pytest.mark.contract
@pytest.mark.asyncio
async def test_create_llm_provider_provider_name_enum():
    """Provider name must match the allowed enum pattern."""
    app, db_session = await create_test_app()
    email, password = await create_test_user(app, db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password}
        )
        headers = {"Authorization": f"Bearer {login_response.json()['access_token']}"}

        valid_providers = ["openai", "mistral"]
        for provider in valid_providers:
            response = await client.post(
                "/api/v1/llm-providers/create",
                json={
                    "provider_name": provider,
                    "api_key": "sk-test",
                    "model_name": "test-model"
                },
                headers=headers
            )
            assert response.status_code == 201, f"Failed to create {provider}: {response.json()}"

        invalid_providers = ["huggingface", "cohere", "invalid", "", "OpenAI"]
        for provider in invalid_providers:
            response = await client.post(
                "/api/v1/llm-providers/create",
                json={
                    "provider_name": provider,
                    "api_key": "sk-test",
                    "model_name": "test-model"
                },
                headers=headers
            )
            assert response.status_code == 422
            assert "detail" in response.json()


@pytest.mark.contract
@pytest.mark.asyncio
async def test_create_llm_provider_optional_field_validation():
    """Optional numeric fields must stay within bounds."""
    app, db_session = await create_test_app()
    email, password = await create_test_user(app, db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password}
        )
        headers = {"Authorization": f"Bearer {login_response.json()['access_token']}"}

        bad_payloads = [
            {"max_tokens": 0},
            {"max_tokens": -5},
            {"temperature": -0.1},
            {"temperature": 1.5}
        ]

        for bad in bad_payloads:
            body = {
                "provider_name": "openai",
                "api_key": "sk",
                "model_name": "gpt-4"
            }
            body.update(bad)
            response = await client.post(
                "/api/v1/llm-providers/create",
                json=body,
                headers=headers
            )
            assert response.status_code == 422


@pytest.mark.contract
@pytest.mark.asyncio
async def test_create_llm_provider_unauthorized():
    """Missing Authorization header returns 401."""
    app, _ = await create_test_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/llm-providers/create",
            json={
                "provider_name": "openai",
                "api_key": "sk",
                "model_name": "gpt-4"
            }
        )
        assert response.status_code == 401
        assert "detail" in response.json()


@pytest.mark.contract
@pytest.mark.asyncio
async def test_create_llm_provider_invalid_json():
    """Malformed JSON body returns 400."""
    app, db_session = await create_test_app()
    email, password = await create_test_user(app, db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password}
        )
        token = login_response.json()["access_token"]
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        response = await client.post(
            "/api/v1/llm-providers/create",
            content="{invalid json}",
            headers=headers
        )
        assert response.status_code == 400
        assert "detail" in response.json()
