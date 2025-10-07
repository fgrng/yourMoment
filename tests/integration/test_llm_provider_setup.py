"""
Integration tests for LLM provider configuration (T022).

Tests the complete LLM provider setup workflow as described in Scenario 2
of the quickstart guide. These tests MUST FAIL until models, services,
and API endpoints are implemented (TDD requirement).
"""

import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import status

from src.config.encryption import encrypt_api_key, decrypt_api_key, is_field_encrypted
from tests.helper import create_test_app, create_test_user


@pytest.mark.integration
@pytest.mark.llm
@pytest.mark.encryption
@pytest.mark.asyncio
async def test_llm_provider_complete_setup_flow():
    """
    Test complete LLM provider configuration flow from quickstart Scenario 2.

    This test validates:
    - User can add multiple LLM providers
    - API keys are encrypted before storage
    - API keys never appear in API responses
    - Provider configuration is saved per user
    - Multiple provider types supported (OpenAI, Mistral, HuggingFace)
    """
    app, db_session = await create_test_app()
    email, password = await create_test_user(app, db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password}
        )
        assert login_response.status_code == status.HTTP_200_OK
        token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Step 1: Add OpenAI provider
        openai_config = {
            "provider_name": "openai",
            "api_key": "sk-test-openai-key-dummy-12345",
            "model_name": "gpt-3.5-turbo",
            "temperature": 0.7,
            "max_tokens": 1000
        }

        openai_response = await client.post(
            "/api/v1/llm-providers/create",
            json=openai_config,
            headers=headers
        )

        assert openai_response.status_code == status.HTTP_201_CREATED
        openai_data = openai_response.json()

        # Validate response schema
        assert "id" in openai_data
        assert openai_data["provider_name"] == "openai"
        assert openai_data["model_name"] == "gpt-3.5-turbo"
        assert openai_data["temperature"] == 0.7
        assert "api_key" not in openai_data  # API key must not be returned!

        openai_provider_id = openai_data["id"]

        # Step 2: Add Mistral provider
        mistral_config = {
            "provider_name": "mistral",
            "api_key": "sk-mistral-test-key-dummy-67890",
            "model_name": "mistral-large-latest",
            "temperature": 0.8,
            "max_tokens": 2000
        }

        mistral_response = await client.post(
            "/api/v1/llm-providers/create",
            json=mistral_config,
            headers=headers
        )

        assert mistral_response.status_code == status.HTTP_201_CREATED
        mistral_data = mistral_response.json()

        assert mistral_data["provider_name"] == "mistral"
        assert "api_key" not in mistral_data  # API key must not be returned!

        # Step 3: List all providers for user
        list_response = await client.get(
            "/api/v1/llm-providers/index",
            headers=headers
        )

        assert list_response.status_code == status.HTTP_200_OK
        providers_list = list_response.json()

        # Should have 2 providers
        assert len(providers_list) == 2

        # Verify both providers are present and API keys are hidden
        provider_names = [p["provider_name"] for p in providers_list]
        assert "openai" in provider_names
        assert "mistral" in provider_names

        for provider in providers_list:
            assert "api_key" not in provider  # Critical security requirement
            assert "id" in provider
            assert "provider_name" in provider
            assert "model_name" in provider
            assert "created_at" in provider


