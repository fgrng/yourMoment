"""Contract tests verifying cross-user ownership enforcement for sensitive resources."""

import uuid

import pytest
from httpx import AsyncClient, ASGITransport

from tests.helper import create_test_app, create_test_user
from src.models.monitoring_process import MonitoringProcess


async def _login(client: AsyncClient, email: str, password: str) -> tuple[dict, uuid.UUID]:
    """Authenticate and return auth headers plus the user ID."""
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password}
    )
    assert response.status_code == 200
    data = response.json()
    return {"Authorization": f"Bearer {data['access_token']}"}, uuid.UUID(data["user"]["id"])


@pytest.mark.contract
@pytest.mark.asyncio
async def test_prompt_template_access_isolated_by_user():
    app, db_session = await create_test_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        owner_email, owner_password = await create_test_user(app, db_session)
        other_email, other_password = await create_test_user(app, db_session)

        owner_headers, _ = await _login(client, owner_email, owner_password)
        other_headers, _ = await _login(client, other_email, other_password)

        template_payload = {
            "name": "Owner Template",
            "description": "Used for ownership checks",
            "system_prompt": "You are a helpful assistant providing concise answers.",
            "user_prompt_template": "[Dieser Kommentar stammt von einem KI-ChatBot.] {article_title}"
        }

        create_response = await client.post(
            "/api/v1/prompt-templates/create",
            json=template_payload,
            headers=owner_headers
        )
        assert create_response.status_code == 201
        template_id = create_response.json()["id"]

        forbidden_get = await client.get(
            f"/api/v1/prompt-templates/{template_id}",
            headers=other_headers
        )
        assert forbidden_get.status_code == 404
        error_payload = forbidden_get.json()["detail"]
        assert error_payload["error"] == "prompt_template_not_found"

        forbidden_update = await client.patch(
            f"/api/v1/prompt-templates/{template_id}",
            json={"name": "Hacked"},
            headers=other_headers
        )
        assert forbidden_update.status_code == 404
        assert forbidden_update.json()["detail"]["error"] == "prompt_template_not_found"


@pytest.mark.contract
@pytest.mark.asyncio
async def test_mymoment_credentials_hidden_from_other_users():
    app, db_session = await create_test_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        owner_email, owner_password = await create_test_user(app, db_session)
        other_email, other_password = await create_test_user(app, db_session)

        owner_headers, _ = await _login(client, owner_email, owner_password)
        other_headers, _ = await _login(client, other_email, other_password)

        creds_payload = {
            "username": "owner_account",
            "password": "super-secret",
            "name": "Primary Login"
        }

        create_response = await client.post(
            "/api/v1/mymoment-credentials/create",
            json=creds_payload,
            headers=owner_headers
        )
        assert create_response.status_code == 201
        credentials_id = create_response.json()["id"]

        forbidden_get = await client.get(
            f"/api/v1/mymoment-credentials/{credentials_id}",
            headers=other_headers
        )
        assert forbidden_get.status_code == 404
        assert forbidden_get.json()["detail"]["error"] == "mymoment_credentials_not_found"

        forbidden_patch = await client.patch(
            f"/api/v1/mymoment-credentials/{credentials_id}",
            json=creds_payload,
            headers=other_headers
        )
        assert forbidden_patch.status_code == 404
        assert forbidden_patch.json()["detail"]["error"] == "mymoment_credentials_not_found"


@pytest.mark.contract
@pytest.mark.asyncio
async def test_llm_provider_operations_require_ownership():
    app, db_session = await create_test_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        owner_email, owner_password = await create_test_user(app, db_session)
        other_email, other_password = await create_test_user(app, db_session)

        owner_headers, _ = await _login(client, owner_email, owner_password)
        other_headers, _ = await _login(client, other_email, other_password)

        provider_payload = {
            "provider_name": "openai",
            "api_key": "sk-test-key",
            "model_name": "gpt-5-nano"
        }

        create_response = await client.post(
            "/api/v1/llm-providers/create",
            json=provider_payload,
            headers=owner_headers
        )
        assert create_response.status_code == 201
        provider_id = create_response.json()["id"]

        forbidden_get = await client.get(
            f"/api/v1/llm-providers/{provider_id}",
            headers=other_headers
        )
        assert forbidden_get.status_code == 404

        forbidden_delete = await client.delete(
            f"/api/v1/llm-providers/{provider_id}",
            headers=other_headers
        )
        assert forbidden_delete.status_code == 404


@pytest.mark.contract
@pytest.mark.asyncio
async def test_monitoring_processes_are_not_visible_to_other_users():
    app, db_session = await create_test_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        owner_email, owner_password = await create_test_user(app, db_session)
        other_email, other_password = await create_test_user(app, db_session)

        owner_headers, owner_id = await _login(client, owner_email, owner_password)
        other_headers, _ = await _login(client, other_email, other_password)

        async with db_session() as session:
            process = MonitoringProcess(
                user_id=owner_id,
                name="Owner Monitoring",
                description="Ensures ownership enforcement",
                max_duration_minutes=60,
                status="created"
            )
            session.add(process)
            await session.commit()
            await session.refresh(process)
            process_id = process.id

        forbidden_get = await client.get(
            f"/api/v1/monitoring-processes/{process_id}",
            headers=other_headers
        )
        assert forbidden_get.status_code == 404

        forbidden_stop = await client.post(
            f"/api/v1/monitoring-processes/{process_id}/stop",
            headers=other_headers
        )
        assert forbidden_stop.status_code == 404
