"""Contract tests for prompt template update, deletion, and metadata endpoints."""

import uuid

import pytest
from httpx import AsyncClient, ASGITransport

from sqlalchemy import select

from tests.helper import create_test_app, create_test_user
from src.models.prompt_template import PromptTemplate


async def _login(client: AsyncClient, email: str, password: str) -> dict:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _create_template(client: AsyncClient, headers: dict, name: str = "Template") -> str:
    response = await client.post(
        "/api/v1/prompt-templates/create",
        json={
            "name": name,
            "description": "Contract test template",
            "system_prompt": "You ensure courteous, concise replies.",
            "user_prompt_template": "[Dieser Kommentar stammt von einem KI-ChatBot.] Reagiere auf {article_title}."
        },
        headers=headers
    )
    assert response.status_code == 201
    return response.json()["id"]


@pytest.mark.contract
@pytest.mark.asyncio
async def test_patch_prompt_template_success():
    app, db_session = await create_test_app()
    email, password = await create_test_user(app, db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _login(client, email, password)
        template_id = await _create_template(client, headers)

        patch_response = await client.patch(
            f"/api/v1/prompt-templates/{template_id}",
            json={
                "description": "Updated description",
                "is_active": False
            },
            headers=headers
        )
        assert patch_response.status_code == 200
        payload = patch_response.json()
        assert payload["description"] == "Updated description"
        assert payload["is_active"] is False


@pytest.mark.contract
@pytest.mark.asyncio
async def test_delete_prompt_template_success():
    app, db_session = await create_test_app()
    email, password = await create_test_user(app, db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _login(client, email, password)
        template_id = await _create_template(client, headers, name="DeleteTemplate")

        delete_response = await client.delete(
            f"/api/v1/prompt-templates/{template_id}",
            headers=headers
        )
        assert delete_response.status_code == 204

        list_response = await client.get(
            "/api/v1/prompt-templates/index",
            headers=headers
        )
        assert all(item["id"] != template_id for item in list_response.json())

        async with db_session() as session:
            result = await session.execute(
                select(PromptTemplate).where(PromptTemplate.id == uuid.UUID(template_id))
            )
            template = result.scalar_one_or_none()

            assert template is not None
            assert template.is_active is False


@pytest.mark.contract
@pytest.mark.asyncio
async def test_get_placeholders_returns_supported_metadata():
    app, db_session = await create_test_app()
    email, password = await create_test_user(app, db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _login(client, email, password)

        response = await client.get(
            "/api/v1/prompt-templates/placeholders",
            headers=headers
        )
        assert response.status_code == 200
        payload = response.json()
        assert "items" in payload
        assert any(item["name"] == "article_title" for item in payload["items"])


@pytest.mark.contract
@pytest.mark.asyncio
async def test_prompt_template_write_requires_authentication():
    app, db_session = await create_test_app()
    email, password = await create_test_user(app, db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client_auth:
        headers = await _login(client_auth, email, password)
        template_id = await _create_template(client_auth, headers, name="UnauthorizedCheck")

    async with AsyncClient(transport=transport, base_url="http://test") as client_unauth:
        response_patch = await client_unauth.patch(
            f"/api/v1/prompt-templates/{template_id}",
            json={"description": "No auth"}
        )
        assert response_patch.status_code == 401

        response_delete = await client_unauth.delete(
            f"/api/v1/prompt-templates/{template_id}"
        )
        assert response_delete.status_code == 401

        response_placeholders = await client_unauth.get("/api/v1/prompt-templates/placeholders")
        assert response_placeholders.status_code == 200
