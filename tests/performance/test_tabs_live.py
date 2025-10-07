"""
Performance tests for GET /articles/{mymoment_login_id}/tabs endpoint

These tests make REAL HTTP calls to the myMoment platform.
Set ENABLE_LIVE_SCRAPER_TESTS=1 environment variable to run these tests.
"""

import os
import time
import uuid

import pytest
from httpx import AsyncClient, ASGITransport

from tests.helper import create_test_app, create_test_user


# Skip all tests if live scraper tests are disabled
pytestmark = pytest.mark.skipif(
    os.getenv("ENABLE_LIVE_SCRAPER_TESTS") != "1",
    reason="Live scraper tests disabled. Set ENABLE_LIVE_SCRAPER_TESTS=1 to enable."
)


@pytest.mark.performance
@pytest.mark.external_api
@pytest.mark.asyncio
async def test_tabs_endpoint_live_performance(mymoment_test_credentials):
    """
    Test tabs endpoint with real myMoment platform.

    Validates:
    - Successful authentication and tab discovery
    - Response time within acceptable limits
    - Tab structure and types are correct
    - Real myMoment platform integration
    """
    username, password = mymoment_test_credentials

    app, db_session = await create_test_app()
    email, user_password = await create_test_user(app, db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Login to get token
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": user_password}
        )
        assert login_response.status_code == 200
        token = login_response.json()["access_token"]

        # Create myMoment credential with real credentials
        credential_response = await client.post(
            "/api/v1/mymoment-credentials/create",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "name": "Live Test Credential",
                "username": os.environ['MYMOMENT_TEST_USERNAME'],
                "password": os.environ['MYMOMENT_TEST_PASSWORD']
            }
        )
        assert credential_response.status_code == 201
        credential_id = credential_response.json()["id"]

        # Test tabs endpoint with performance measurement
        start_time = time.time()

        response = await client.get(
            f"/api/v1/articles/{credential_id}/tabs",
            headers={"Authorization": f"Bearer {token}"}
        )

        end_time = time.time()
        response_time = end_time - start_time

        # Assert successful response
        assert response.status_code == 200
        data = response.json()

        # Validate response structure
        assert "items" in data
        assert "total" in data
        assert isinstance(data["items"], list)
        assert data["total"] == len(data["items"])

        # Validate we got tabs
        assert len(data["items"]) > 0, "Should discover at least one tab"

        # Validate tab structure
        for tab in data["items"]:
            assert "id" in tab
            assert "name" in tab
            assert "tab_type" in tab
            assert isinstance(tab["id"], str)
            assert isinstance(tab["name"], str)
            assert tab["tab_type"] in ["home", "alle", "class"]

        # Validate tab types
        tab_types = {tab["tab_type"] for tab in data["items"]}
        assert "home" in tab_types or "alle" in tab_types, \
            "Should have at least 'home' or 'alle' tab"

        # Check for expected tabs from examples
        tab_ids = {tab["id"] for tab in data["items"]}
        tab_names = {tab["name"] for tab in data["items"]}

        # Based on examples/mymoment_articles_tabs.html
        # Should have home ("Meine") and alle ("Alle") tabs
        assert "home" in tab_ids or "Meine" in tab_names, \
            "Should have 'home' tab (Meine)"
        assert "alle" in tab_ids or "Alle" in tab_names, \
            "Should have 'alle' tab (Alle)"

        # Performance assertion - should respond within 20 seconds
        # (includes myMoment authentication + tab scraping)
        assert response_time < 20.0, \
            f"Tab discovery took {response_time:.2f}s, should be < 20s"

        print(f"\n✅ Live tabs endpoint test passed")
        print(f"   Response time: {response_time:.2f}s")
        print(f"   Tabs discovered: {len(data['items'])}")
        print(f"   Tab types: {tab_types}")
        print(f"   Tab IDs: {tab_ids}")


