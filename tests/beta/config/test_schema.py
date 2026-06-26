"""Tests for app.beta.config.schema (BetaConfig)."""

import pytest
from pydantic import ValidationError

from app.beta.config.profiles import ConfigProfile
from app.beta.config.schema import BetaConfig


class TestBetaConfigFromEnvValid:
    def test_builds_from_valid_env(self, valid_env):
        config = BetaConfig.from_env(valid_env)
        assert config.env == ConfigProfile.BETA
        assert config.domain == "test.example.com"
        assert config.port == 8080

    def test_env_field_maps_to_profile(self, valid_env):
        valid_env["BETA_ENV"] = "dev"
        config = BetaConfig.from_env(valid_env)
        assert config.env == ConfigProfile.DEV
        assert config.is_dev() is True

    def test_production_profile(self, valid_env):
        valid_env["BETA_ENV"] = "production"
        config = BetaConfig.from_env(valid_env)
        assert config.is_production() is True

    def test_secrets_are_secret_str(self, valid_env):
        config = BetaConfig.from_env(valid_env)
        # SecretStr should redact in repr
        assert "a" * 64 not in repr(config.jwt_secret)
        # But accessible via get_secret_value()
        assert config.jwt_secret.get_secret_value() == "a" * 64

    def test_plugin_dir_computed_from_storage_path(self, valid_env):
        valid_env.pop("BETA_PLUGIN_DIR", None)
        valid_env["BETA_STORAGE_PATH"] = "/tmp/storage"
        config = BetaConfig.from_env(valid_env)
        assert config.plugin_dir == "/tmp/storage/plugins"

    def test_explicit_plugin_dir_not_overridden(self, valid_env):
        valid_env["BETA_PLUGIN_DIR"] = "/custom/plugins"
        config = BetaConfig.from_env(valid_env)
        assert config.plugin_dir == "/custom/plugins"

    def test_defaults_applied_for_optional_fields(self, valid_env):
        config = BetaConfig.from_env(valid_env)
        assert config.log_level == "INFO"
        assert config.jwt_access_ttl_minutes == 15
        assert config.jwt_refresh_ttl_days == 7
        assert config.max_upload_mb == 50
        assert config.worker_concurrency == 2
        assert config.scheduler_poll_seconds == 30
        assert config.backup_retain_days == 30

    def test_log_level_uppercased(self, valid_env):
        valid_env["BETA_LOG_LEVEL"] = "debug"
        config = BetaConfig.from_env(valid_env)
        assert config.log_level == "DEBUG"

    def test_banner_returns_string(self, valid_env):
        config = BetaConfig.from_env(valid_env)
        assert "BETA" in config.banner()

    def test_frozen_model_cannot_be_mutated(self, valid_env):
        config = BetaConfig.from_env(valid_env)
        with pytest.raises(Exception):
            config.domain = "changed.example.com"  # type: ignore[misc]


class TestBetaConfigFromEnvInvalid:
    def test_bad_ssl_mode_raises(self, valid_env):
        valid_env["BETA_SSL_MODE"] = "auto"
        with pytest.raises(ValidationError) as exc_info:
            BetaConfig.from_env(valid_env)
        assert "ssl_mode" in str(exc_info.value).lower()

    def test_bad_currency_raises(self, valid_env):
        valid_env["BETA_CURRENCY"] = "eur"
        with pytest.raises(ValidationError):
            BetaConfig.from_env(valid_env)

    def test_bad_timezone_raises(self, valid_env):
        valid_env["BETA_TIMEZONE"] = "Invalid/Zone"
        with pytest.raises(ValidationError):
            BetaConfig.from_env(valid_env)

    def test_bad_database_url_raises(self, valid_env):
        valid_env["BETA_DATABASE_URL"] = "mysql://user:pass@host/db"
        with pytest.raises(ValidationError):
            BetaConfig.from_env(valid_env)

    def test_bad_nextcloud_url_raises(self, valid_env):
        valid_env["BETA_NEXTCLOUD_URL"] = "not-a-url"
        with pytest.raises(ValidationError):
            BetaConfig.from_env(valid_env)

    def test_short_jwt_secret_raises(self, valid_env):
        valid_env["BETA_JWT_SECRET"] = "short"
        with pytest.raises(ValidationError):
            BetaConfig.from_env(valid_env)

    def test_short_rest_api_secret_raises(self, valid_env):
        valid_env["BETA_REST_API_SECRET"] = "short"
        with pytest.raises(ValidationError):
            BetaConfig.from_env(valid_env)

    def test_empty_domain_raises(self, valid_env):
        valid_env["BETA_DOMAIN"] = ""
        with pytest.raises(ValidationError):
            BetaConfig.from_env(valid_env)

    def test_port_out_of_range_raises(self, valid_env):
        valid_env["BETA_PORT"] = "80"
        with pytest.raises(ValidationError):
            BetaConfig.from_env(valid_env)

    def test_empty_postgres_password_raises(self, valid_env):
        valid_env["BETA_POSTGRES_PASSWORD"] = ""
        with pytest.raises(ValidationError):
            BetaConfig.from_env(valid_env)

    def test_bad_log_level_raises(self, valid_env):
        valid_env["BETA_LOG_LEVEL"] = "VERBOSE"
        with pytest.raises(ValidationError):
            BetaConfig.from_env(valid_env)
