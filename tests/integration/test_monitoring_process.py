"""
Integration tests for monitoring process creation (T025).

Tests the monitoring process creation and management workflow as described
in Scenario 5 of the quickstart guide. These tests MUST FAIL until models,
services, and API endpoints are implemented (TDD requirement).
"""

import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import status

from src.main import create_app


app = create_app()


@pytest.mark.integration
@pytest.mark.celery
@pytest.mark.web_scraping
@pytest.mark.asyncio
async def test_monitoring_process_complete_creation_flow():
    """
    Test complete monitoring process creation flow from quickstart Scenario 5.

    This test validates:
    - User can create monitoring processes
    - Processes can be associated with multiple myMoment logins
    - Processes can use prompt templates
    - Process configuration is validated
    - Processes have duration limits
    """
    # Setup user
    user_data = {
        "email": "monitor_user@example.com",
        "password": "SecurePassword123!"
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Setup: Register and login user
        await client.post("/api/v1/auth/register", json=user_data)
        login_response = await client.post("/api/v1/auth/login", json=user_data)
        token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Prerequisites: Create myMoment credentials and prompt template
        credentials1 = {
            "username": "monitor1@mymoment.com",
            "password": "MonitorPassword1"
        }
        credentials2 = {
            "username": "monitor2@mymoment.com",
            "password": "MonitorPassword2"
        }

        creds1_response = await client.post(
            "/api/v1/mymoment-credentials",
            json=credentials1,
            headers=headers
        )
        creds2_response = await client.post(
            "/api/v1/mymoment-credentials",
            json=credentials2,
            headers=headers
        )

        creds1_id = creds1_response.json()["id"]
        creds2_id = creds2_response.json()["id"]

        # Create prompt template
        template_data = {
            "name": "Monitor Template",
            "system_prompt": "You are a helpful commenter",
            "user_prompt_template": "Comment on: {article_title}"
        }

        template_response = await client.post(
            "/api/v1/prompt-templates",
            json=template_data,
            headers=headers
        )

        template_id = template_response.json()["id"]

        # Step 1: Create monitoring process
        process_data = {
            "name": "Tech Article Monitor",
            "description": "Monitor technology articles",
            "mymoment_login_ids": [creds1_id, creds2_id],  # Multi-login support
            "prompt_template_id": template_id,
            "filter_criteria": {
                "categories": [1, 2],  # Technology categories
                "keywords": ["AI", "Python", "Web Development"]
            },
            "monitoring_interval_minutes": 15,
            "max_duration_hours": 24,
            "is_active": True
        }

        process_response = await client.post(
            "/api/v1/monitoring-processes",
            json=process_data,
            headers=headers
        )

        assert process_response.status_code == status.HTTP_201_CREATED
        process = process_response.json()

        # Validate response schema
        assert "id" in process
        assert process["name"] == process_data["name"]
        assert process["description"] == process_data["description"]
        assert process["is_active"] is True
        assert process["is_running"] is False  # Not started yet
        assert process["monitoring_interval_minutes"] == 15
        assert process["max_duration_hours"] == 24
        assert "created_at" in process
        assert "updated_at" in process

        process_id = process["id"]

        # Step 2: Start monitoring process
        start_response = await client.post(
            f"/api/v1/monitoring-processes/{process_id}/start",
            headers=headers
        )

        assert start_response.status_code == status.HTTP_200_OK
        start_data = start_response.json()

        assert start_data["is_running"] is True
        assert "started_at" in start_data
        assert start_data["status"] == "running"

        # Step 3: Check process status
        status_response = await client.get(
            f"/api/v1/monitoring-processes/{process_id}",
            headers=headers
        )

        if status_response.status_code == status.HTTP_200_OK:
            status_data = status_response.json()
            assert status_data["is_running"] is True

        # Step 4: Stop monitoring process
        stop_response = await client.post(
            f"/api/v1/monitoring-processes/{process_id}/stop",
            headers=headers
        )

        assert stop_response.status_code == status.HTTP_200_OK
        stop_data = stop_response.json()

        assert stop_data["is_running"] is False
        assert "stopped_at" in stop_data
        assert stop_data["status"] == "stopped"


@pytest.mark.integration
@pytest.mark.celery
@pytest.mark.asyncio
async def test_monitoring_process_multi_login_support():
    """
    Test that monitoring processes support multiple myMoment logins.

    This validates the core multi-login architecture requirement.
    """
    # Setup user
    user_data = {
        "email": "multilogin@example.com",
        "password": "Password123!"
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/v1/auth/register", json=user_data)
        login_response = await client.post("/api/v1/auth/login", json=user_data)
        token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Create multiple myMoment credentials
        login_credentials = []
        login_ids = []

        for i in range(3):
            creds = {
                "username": f"multilogin{i}@mymoment.com",
                "password": f"Password{i}123"
            }
            response = await client.post(
                "/api/v1/mymoment-credentials",
                json=creds,
                headers=headers
            )
            login_credentials.append(creds)
            login_ids.append(response.json()["id"])

        # Create monitoring process with all logins
        process_data = {
            "name": "Multi-Login Process",
            "mymoment_login_ids": login_ids,  # All 3 logins
            "monitoring_interval_minutes": 30,
            "max_duration_hours": 12
        }

        process_response = await client.post(
            "/api/v1/monitoring-processes",
            json=process_data,
            headers=headers
        )

        assert process_response.status_code == status.HTTP_201_CREATED

        # TODO: When background tasks are implemented, verify:
        # 1. Process creates separate sessions for each login
        # 2. Each login generates separate comments
        # 3. Failed logins don't affect others
        # 4. Session isolation is maintained


@pytest.mark.integration
@pytest.mark.celery
@pytest.mark.asyncio
async def test_monitoring_process_duration_limits():
    """Test monitoring process duration limit enforcement."""
    # Setup user
    user_data = {
        "email": "duration@example.com",
        "password": "Password123!"
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/v1/auth/register", json=user_data)
        login_response = await client.post("/api/v1/auth/login", json=user_data)
        token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Create process with short duration (1 hour)
        process_data = {
            "name": "Short Duration Process",
            "monitoring_interval_minutes": 5,
            "max_duration_hours": 1  # 1 hour limit
        }

        process_response = await client.post(
            "/api/v1/monitoring-processes",
            json=process_data,
            headers=headers
        )

        assert process_response.status_code == status.HTTP_201_CREATED
        process_id = process_response.json()["id"]

        # TODO: When background tasks are implemented, verify:
        # 1. Process automatically stops after max duration
        # 2. Immediate termination when duration exceeded
        # 3. Proper cleanup of sessions and resources
        # 4. Status updates reflect duration-based termination

        # For now, validate the duration limit is stored
        get_response = await client.get(
            f"/api/v1/monitoring-processes/{process_id}",
            headers=headers
        )

        if get_response.status_code == status.HTTP_200_OK:
            process_data = get_response.json()
            assert process_data["max_duration_hours"] == 1


@pytest.mark.integration
@pytest.mark.celery
@pytest.mark.asyncio
async def test_monitoring_process_validation():
    """Test monitoring process input validation."""
    # Setup user
    user_data = {
        "email": "validation@example.com",
        "password": "Password123!"
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/v1/auth/register", json=user_data)
        login_response = await client.post("/api/v1/auth/login", json=user_data)
        token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Test invalid process data
        invalid_processes = [
            {},  # Missing required fields
            {"name": ""},  # Empty name
            {"name": "Test", "max_duration_hours": 0},  # Invalid duration
            {"name": "Test", "monitoring_interval_minutes": 0},  # Invalid interval
            {"name": "Test", "mymoment_login_ids": []},  # Empty login list
        ]

        for invalid_process in invalid_processes:
            response = await client.post(
                "/api/v1/monitoring-processes",
                json=invalid_process,
                headers=headers
            )
            assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.integration
@pytest.mark.celery
@pytest.mark.asyncio
async def test_monitoring_process_user_isolation():
    """Test that monitoring processes are isolated per user."""
    # Create two users
    user1_data = {
        "email": "user1@example.com",
        "password": "Password123!"
    }
    user2_data = {
        "email": "user2@example.com",
        "password": "Password123!"
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Register and login both users
        await client.post("/api/v1/auth/register", json=user1_data)
        await client.post("/api/v1/auth/register", json=user2_data)

        login1_response = await client.post("/api/v1/auth/login", json=user1_data)
        login2_response = await client.post("/api/v1/auth/login", json=user2_data)

        token1 = login1_response.json()["access_token"]
        token2 = login2_response.json()["access_token"]

        headers1 = {"Authorization": f"Bearer {token1}"}
        headers2 = {"Authorization": f"Bearer {token2}"}

        # User 1 creates monitoring process
        user1_process = {
            "name": "User 1 Process",
            "monitoring_interval_minutes": 15,
            "max_duration_hours": 12
        }

        await client.post(
            "/api/v1/monitoring-processes",
            json=user1_process,
            headers=headers1
        )

        # User 2 creates monitoring process
        user2_process = {
            "name": "User 2 Process",
            "monitoring_interval_minutes": 30,
            "max_duration_hours": 24
        }

        await client.post(
            "/api/v1/monitoring-processes",
            json=user2_process,
            headers=headers2
        )

        # User 1 should only see their process
        user1_list_response = await client.get(
            "/api/v1/monitoring-processes",
            headers=headers1
        )

        if user1_list_response.status_code == status.HTTP_200_OK:
            user1_processes = user1_list_response.json()
            assert len(user1_processes) == 1
            assert user1_processes[0]["name"] == "User 1 Process"

        # User 2 should only see their process
        user2_list_response = await client.get(
            "/api/v1/monitoring-processes",
            headers=headers2
        )

        if user2_list_response.status_code == status.HTTP_200_OK:
            user2_processes = user2_list_response.json()
            assert len(user2_processes) == 1
            assert user2_processes[0]["name"] == "User 2 Process"


@pytest.mark.integration
@pytest.mark.celery
@pytest.mark.asyncio
async def test_monitoring_process_unauthorized_access():
    """Test that monitoring process endpoints require authentication."""
    process_data = {
        "name": "Test Process",
        "monitoring_interval_minutes": 15,
        "max_duration_hours": 12
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Test POST without authentication
        post_response = await client.post(
            "/api/v1/monitoring-processes",
            json=process_data
        )
        assert post_response.status_code == status.HTTP_401_UNAUTHORIZED

        # Test GET without authentication
        get_response = await client.get("/api/v1/monitoring-processes")
        assert get_response.status_code == status.HTTP_401_UNAUTHORIZED

        # Test start/stop without authentication
        start_response = await client.post(
            "/api/v1/monitoring-processes/fake-id/start"
        )
        assert start_response.status_code == status.HTTP_401_UNAUTHORIZED

        stop_response = await client.post(
            "/api/v1/monitoring-processes/fake-id/stop"
        )
        assert stop_response.status_code == status.HTTP_401_UNAUTHORIZED
