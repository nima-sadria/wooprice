"""Tests for B3 Configuration Foundation integration in installer."""

import pytest

from app.beta.config import ValidationResult
from installer.installer_core import (
    InstallerConfig,
    _parse_env_content,
    generate_env_content,
    validate_generated_config,
)


class TestValidateGeneratedConfig:
    def test_valid_config_passes(self, valid_env_dict: dict[str, str]):
        result = validate_generated_config(env_dict=valid_env_dict)
        assert isinstance(result, ValidationResult)
        assert result.is_valid, result.format_errors()

    def test_returns_validation_result(self, valid_env_dict: dict[str, str]):
        result = validate_generated_config(env_dict=valid_env_dict)
        assert isinstance(result, ValidationResult)

    def test_accepts_env_content_string(self, valid_config_with_paths: InstallerConfig):
        content = generate_env_content(valid_config_with_paths)
        result = validate_generated_config(env_content=content)
        assert isinstance(result, ValidationResult)
        assert result.is_valid, result.format_errors()

    def test_missing_required_field_produces_error(self, valid_env_dict: dict[str, str]):
        del valid_env_dict["BETA_DOMAIN"]
        result = validate_generated_config(env_dict=valid_env_dict)
        assert not result.is_valid
        assert any(e.field == "BETA_DOMAIN" for e in result.errors)

    def test_bad_port_produces_error(self, valid_env_dict: dict[str, str]):
        valid_env_dict["BETA_PORT"] = "80"
        result = validate_generated_config(env_dict=valid_env_dict)
        assert not result.is_valid
        assert any(e.field == "BETA_PORT" for e in result.errors)

    def test_short_jwt_secret_produces_error(self, valid_env_dict: dict[str, str]):
        valid_env_dict["BETA_JWT_SECRET"] = "too_short"
        result = validate_generated_config(env_dict=valid_env_dict)
        assert not result.is_valid
        assert any(e.field == "BETA_JWT_SECRET" for e in result.errors)

    def test_bad_timezone_produces_error(self, valid_env_dict: dict[str, str]):
        valid_env_dict["BETA_TIMEZONE"] = "Nowhere/Unknown_XYZ"
        result = validate_generated_config(env_dict=valid_env_dict)
        assert not result.is_valid
        assert any(e.field == "BETA_TIMEZONE" for e in result.errors)

    def test_bad_url_produces_error(self, valid_env_dict: dict[str, str]):
        valid_env_dict["BETA_NEXTCLOUD_URL"] = "not-a-url"
        result = validate_generated_config(env_dict=valid_env_dict)
        assert not result.is_valid
        assert any(e.field == "BETA_NEXTCLOUD_URL" for e in result.errors)

    def test_bad_currency_produces_error(self, valid_env_dict: dict[str, str]):
        valid_env_dict["BETA_CURRENCY"] = "usd"  # lowercase → invalid
        result = validate_generated_config(env_dict=valid_env_dict)
        assert not result.is_valid
        assert any(e.field == "BETA_CURRENCY" for e in result.errors)

    def test_bad_email_produces_error(self, valid_env_dict: dict[str, str]):
        valid_env_dict["BETA_ADMIN_EMAIL"] = "not-an-email"
        result = validate_generated_config(env_dict=valid_env_dict)
        assert not result.is_valid
        assert any(e.field == "BETA_ADMIN_EMAIL" for e in result.errors)

    def test_bad_ssl_mode_produces_error(self, valid_env_dict: dict[str, str]):
        valid_env_dict["BETA_SSL_MODE"] = "nginx"
        result = validate_generated_config(env_dict=valid_env_dict)
        assert not result.is_valid
        assert any(e.field == "BETA_SSL_MODE" for e in result.errors)

    def test_validate_never_calls_sys_exit(self, valid_env_dict: dict[str, str]):
        import sys
        from unittest.mock import patch

        valid_env_dict["BETA_PORT"] = "not_a_port"
        with patch.object(sys, "exit", side_effect=AssertionError("sys.exit was called")):
            result = validate_generated_config(env_dict=valid_env_dict)
        assert not result.is_valid  # invalid but no exit

    def test_validation_collects_multiple_errors(self, valid_env_dict: dict[str, str]):
        valid_env_dict["BETA_PORT"] = "99"
        valid_env_dict["BETA_CURRENCY"] = "xx"
        valid_env_dict["BETA_TIMEZONE"] = "BadZone"
        result = validate_generated_config(env_dict=valid_env_dict)
        assert len(result.errors) >= 3

    def test_requires_env_dict_or_env_content(self):
        with pytest.raises(ValueError):
            validate_generated_config()

    def test_check_paths_false_by_default(self, valid_env_dict: dict[str, str]):
        # With check_paths=False, non-existent paths don't cause errors
        valid_env_dict["BETA_STORAGE_PATH"] = "/nonexistent/path/that/does/not/exist"
        result = validate_generated_config(env_dict=valid_env_dict, check_paths=False)
        assert not any(e.field == "BETA_STORAGE_PATH" for e in result.errors)

    def test_valid_config_uses_b3_validator(self, valid_env_dict: dict[str, str]):
        # Verifies that validate_generated_config delegates to B3 ConfigValidator,
        # not a reimplemented validator
        from app.beta.config import ConfigValidator
        from unittest.mock import patch

        with patch.object(ConfigValidator, "validate", wraps=ConfigValidator(check_paths=False).validate) as mock_validate:
            validate_generated_config(env_dict=valid_env_dict)
        mock_validate.assert_called_once()