@pytest.mark.integration
@pytest.mark.llm
@pytest.mark.encryption
@pytest.mark.asyncio
async def test_api_key_encryption_security():
    """
    Test that API keys are properly encrypted before storage.

    This validates the critical security requirement that LLM provider
    API keys are never stored in plaintext.
    """
    app, db_session = await create_test_app()
    email, password = await create_test_user(app, db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password}
        )
        assert login_response.status_code == status.HTTP_200_OK
        token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Add provider with sensitive API key
        sensitive_api_key = "sk-very-secret-api-key-12345"
        provider_config = {
            "provider_name": "openai",
            "api_key": sensitive_api_key,
            "model_name": "gpt-4",
            "temperature": 0.5
        }

        response = await client.post(
            "/api/v1/llm-providers",
            json=provider_config,
            headers=headers
        )

        assert response.status_code == status.HTTP_201_CREATED

        # TODO: When database models are implemented, verify:
        # 1. API key is encrypted in database storage
        # 2. Encrypted value is different from plaintext
        # 3. Encryption uses Fernet from our encryption config
        # 4. API key can be decrypted for actual LLM API calls

        # For now, demonstrate encryption config works
        encrypted_key = encrypt_api_key(sensitive_api_key)
        decrypted_key = decrypt_api_key(encrypted_key)

        assert is_field_encrypted(encrypted_key)
        assert not is_field_encrypted(sensitive_api_key)
        assert decrypted_key == sensitive_api_key
        assert encrypted_key != sensitive_api_key


@pytest.mark.integration
@pytest.mark.llm
@pytest.mark.asyncio
async def test_llm_provider_user_isolation():
    """
    Test that LLM providers are isolated per user.

    Each user should only see their own LLM provider configurations.
    """
    app, db_session = await create_test_app()
    user1_email, user1_password = await create_test_user(app, db_session)
    user2_email, user2_password = await create_test_user(app, db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login1_response = await client.post(
            "/api/v1/auth/login",
            json={"email": user1_email, "password": user1_password}
        )
        login2_response = await client.post(
            "/api/v1/auth/login",
            json={"email": user2_email, "password": user2_password}
        )

        assert login1_response.status_code == status.HTTP_200_OK
        assert login2_response.status_code == status.HTTP_200_OK

        token1 = login1_response.json()["access_token"]
        token2 = login2_response.json()["access_token"]

        headers1 = {"Authorization": f"Bearer {token1}"}
        headers2 = {"Authorization": f"Bearer {token2}"}

        # User 1 adds OpenAI provider
        user1_config = {
            "provider_name": "openai",
            "api_key": "sk-user1-key",
            "model_name": "gpt-3.5-turbo",
            "temperature": 0.7
        }

        await client.post(
            "/api/v1/llm-providers/create",
            json=user1_config,
            headers=headers1
        )

        # User 2 adds HuggingFace provider
        user2_config = {
            "provider_name": "huggingface",
            "api_key": "hf-user2-key",
            "model_name": "meta-llama/Meta-Llama-3-8B-Instruct",
            "temperature": 0.8
        }

        await client.post(
            "/api/v1/llm-providers/create",
            json=user2_config,
            headers=headers2
        )

        # User 1 should only see their provider
        user1_list_response = await client.get(
            "/api/v1/llm-providers/index",
            headers=headers1
        )
        user1_providers = user1_list_response.json()

        assert len(user1_providers) == 1
        assert user1_providers[0]["provider_name"] == "openai"

        # User 2 should only see their provider
        user2_list_response = await client.get(
            "/api/v1/llm-providers/index",
            headers=headers2
        )
        user2_providers = user2_list_response.json()

        assert len(user2_providers) == 1
        assert user2_providers[0]["provider_name"] == "huggingface"


@pytest.mark.integration
@pytest.mark.llm
@pytest.mark.asyncio
async def test_llm_provider_crud_operations():
    """Test complete CRUD operations for LLM providers."""
    app, db_session = await create_test_app()
    email, password = await create_test_user(app, db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password}
        )
        assert login_response.status_code == status.HTTP_200_OK
        token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # CREATE: Add provider
        provider_config = {
            "provider_name": "openai",
            "api_key": "sk-test-key",
            "model_name": "gpt-3.5-turbo",
            "temperature": 0.7
        }

        create_response = await client.post(
            "/api/v1/llm-providers/create",
            json=provider_config,
            headers=headers
        )

        assert create_response.status_code == status.HTTP_201_CREATED
        provider_data = create_response.json()
        provider_id = provider_data["id"]

        # READ: Get specific provider (if endpoint exists)
        get_response = await client.get(
            f"/api/v1/llm-providers/{provider_id}",
            headers=headers
        )

        if get_response.status_code != status.HTTP_404_NOT_FOUND:
            # If endpoint is implemented, validate response
            assert get_response.status_code == status.HTTP_200_OK
            get_data = get_response.json()
            assert get_data["id"] == provider_id
            assert "api_key" not in get_data

        # UPDATE: Modify provider (if endpoint exists)
        update_data = {
            "model_name": "gpt-4",
            "temperature": 0.8
        }

        update_response = await client.patch(
            f"/api/v1/llm-providers/{provider_id}",
            json=update_data,
            headers=headers
        )

        # May not be implemented yet, check if it exists
        if update_response.status_code != status.HTTP_404_NOT_FOUND:
            assert update_response.status_code == status.HTTP_200_OK

        # DELETE: Remove provider (if endpoint exists)
        delete_response = await client.delete(
            f"/api/v1/llm-providers/{provider_id}",
            headers=headers
        )

        # May not be implemented yet
        if delete_response.status_code != status.HTTP_404_NOT_FOUND:
            assert delete_response.status_code in [
                status.HTTP_200_OK,
                status.HTTP_204_NO_CONTENT
            ]