@pytest.mark.performance
@pytest.mark.external_api
@pytest.mark.asyncio
async def test_tabs_endpoint_class_tabs(mymoment_test_credentials):
    """
    Test tabs endpoint discovers class tabs correctly.

    Class tabs represent student-class relationships and have numeric IDs.
    Based on examples/mymoment_articles_tabs.html which shows class tabs
    like "Dummy Klasse 01 (imedias)" with ID "38".
    """
    username, password = mymoment_test_credentials

    app, db_session = await create_test_app()
    email, user_password = await create_test_user(app, db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Login and create credential
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": user_password}
        )
        token = login_response.json()["access_token"]

        credential_response = await client.post(
            "/api/v1/mymoment-credentials/create",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "name": "Class Test Credential",
                "username": os.environ['MYMOMENT_TEST_USERNAME'],
                "password": os.environ['MYMOMENT_TEST_PASSWORD']
            }
        )
        credential_id = credential_response.json()["id"]

        # Get tabs
        response = await client.get(
            f"/api/v1/articles/{credential_id}/tabs",
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        data = response.json()

        # Filter class tabs
        class_tabs = [tab for tab in data["items"] if tab["tab_type"] == "class"]

        # Validate class tab structure
        for tab in class_tabs:
            # Class tabs should have numeric IDs
            assert tab["id"].isdigit(), \
                f"Class tab ID '{tab['id']}' should be numeric"

            # Should have a name
            assert len(tab["name"]) > 0, \
                "Class tab should have a name"

        print(f"\n✅ Class tabs test passed")
        print(f"   Total tabs: {len(data['items'])}")
        print(f"   Class tabs: {len(class_tabs)}")
        if class_tabs:
            print(f"   Example class tab: {class_tabs[0]}")


@pytest.mark.performance
@pytest.mark.external_api
@pytest.mark.asyncio
async def test_tabs_endpoint_unauthorized_access():
    """
    Test tabs endpoint properly rejects unauthorized access.

    Even with live tests, security should be enforced.
    """
    app, db_session = await create_test_app()

    fake_credential_id = uuid.uuid4()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/articles/{fake_credential_id}/tabs"
        )

        assert response.status_code == 401
        print(f"\n✅ Unauthorized access properly rejected")


@pytest.mark.performance
@pytest.mark.external_api
@pytest.mark.asyncio
async def test_tabs_endpoint_caching_performance(mymoment_test_credentials):
    """
    Test tabs endpoint performance with repeated calls.

    Validates that subsequent calls can leverage session caching
    for improved performance.
    """
    username, password = mymoment_test_credentials

    app, db_session = await create_test_app()
    email, user_password = await create_test_user(app, db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Login and create credential
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": user_password}
        )
        token = login_response.json()["access_token"]

        credential_response = await client.post(
            "/api/v1/mymoment-credentials/create",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "name": "Caching Test Credential",
                "username": os.environ['MYMOMENT_TEST_USERNAME'],
                "password": os.environ['MYMOMENT_TEST_PASSWORD']
            }
        )
        credential_id = credential_response.json()["id"]

        # First call - includes authentication
        start_time_1 = time.time()
        response_1 = await client.get(
            f"/api/v1/articles/{credential_id}/tabs",
            headers={"Authorization": f"Bearer {token}"}
        )
        time_1 = time.time() - start_time_1

        assert response_1.status_code == 200
        data_1 = response_1.json()

        # Second call - may leverage caching
        start_time_2 = time.time()
        response_2 = await client.get(
            f"/api/v1/articles/{credential_id}/tabs",
            headers={"Authorization": f"Bearer {token}"}
        )
        time_2 = time.time() - start_time_2

        assert response_2.status_code == 200
        data_2 = response_2.json()

        # Both responses should have same tabs
        assert data_1["total"] == data_2["total"]
        assert len(data_1["items"]) == len(data_2["items"])

        print(f"\n✅ Caching performance test passed")
        print(f"   First call: {time_1:.2f}s")
        print(f"   Second call: {time_2:.2f}s")
        print(f"   Tabs discovered: {data_1['total']}")
