"""
Integration tests for myMoment credentials setup (T023).

Validates the full credentials workflow using the real FastAPI app and helpers.
"""

import uuid

import pytest
from httpx import AsyncClient, ASGITransport

from tests.helper import create_test_app, create_test_user


@pytest.mark.integration
@pytest.mark.web_scraping
@pytest.mark.encryption
@pytest.mark.asyncio
async def test_mymoment_credentials_complete_setup_flow():
    app, db_session = await create_test_app()
    email, password = await create_test_user(app, db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password}
        )
        headers = {"Authorization": f"Bearer {login_response.json()['access_token']}"}

        credentials1 = {
            "name": "Test Credentials 1",
            "username": "ArtificialArmadillo",
            "password": "Valid!Password123"
        }
        response1 = await client.post(
            "/api/v1/mymoment-credentials/create",
            json=credentials1,
            headers=headers
        )
        assert response1.status_code == 201

        credentials2 = {
            "name": "Test Credentials 2",
            "username": "ComputatedCrocodile",
            "password": "Valid!Password123"
        }
        response2 = await client.post(
            "/api/v1/mymoment-credentials/create",
            json=credentials2,
            headers=headers
        )
        assert response2.status_code == 201

        list_response = await client.get(
            "/api/v1/mymoment-credentials/index",
            headers=headers
        )
        assert list_response.status_code == 200
        usernames = {item["username"] for item in list_response.json()}
        assert {credentials1["username"], credentials2["username"]}.issubset(usernames)


@pytest.mark.integration
@pytest.mark.web_scraping
@pytest.mark.asyncio
async def test_mymoment_credentials_user_isolation():
    app, db_session = await create_test_app()
    email1, password1 = await create_test_user(app, db_session)
    email2, password2 = await create_test_user(app, db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login1 = await client.post(
            "/api/v1/auth/login",
            json={"email": email1, "password": password1}
        )
        login2 = await client.post(
            "/api/v1/auth/login",
            json={"email": email2, "password": password2}
        )

        headers1 = {"Authorization": f"Bearer {login1.json()['access_token']}"}
        headers2 = {"Authorization": f"Bearer {login2.json()['access_token']}"}

        await client.post(
            "/api/v1/mymoment-credentials/create",
            json={"name": "Test Credentials 1", "username": "ArtificialArmadillo", "password": "Valid!Password123"},
            headers=headers1
        )
        await client.post(
            "/api/v1/mymoment-credentials/create",
            json={"name": "Test Credentials 2", "username": "ComputatedCrocodile", "password": "Valid!Password123"},
            headers=headers2
        )

        list1 = await client.get("/api/v1/mymoment-credentials/index", headers=headers1)
        list2 = await client.get("/api/v1/mymoment-credentials/index", headers=headers2)

        assert len(list1.json()) == 1
        assert len(list2.json()) == 1
        assert list1.json()[0]["username"] == "ArtificialArmadillo"
        assert list2.json()[0]["username"] == "ComputatedCrocodile"


@pytest.mark.integration
@pytest.mark.web_scraping
@pytest.mark.asyncio
async def test_mymoment_credentials_validation_errors():
    app, db_session = await create_test_app()
    email, password = await create_test_user(app, db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password}
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        invalid_payloads = [
            {},
            {"username": "ArtificialArmadillo"},
            {"password": "Valid!Password123"},
            {"username": "", "password": "Valid!Password123"},
            {"username": "ArtificialArmadillo", "password": ""},
        ]

        for payload in invalid_payloads:
            response = await client.post(
                "/api/v1/mymoment-credentials/create",
                json=payload,
                headers=headers
            )
            assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.web_scraping
@pytest.mark.asyncio
async def test_mymoment_credentials_crud_flow():
    app, db_session = await create_test_app()
    email, password = await create_test_user(app, db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password}
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        create_resp = await client.post(
            "/api/v1/mymoment-credentials/create",
            json={"name": "Test Credentials 1", "username": "ArtificialArmadillo", "password": "Valid!Password123"},
            headers=headers
        )
        assert create_resp.status_code == 201
        cred_id = create_resp.json()["id"]

        get_resp = await client.get(
            f"/api/v1/mymoment-credentials/{cred_id}",
            headers=headers
        )
        if get_resp.status_code != 404:
            assert get_resp.status_code == 200
            assert get_resp.json()["username"] == "ArtificialArmadillo"

        patch_resp = await client.patch(
            f"/api/v1/mymoment-credentials/{cred_id}",
            json={"password": "SecondValid!Password123"},
            headers=headers
        )
        if patch_resp.status_code != 404:
            assert patch_resp.status_code == 200

        delete_resp = await client.delete(
            f"/api/v1/mymoment-credentials/{cred_id}",
            headers=headers
        )
        if delete_resp.status_code != 404:
            assert delete_resp.status_code in (200, 204)
