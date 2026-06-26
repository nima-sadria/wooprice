"""Tests for installer secret generation."""

import re

import pytest

from installer.installer_core import (
    InstallerConfig,
    InstallerSecrets,
    _JWT_SECRET_MIN_BYTES,
    _REST_SECRET_HEX_BYTES,
    apply_secrets,
    generate_secrets,
)


class TestGenerateSecrets:
    def test_returns_installer_secrets(self):
        sec = generate_secrets()
        assert isinstance(sec, InstallerSecrets)

    def test_jwt_secret_minimum_length(self):
        sec = generate_secrets()
        # token_urlsafe(64) → ~86 base64url chars
        assert len(sec.jwt_secret) >= _JWT_SECRET_MIN_BYTES

    def test_rest_api_secret_is_64_char_hex(self):
        sec = generate_secrets()
        # token_hex(32) → 64 hex chars
        assert len(sec.rest_api_secret) == _REST_SECRET_HEX_BYTES * 2
        assert re.fullmatch(r"[0-9a-f]+", sec.rest_api_secret)

    def test_postgres_password_non_empty(self):
        sec = generate_secrets()
        assert len(sec.postgres_password) >= 20

    def test_secrets_are_unique_across_calls(self):
        sec1 = generate_secrets()
        sec2 = generate_secrets()
        assert sec1.jwt_secret != sec2.jwt_secret
        assert sec1.rest_api_secret != sec2.rest_api_secret
        assert sec1.postgres_password != sec2.postgres_password

    def test_secrets_have_no_newlines(self):
        sec = generate_secrets()
        assert "\n" not in sec.jwt_secret
        assert "\n" not in sec.rest_api_secret
        assert "\n" not in sec.postgres_password


class TestInstallerSecretsMaskedSummary:
    def test_masked_summary_returns_dict(self):
        sec = InstallerSecrets(
            jwt_secret="a" * 64,
            rest_api_secret="b" * 64,
            postgres_password="c" * 32,
        )
        summary = sec.masked_summary()
        assert isinstance(summary, dict)

    def test_masked_summary_keys(self):
        sec = InstallerSecrets(jwt_secret="x" * 64, rest_api_secret="y" * 64, postgres_password="z" * 32)
        summary = sec.masked_summary()
        assert "jwt_secret" in summary
        assert "rest_api_secret" in summary
        assert "postgres_password" in summary

    def test_masked_summary_does_not_reveal_full_secret(self):
        jwt = "a" * 64
        sec = InstallerSecrets(jwt_secret=jwt, rest_api_secret="b" * 64, postgres_password="c" * 32)
        summary = sec.masked_summary()
        assert summary["jwt_secret"] != jwt
        assert "a" * 64 not in summary["jwt_secret"]

    def test_masked_summary_shows_last_4_chars(self):
        sec = InstallerSecrets(
            jwt_secret="x" * 60 + "abcd",
            rest_api_secret="y" * 60 + "efgh",
            postgres_password="z" * 28 + "ijkl",
        )
        summary = sec.masked_summary()
        assert summary["jwt_secret"].endswith("abcd")
        assert summary["rest_api_secret"].endswith("efgh")
        assert summary["postgres_password"].endswith("ijkl")

    def test_masked_summary_contains_asterisks(self):
        sec = InstallerSecrets(jwt_secret="a" * 64, rest_api_secret="b" * 64, postgres_password="c" * 32)
        summary = sec.masked_summary()
        assert "*" in summary["jwt_secret"]
        assert "*" in summary["rest_api_secret"]
        assert "*" in summary["postgres_password"]

    def test_masked_summary_short_secret(self):
        sec = InstallerSecrets(jwt_secret="abc", rest_api_secret="de", postgres_password="f")
        summary = sec.masked_summary()
        assert summary["jwt_secret"] == "****"
        assert summary["rest_api_secret"] == "****"
        assert summary["postgres_password"] == "****"


class TestApplySecrets:
    def test_fills_empty_jwt_secret(self):
        config = InstallerConfig(jwt_secret="")
        sec = InstallerSecrets(jwt_secret="new_jwt", rest_api_secret="new_rest", postgres_password="new_pg")
        result = apply_secrets(config, sec)
        assert result.jwt_secret == "new_jwt"

    def test_fills_empty_rest_secret(self):
        config = InstallerConfig(rest_api_secret="")
        sec = InstallerSecrets(jwt_secret="j", rest_api_secret="new_rest", postgres_password="p")
        result = apply_secrets(config, sec)
        assert result.rest_api_secret == "new_rest"

    def test_fills_empty_postgres_password(self):
        config = InstallerConfig(postgres_password="")
        sec = InstallerSecrets(jwt_secret="j", rest_api_secret="r", postgres_password="new_pg")
        result = apply_secrets(config, sec)
        assert result.postgres_password == "new_pg"

    def test_does_not_overwrite_provided_jwt_secret(self):
        config = InstallerConfig(jwt_secret="my_existing_jwt_" + "x" * 48)
        sec = InstallerSecrets(jwt_secret="new_jwt", rest_api_secret="new_rest", postgres_password="new_pg")
        result = apply_secrets(config, sec)
        assert result.jwt_secret == config.jwt_secret

    def test_does_not_overwrite_provided_postgres_password(self):
        config = InstallerConfig(postgres_password="my_existing_pw_abc123")
        sec = InstallerSecrets(jwt_secret="j", rest_api_secret="r", postgres_password="new_pg")
        result = apply_secrets(config, sec)
        assert result.postgres_password == "my_existing_pw_abc123"

    def test_returns_new_instance(self):
        config = InstallerConfig()
        sec = InstallerSecrets(jwt_secret="j", rest_api_secret="r", postgres_password="p")
        result = apply_secrets(config, sec)
        assert result is not config


class TestInstallerConfigNeedsSecretGeneration:
    def test_empty_jwt_needs_generation(self):
        config = InstallerConfig(jwt_secret="")
        assert config.needs_secret_generation() is True

    def test_empty_rest_needs_generation(self):
        config = InstallerConfig(jwt_secret="x" * 64, rest_api_secret="")
        assert config.needs_secret_generation() is True

    def test_empty_pg_needs_generation(self):
        config = InstallerConfig(jwt_secret="x" * 64, rest_api_secret="y" * 32, postgres_password="")
        assert config.needs_secret_generation() is True

    def test_all_provided_no_generation_needed(self):
        config = InstallerConfig(
            jwt_secret="x" * 64,
            rest_api_secret="y" * 32,
            postgres_password="some_pass",
        )
        assert config.needs_secret_generation() is False
