"""Unit tests for LLMProviderConfiguration model behavior."""

import uuid
from datetime import datetime

import pytest

import src.models.llm_provider as llm_module
from src.models.llm_provider import LLMProviderConfiguration


@pytest.fixture
def provider_config():
    return LLMProviderConfiguration(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        provider_name="openai",
        api_key_encrypted="enc:initial",
        model_name="gpt-4o",
        max_tokens=1000,
        temperature=0.5,
        is_active=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


class TestLLMProviderConfiguration:
    """Tests covering API key helpers and configuration management."""

    def test_set_and_get_api_key_roundtrip(self, provider_config, monkeypatch):
        monkeypatch.setattr(llm_module, "encrypt_api_key", lambda value: f"enc:{value}")
        monkeypatch.setattr(llm_module, "decrypt_api_key", lambda value: value.replace("enc:", "", 1))

        before = datetime.utcnow()
        provider_config.set_api_key("secret")
        after = datetime.utcnow()

        assert provider_config.api_key_encrypted == "enc:secret"
        assert before <= provider_config.updated_at <= after
        assert provider_config.get_api_key() == "secret"

    def test_to_dict_excludes_api_key_by_default(self, provider_config):
        result = provider_config.to_dict()

        assert result["id"] == str(provider_config.id)
        assert result["provider_name"] == "openai"
        assert "api_key" not in result

    def test_to_dict_can_include_api_key(self, provider_config, monkeypatch):
        monkeypatch.setattr(llm_module, "decrypt_api_key", lambda value: "secret-value")

        result = provider_config.to_dict(include_api_key=True)

        assert result["api_key"] == "secret-value"

    def test_get_generation_config_includes_optional_fields(self, provider_config, monkeypatch):
        monkeypatch.setattr(llm_module, "decrypt_api_key", lambda value: "secret-value")

        config = provider_config.get_generation_config()

        assert config["provider_name"] == "openai"
        assert config["model_name"] == "gpt-4o"
        assert config["api_key"] == "secret-value"
        assert config["max_tokens"] == 1000
        assert config["temperature"] == 0.5

    def test_mark_as_used_sets_last_used_timestamp(self, provider_config):
        provider_config.last_used = None
        before = datetime.utcnow()

        provider_config.mark_as_used()

        assert provider_config.last_used is not None
        assert before <= provider_config.last_used <= datetime.utcnow()

    def test_update_configuration_updates_fields(self, provider_config):
        before = provider_config.updated_at

        provider_config.update_configuration(model_name="gpt-4.1", max_tokens=2000, temperature=0.9)

        assert provider_config.model_name == "gpt-4.1"
        assert provider_config.max_tokens == 2000
        assert provider_config.temperature == 0.9
        assert provider_config.updated_at >= before

    def test_activate_and_deactivate_toggle_state(self, provider_config):
        provider_config.deactivate()
        assert provider_config.is_active is False

        provider_config.activate()
        assert provider_config.is_active is True

    @pytest.mark.parametrize(
        "provider_name, expected",
        [
            ("openai", 1500),
            ("mistral", 2000),
            ("huggingface", 1000),
            ("unknown", 1000),
        ],
    )
    def test_get_default_max_tokens(self, provider_name, expected):
        config = LLMProviderConfiguration(
            user_id=uuid.uuid4(),
            provider_name=provider_name,
            api_key_encrypted="enc",
            model_name="generic",
        )

        assert config.get_default_max_tokens() == expected

    def test_get_default_temperature_returns_value(self):
        config = LLMProviderConfiguration(
            user_id=uuid.uuid4(),
            provider_name="openai",
            api_key_encrypted="enc",
            model_name="generic",
        )

        assert config.get_default_temperature() == pytest.approx(0.7)

        config.temperature = 0.2
        assert config.get_default_temperature() == 0.2
