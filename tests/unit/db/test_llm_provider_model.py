"""DB-backed tests for the current `LLMProviderConfiguration` model behavior."""

from __future__ import annotations

from datetime import datetime

import pytest

from tests.fixtures.assertions import assert_api_key_round_trip
from tests.fixtures.factories import create_llm_provider, create_user


pytestmark = pytest.mark.database


async def test_api_key_round_trip_and_safe_display_use_model_helpers(db_session):
    user = await create_user(db_session)
    provider = await create_llm_provider(
        db_session,
        user=user,
        provider_name="openai",
        model_name="gpt-4o-mini",
        api_key="sk-test-provider-secret",
    )

    assert_api_key_round_trip(provider, api_key="sk-test-provider-secret")

    payload = provider.to_dict()
    assert payload["id"] == str(provider.id)
    assert payload["user_id"] == str(user.id)
    assert payload["provider_name"] == "openai"
    assert payload["model_name"] == "gpt-4o-mini"
    assert payload["created_at"] is not None
    assert payload["updated_at"] is not None
    assert "api_key" not in payload
    assert "api_key_encrypted" not in payload

    with_api_key = provider.to_dict(include_api_key=True)
    assert with_api_key["api_key"] == "sk-test-provider-secret"


async def test_generation_config_and_default_helpers_reflect_current_fields(db_session):
    user = await create_user(db_session)
    configured = await create_llm_provider(
        db_session,
        user=user,
        provider_name="openai",
        model_name="gpt-4.1-mini",
        api_key="sk-configured",
        max_tokens=900,
        temperature=0.25,
    )
    defaults_only = await create_llm_provider(
        db_session,
        user=user,
        provider_name="mistral",
        model_name="mistral-large-latest",
        api_key="sk-defaults",
        max_tokens=None,
        temperature=None,
    )

    config = configured.get_generation_config()
    assert config == {
        "provider_name": "openai",
        "model_name": "gpt-4.1-mini",
        "api_key": "sk-configured",
        "max_tokens": 900,
        "temperature": 0.25,
    }

    defaults_config = defaults_only.get_generation_config()
    assert defaults_config == {
        "provider_name": "mistral",
        "model_name": "mistral-large-latest",
        "api_key": "sk-defaults",
    }
    assert defaults_only.get_default_max_tokens() == 2000
    assert defaults_only.get_default_temperature() == 0.7


async def test_lifecycle_and_update_configuration_helpers_keep_api_key_safe(db_session):
    user = await create_user(db_session)
    provider = await create_llm_provider(
        db_session,
        user=user,
        model_name="gpt-4o",
        api_key="sk-original",
    )

    before_used = datetime.utcnow()
    provider.mark_as_used()
    assert provider.last_used is not None
    assert provider.last_used >= before_used

    provider.update_configuration(
        model_name="gpt-4o-mini",
        max_tokens=512,
        temperature=0.35,
        api_key="sk-ignored",
    )
    assert provider.model_name == "gpt-4o-mini"
    assert provider.max_tokens == 512
    assert provider.temperature == pytest.approx(0.35)
    assert provider.get_api_key() == "sk-original"

    provider.deactivate()
    assert provider.is_active is False
    provider.activate()
    assert provider.is_active is True
