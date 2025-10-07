"""
Contract tests for GET /prompt-templates endpoints.

Validates listing behaviour, filtering, and authorization using the real FastAPI app.
"""

import uuid

import pytest
from httpx import AsyncClient, ASGITransport

from tests.helper import create_test_app, create_test_user


@pytest.mark.contract
@pytest.mark.asyncio
async def test_get_prompt_templates_index_success():
    """Authenticated user should receive list including their templates."""
    app, db_session = await create_test_app()
    email, password = await create_test_user(app, db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Login to obtain JWT
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password}
        )
        token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        templates_payloads = [
            {
                "name": "Tech Analyst",
                "description": "Expert commentary for technology pieces",
                "system_prompt": "You are a senior technology analyst who writes concise insights.",
                "user_prompt_template": "[Dieser Kommentar stammt von einem KI-ChatBot.] Analyze {article_title}."
            },
            {
                "name": "Education Coach",
                "description": "Supportive tone for education topics",
                "system_prompt": "You coach teachers with actionable advice.",
                "user_prompt_template": "[Dieser Kommentar stammt von einem KI-ChatBot.] Offer feedback on {article_title}."
            },
        ]

        created_ids = []
        for payload in templates_payloads:
            create_response = await client.post(
                "/api/v1/prompt-templates/create",
                json=payload,
                headers=headers
            )
            assert create_response.status_code == 201
            created_ids.append(create_response.json()["id"])

        response = await client.get("/api/v1/prompt-templates/index", headers=headers)

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")

        items = response.json()
        assert isinstance(items, list)

        user_templates = [item for item in items if item["id"] in created_ids]
        assert len(user_templates) == len(created_ids)

        for item in user_templates:
            assert item["category"] == "USER"
            assert item["is_active"] is True
            assert isinstance(item.get("created_at"), str)
            assert "system_prompt" in item
            assert "user_prompt_template" in item
            uuid.UUID(item["id"])


@pytest.mark.contract
@pytest.mark.asyncio
async def test_get_prompt_templates_index_empty_user_templates():
    """User with no custom templates should see zero USER templates."""
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

        response = await client.get(
            "/api/v1/prompt-templates/index?category=USER",
            headers=headers
        )

        assert response.status_code == 200
        items = response.json()
        assert isinstance(items, list)
        assert len(items) == 0  # No user templates yet


@pytest.mark.contract
@pytest.mark.asyncio
async def test_get_prompt_templates_index_category_filter():
    """Category filter USER should only return user-owned templates."""
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

        for idx in range(2):
            payload = {
                "name": f"Template {idx}",
                "system_prompt": "Provide thoughtful commentary.",
                "user_prompt_template": f"[Dieser Kommentar stammt von einem KI-ChatBot.] Comment {idx} on {{article_title}}."
            }
            create_response = await client.post(
                "/api/v1/prompt-templates/create",
                json=payload,
                headers=headers
            )
            assert create_response.status_code == 201

        response = await client.get(
            "/api/v1/prompt-templates/index?category=USER",
            headers=headers
        )

        assert response.status_code == 200
        items = response.json()
        assert len(items) == 2
        assert all(item["category"] == "USER" for item in items)


@pytest.mark.contract
@pytest.mark.asyncio
async def test_get_prompt_templates_index_limit_parameter():
    """Limit parameter should cap the number of returned templates."""
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

        for idx in range(3):
            payload = {
                "name": f"Limited Template {idx}",
                "system_prompt": "System prompt",
                "user_prompt_template": "[Dieser Kommentar stammt von einem KI-ChatBot.]",
            }
            create_response = await client.post(
                "/api/v1/prompt-templates/create",
                json=payload,
                headers=headers
            )
            assert create_response.status_code == 201

        response = await client.get(
            "/api/v1/prompt-templates/index?category=USER&limit=2",
            headers=headers
        )

        assert response.status_code == 200
        items = response.json()
        assert len(items) == 2


@pytest.mark.contract
@pytest.mark.asyncio
async def test_get_prompt_templates_index_no_authorization():
    """Requests without Authorization header should be rejected."""
    app, _ = await create_test_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/prompt-templates/index")
        assert response.status_code == 401
        assert "detail" in response.json()


@pytest.mark.contract
@pytest.mark.asyncio
async def test_get_prompt_templates_index_invalid_token():
    """Requests with invalid tokens should return 401."""
    app, _ = await create_test_app()

    headers = {"Authorization": "Bearer invalid.jwt.token"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/prompt-templates/index",
            headers=headers
        )
        assert response.status_code == 401
        assert "detail" in response.json()


@pytest.mark.contract
@pytest.mark.asyncio
async def test_get_prompt_templates_index_invalid_category():
    """Invalid category value should trigger 422 validation error."""
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

        response = await client.get(
            "/api/v1/prompt-templates/index?category=INVALID",
            headers=headers
        )

        assert response.status_code == 422
        error = response.json()
        assert "detail" in error
