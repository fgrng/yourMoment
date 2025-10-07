"""
Integration tests for prompt template management workflows.

These tests exercise the live FastAPI app to ensure prompt template endpoints
support the expected user scenarios (creation, listing, update, isolation, and validation).
"""

import uuid

import pytest
from httpx import AsyncClient, ASGITransport

from tests.helper import create_test_app, create_test_user


@pytest.mark.integration
@pytest.mark.asyncio
async def test_prompt_template_management_flow():
    """End-to-end flow: create, update, list, and delete a user template."""
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

        create_payload = {
            "name": "Scenario Template",
            "description": "Initial description",
            "system_prompt": "You provide short, thoughtful comments.",
            "user_prompt_template": "[Dieser Kommentar stammt von einem KI-ChatBot.] React to {article_title}."
        }

        create_response = await client.post(
            "/api/v1/prompt-templates/create",
            json=create_payload,
            headers=headers
        )
        assert create_response.status_code == 201
        template = create_response.json()
        template_id = template["id"]
        uuid.UUID(template_id)

        update_response = await client.patch(
            f"/api/v1/prompt-templates/{template_id}",
            json={"description": "Updated description"},
            headers=headers
        )
        assert update_response.status_code == 200
        assert update_response.json()["description"] == "Updated description"

        list_response = await client.get(
            "/api/v1/prompt-templates/index?category=USER",
            headers=headers
        )
        assert list_response.status_code == 200
        user_templates = list_response.json()
        assert any(item["id"] == template_id and item["description"] == "Updated description" for item in user_templates)

        delete_response = await client.delete(
            f"/api/v1/prompt-templates/{template_id}",
            headers=headers
        )
        assert delete_response.status_code == 204

        post_delete_response = await client.get(
            "/api/v1/prompt-templates/index?category=USER",
            headers=headers
        )
        remaining_user_templates = post_delete_response.json()
        assert all(item["id"] != template_id for item in remaining_user_templates)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_prompt_template_user_isolation():
    """Each user should only see their own USER templates when listing."""
    app, db_session = await create_test_app()
    email1, password1 = await create_test_user(app, db_session)
    email2, password2 = await create_test_user(app, db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login1 = await client.post(
            "/api/v1/auth/login",
            json={"email": email1, "password": password1}
        )
        token1 = login1.json()["access_token"]
        headers1 = {"Authorization": f"Bearer {token1}"}

        login2 = await client.post(
            "/api/v1/auth/login",
            json={"email": email2, "password": password2}
        )
        token2 = login2.json()["access_token"]
        headers2 = {"Authorization": f"Bearer {token2}"}

        await client.post(
            "/api/v1/prompt-templates/create",
            json={
                "name": "User One Template",
                "system_prompt": "Provide helpful guidance with context.",
                "user_prompt_template": "[Dieser Kommentar stammt von einem KI-ChatBot.] Bitte reagiere auf {article_title}."
            },
            headers=headers1
        )

        await client.post(
            "/api/v1/prompt-templates/create",
            json={
                "name": "User Two Template",
                "system_prompt": "Offer thoughtful commentary referencing details.",
                "user_prompt_template": "[Dieser Kommentar stammt von einem KI-ChatBot.] Teile Gedanken zu {article_title}."
            },
            headers=headers2
        )

        response1 = await client.get(
            "/api/v1/prompt-templates/index?category=USER",
            headers=headers1
        )
        templates1 = response1.json()
        assert len(templates1) == 1
        assert templates1[0]["name"] == "User One Template"

        response2 = await client.get(
            "/api/v1/prompt-templates/index?category=USER",
            headers=headers2
        )
        templates2 = response2.json()
        assert len(templates2) == 1
        assert templates2[0]["name"] == "User Two Template"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_prompt_template_validation_errors():
    """Invalid payloads should surface validation errors."""
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

        invalid_payload = {
            "name": "",
            "system_prompt": "",
            "user_prompt_template": ""
        }

        response = await client.post(
            "/api/v1/prompt-templates/create",
            json=invalid_payload,
            headers=headers
        )
        assert response.status_code == 422
        assert "detail" in response.json()

        # Attempt to update with invalid data
        create_response = await client.post(
            "/api/v1/prompt-templates/create",
            json={
                "name": "Valid Template",
                "system_prompt": "Provide structured feedback focusing on clarity.",
                "user_prompt_template": "[Dieser Kommentar stammt von einem KI-ChatBot.] Reflektiere über {article_title}."
            },
            headers=headers
        )
        template_id = create_response.json()["id"]

        bad_update = await client.patch(
            f"/api/v1/prompt-templates/{template_id}",
            json={"name": ""},
            headers=headers
        )
        assert bad_update.status_code == 422
        assert "detail" in bad_update.json()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_prompt_template_unauthorized_access():
    """Prompt template endpoints must require authentication."""
    app, _ = await create_test_app()

    payload = {
        "name": "Unauthorized",
        "system_prompt": "System",
        "user_prompt_template": "[Dieser Kommentar stammt von einem KI-ChatBot.]"
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        post_response = await client.post(
            "/api/v1/prompt-templates/create",
            json=payload
        )
        assert post_response.status_code == 401

        list_response = await client.get("/api/v1/prompt-templates/index")
        assert list_response.status_code == 401

        delete_response = await client.delete("/api/v1/prompt-templates/00000000-0000-0000-0000-000000000000")
        assert delete_response.status_code == 401
