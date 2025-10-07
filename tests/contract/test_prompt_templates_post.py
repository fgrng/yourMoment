"""
Contract tests for POST /prompt-templates/create endpoint.

Validates schema, validation errors, and authorization behaviour.
"""

import uuid

import pytest
from httpx import AsyncClient, ASGITransport

from tests.helper import create_test_app, create_test_user


@pytest.mark.contract
@pytest.mark.asyncio
async def test_create_prompt_template_success():
    """Creating a prompt template should return 201 with response payload."""
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
            "name": "Insightful Commenter",
            "description": "Provides balanced, respectful comments",
            "system_prompt": "You are an empathetic commentator who references facts.",
            "user_prompt_template": "[Dieser Kommentar stammt von einem KI-ChatBot.] Share insights on {article_title}."
        }

        response = await client.post(
            "/api/v1/prompt-templates/create",
            json=payload,
            headers=headers
        )

        assert response.status_code == 201
        data = response.json()

        assert data["name"] == payload["name"]
        assert data["description"] == payload["description"]
        assert data["system_prompt"] == payload["system_prompt"]
        assert data["user_prompt_template"] == payload["user_prompt_template"]
        assert data["category"] == "USER"
        assert data["is_active"] is True
        assert isinstance(data["created_at"], str)
        uuid.UUID(data["id"])


@pytest.mark.contract
@pytest.mark.asyncio
async def test_create_prompt_template_minimal_payload():
    """Description is optional and should default to null when omitted."""
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
            "name": "Minimal Template",
            "system_prompt": "Keep answers short.",
            "user_prompt_template": "[Dieser Kommentar stammt von einem KI-ChatBot.]"
        }

        response = await client.post(
            "/api/v1/prompt-templates/create",
            json=payload,
            headers=headers
        )

        assert response.status_code == 201
        data = response.json()
        assert data["description"] is None
        assert data["name"] == payload["name"]


@pytest.mark.contract
@pytest.mark.asyncio
async def test_create_prompt_template_no_authorization():
    """Missing Authorization header should return 401."""
    app, _ = await create_test_app()

    payload = {
        "name": "Unauthorized",
        "system_prompt": "System",
        "user_prompt_template": "[Dieser Kommentar stammt von einem KI-ChatBot.]"
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/prompt-templates/create", json=payload)
        assert response.status_code == 401
        assert "detail" in response.json()


@pytest.mark.contract
@pytest.mark.asyncio
async def test_create_prompt_template_invalid_token():
    """Invalid JWT should return 401 Unauthorized."""
    app, _ = await create_test_app()

    payload = {
        "name": "Invalid Token",
        "system_prompt": "System",
        "user_prompt_template": "[Dieser Kommentar stammt von einem KI-ChatBot.]"
    }

    headers = {"Authorization": "Bearer invalid.jwt.token"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/prompt-templates/create",
            json=payload,
            headers=headers
        )
        assert response.status_code == 401
        assert "detail" in response.json()


@pytest.mark.contract
@pytest.mark.asyncio
async def test_create_prompt_template_missing_required_fields():
    """Missing required fields should fail validation with 422."""
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

        invalid_payloads = [
            {},
            {"system_prompt": "System"},
            {"user_prompt_template": "Prompt"},
            {
                "name": "",
                "system_prompt": "System",
                "user_prompt_template": "Prompt"
            }
        ]

        for payload in invalid_payloads:
            response = await client.post(
                "/api/v1/prompt-templates/create",
                json=payload,
                headers=headers
            )
            assert response.status_code == 422
            assert "detail" in response.json()


@pytest.mark.contract
@pytest.mark.asyncio
async def test_create_prompt_template_field_length_validation():
    """Field length violations should yield 422 responses."""
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
            "name": "x" * 101,
            "system_prompt": "System prompt",
            "user_prompt_template": "[Dieser Kommentar stammt von einem KI-ChatBot.]"
        }

        response = await client.post(
            "/api/v1/prompt-templates/create",
            json=payload,
            headers=headers
        )
        assert response.status_code == 422
        assert "detail" in response.json()

        payload = {
            "name": "Valid Name",
            "description": "x" * 501,
            "system_prompt": "System",
            "user_prompt_template": "[Dieser Kommentar stammt von einem KI-ChatBot.]"
        }

        response = await client.post(
            "/api/v1/prompt-templates/create",
            json=payload,
            headers=headers
        )
        assert response.status_code == 422
        assert "detail" in response.json()
