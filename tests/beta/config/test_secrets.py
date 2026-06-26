"""Tests for app.beta.config.secrets."""

import pytest

from app.beta.config.secrets import EnvSecretProvider, SECRET_FIELDS, SecretProvider


class TestSecretFields:
    def test_all_expected_fields_present(self):
        expected = {
            "BETA_JWT_SECRET",
            "BETA_REST_API_SECRET",
            "BETA_POSTGRES_PASSWORD",
            "BETA_NEXTCLOUD_PASSWORD",
            "BETA_WOOCOMMERCE_KEY",
            "BETA_WOOCOMMERCE_SECRET",
        }
        assert expected == SECRET_FIELDS

    def test_non_secrets_not_included(self):
        assert "BETA_ENV" not in SECRET_FIELDS
        assert "BETA_DOMAIN" not in SECRET_FIELDS
        assert "BETA_PORT" not in SECRET_FIELDS


class TestEnvSecretProvider:
    def test_is_abstract_subclass(self):
        assert issubclass(EnvSecretProvider, SecretProvider)

    def test_get_returns_env_value(self, monkeypatch):
        monkeypatch.setenv("BETA_JWT_SECRET", "test_secret_value")
        provider = EnvSecretProvider()
        assert provider.get("BETA_JWT_SECRET") == "test_secret_value"

    def test_get_returns_none_when_absent(self, monkeypatch):
        monkeypatch.delenv("BETA_JWT_SECRET", raising=False)
        provider = EnvSecretProvider()
        assert provider.get("BETA_JWT_SECRET") is None

    def test_names_returns_all_secrets(self):
        provider = EnvSecretProvider()
        assert set(provider.names()) == SECRET_FIELDS

    def test_names_returns_sorted_list(self):
        provider = EnvSecretProvider()
        names = provider.names()
        assert names == sorted(names)

    def test_is_secret_true_for_secrets(self):
        provider = EnvSecretProvider()
        for name in SECRET_FIELDS:
            assert provider.is_secret(name) is True

    def test_is_secret_false_for_non_secrets(self):
        provider = EnvSecretProvider()
        assert provider.is_secret("BETA_ENV") is False
        assert provider.is_secret("BETA_DOMAIN") is False
        assert provider.is_secret("UNRELATED_VAR") is False
