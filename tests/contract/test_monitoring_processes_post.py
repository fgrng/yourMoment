"""Contract tests for monitoring process creation, listing, and deletion."""

import uuid

import pytest
from httpx import AsyncClient, ASGITransport

from sqlalchemy import select

from tests.helper import create_test_app, create_test_user
from src.models.monitoring_process import MonitoringProcess


async def _authenticate(client: AsyncClient, email: str, password: str) -> dict:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password}
    )
    assert response.status_code == 200
    data = response.json()
    return {"Authorization": f"Bearer {data['access_token']}"}


async def _create_prompt_template(client: AsyncClient, headers: dict) -> str:
    response = await client.post(
        "/api/v1/prompt-templates/create",
        json={
            "name": "Monitoring Template",
            "description": "Used in contract tests",
            "system_prompt": "You help draft insightful comments.",
            "user_prompt_template": "[Dieser Kommentar stammt von einem KI-ChatBot.] Bitte kommentiere {article_title}."
        },
        headers=headers
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _create_credentials(client: AsyncClient, headers: dict, suffix: str = "1") -> str:
    response = await client.post(
        "/api/v1/mymoment-credentials/create",
        json={
            "name": f"Contract Credential {suffix}",
            "username": f"contract_user_{suffix}",
            "password": "StrongPassword123!"
        },
        headers=headers
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _create_llm_provider(client: AsyncClient, headers: dict) -> str:
    response = await client.post(
        "/api/v1/llm-providers/create",
        json={
            "provider_name": "openai",
            "api_key": "sk-contract-test",
            "model_name": "gpt-4o-mini"
        },
        headers=headers
    )
    assert response.status_code == 201
    return response.json()["id"]


@pytest.mark.contract
@pytest.mark.asyncio
async def test_monitoring_process_create_success():
    app, db_session = await create_test_app()
    email, password = await create_test_user(app, db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _authenticate(client, email, password)
        llm_provider_id = await _create_llm_provider(client, headers)
        prompt_id = await _create_prompt_template(client, headers)
        credential_id = await _create_credentials(client, headers)

        request_body = {
            "name": "Contract Monitoring",
            "description": "Ensures monitoring create endpoint works",
            "max_duration_minutes": 45,
            "llm_provider_id": llm_provider_id,
            "target_filters": {"categories": [1], "tabs": ["alle"]},
            "prompt_template_ids": [prompt_id],
            "mymoment_login_ids": [credential_id]
        }

        response = await client.post(
            "/api/v1/monitoring-processes/create",
            json=request_body,
            headers=headers
        )
        assert response.status_code == 201
        payload = response.json()
        assert payload["name"] == request_body["name"]
        assert payload["llm_provider_id"] == llm_provider_id
        assert payload["prompt_template_ids"] == [prompt_id]
        assert payload["mymoment_login_ids"] == [credential_id]


@pytest.mark.contract
@pytest.mark.asyncio
async def test_monitoring_process_index_returns_created_items():
    app, db_session = await create_test_app()
    email, password = await create_test_user(app, db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _authenticate(client, email, password)
        llm_provider_id = await _create_llm_provider(client, headers)
        prompt_id = await _create_prompt_template(client, headers)
        credential_id = await _create_credentials(client, headers)

        create_response = await client.post(
            "/api/v1/monitoring-processes/create",
            json={
                "name": "Index Monitoring",
                "max_duration_minutes": 30,
                "llm_provider_id": llm_provider_id,
                "prompt_template_ids": [prompt_id],
                "mymoment_login_ids": [credential_id]
            },
            headers=headers
        )
        assert create_response.status_code == 201

        list_response = await client.get(
            "/api/v1/monitoring-processes/index",
            headers=headers
        )
        assert list_response.status_code == 200
        items = list_response.json()
        assert isinstance(items, list)
        assert any(item["name"] == "Index Monitoring" for item in items)


@pytest.mark.contract
@pytest.mark.asyncio
async def test_monitoring_process_delete_success():
    app, db_session = await create_test_app()
    email, password = await create_test_user(app, db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _authenticate(client, email, password)
        llm_provider_id = await _create_llm_provider(client, headers)
        prompt_id = await _create_prompt_template(client, headers)
        credential_id = await _create_credentials(client, headers)

        create_response = await client.post(
            "/api/v1/monitoring-processes/create",
            json={
                "name": "Delete Monitoring",
                "max_duration_minutes": 25,
                "llm_provider_id": llm_provider_id,
                "prompt_template_ids": [prompt_id],
                "mymoment_login_ids": [credential_id]
            },
            headers=headers
        )
        process_id = create_response.json()["id"]

        delete_response = await client.delete(
            f"/api/v1/monitoring-processes/{process_id}",
            headers=headers
        )
        assert delete_response.status_code == 204

        list_response = await client.get(
            "/api/v1/monitoring-processes/index",
            headers=headers
        )
        assert all(item["id"] != process_id for item in list_response.json())

        async with db_session() as session:
            result = await session.execute(
                select(MonitoringProcess).where(MonitoringProcess.id == uuid.UUID(process_id))
            )
            process = result.scalar_one_or_none()

            assert process is not None
            assert process.is_active is False


@pytest.mark.contract
@pytest.mark.asyncio
async def test_monitoring_process_create_requires_authentication():
    app, _ = await create_test_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/monitoring-processes/create",
            json={
                "name": "Unauthenticated",
                "max_duration_minutes": 30,
                "llm_provider_id": str(uuid.uuid4()),
                "prompt_template_ids": [str(uuid.uuid4())],
                "mymoment_login_ids": [str(uuid.uuid4())]
            }
        )
        assert response.status_code == 401