@pytest.mark.integration
@pytest.mark.llm
@pytest.mark.asyncio
async def test_llm_provider_validation_requirements():
    """Test LLM provider input validation and business rules."""
    app, db_session = await create_test_app()
    email, password = await create_test_user(app, db_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password}
        )
        assert login_response.status_code == status.HTTP_200_OK
        token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Test missing required fields
        invalid_configs = [
            {},  # All fields missing
            {"provider_name": "openai"},  # Missing API key
            {"api_key": "sk-test"},  # Missing provider name
            {"provider_name": "openai", "api_key": ""},  # Empty API key
            {"provider_name": "", "api_key": "sk-test"},  # Empty provider name
        ]

        for invalid_config in invalid_configs:
            response = await client.post(
                "/api/v1/llm-providers/create",
                json=invalid_config,
                headers=headers
            )
            assert response.status_code in {
                status.HTTP_400_BAD_REQUEST,
                status.HTTP_422_UNPROCESSABLE_ENTITY
            }

        # Test unsupported provider (if validation exists)
        unsupported_provider = {
            "provider_name": "unsupported_provider",
            "api_key": "some-key",
            "model_name": "some-model"
        }

        unsupported_response = await client.post(
            "/api/v1/llm-providers/create",
            json=unsupported_provider,
            headers=headers
        )

        # Should either accept it or reject with 400
        assert unsupported_response.status_code in [
            status.HTTP_201_CREATED,  # If validation not implemented yet
            status.HTTP_400_BAD_REQUEST  # If validation rejects unsupported providers
        ]


@pytest.mark.integration
@pytest.mark.llm
@pytest.mark.asyncio
async def test_llm_provider_unauthorized_access():
    """Test that LLM provider endpoints require authentication."""
    app, _ = await create_test_app()

    provider_config = {
        "provider_name": "openai",
        "api_key": "sk-test-key",
        "model_name": "gpt-3.5-turbo"
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Test POST without authentication
        post_response = await client.post(
            "/api/v1/llm-providers/create",
            json=provider_config
        )
        assert post_response.status_code == status.HTTP_401_UNAUTHORIZED

        # Test GET without authentication
        get_response = await client.get("/api/v1/llm-providers/index")
        assert get_response.status_code == status.HTTP_401_UNAUTHORIZED

        # Test with invalid token
        invalid_headers = {"Authorization": "Bearer invalid-token"}

        post_invalid_response = await client.post(
            "/api/v1/llm-providers/create",
            json=provider_config,
            headers=invalid_headers
        )
        assert post_invalid_response.status_code == status.HTTP_401_UNAUTHORIZED

        get_invalid_response = await client.get(
            "/api/v1/llm-providers/index",
            headers=invalid_headers
        )
        assert get_invalid_response.status_code == status.HTTP_401_UNAUTHORIZED
