"""Tests for app.beta.config.validation."""

import pytest

from app.beta.config.validation import (
    ConfigValidator,
    FieldError,
    REQUIRED_FIELDS,
    ValidationResult,
    _check_currency,
    _check_database_url,
    _check_email,
    _check_env,
    _check_jwt_secret,
    _check_log_level,
    _check_port,
    _check_positive_int,
    _check_rest_secret,
    _check_ssl_mode,
    _check_timezone,
    _check_url,
)


class TestValidationResult:
    def test_is_valid_when_empty(self):
        r = ValidationResult()
        assert r.is_valid is True
        assert bool(r) is True

    def test_is_invalid_when_errors_present(self):
        r = ValidationResult()
        r.add_error("SOME_VAR", "bad", "reason")
        assert r.is_valid is False
        assert bool(r) is False

    def test_add_error(self):
        r = ValidationResult()
        r.add_error("BETA_ENV", "bad", "not valid")
        assert len(r.errors) == 1
        assert r.errors[0].field == "BETA_ENV"
        assert r.errors[0].message == "not valid"

    def test_add_warning(self):
        r = ValidationResult()
        r.add_warning("watch out")
        assert len(r.warnings) == 1
        assert r.warnings[0] == "watch out"

    def test_format_errors_no_errors(self):
        r = ValidationResult()
        assert r.format_errors() == "No errors."

    def test_format_errors_with_error(self):
        r = ValidationResult()
        r.add_error("BETA_DOMAIN", "bad_val", "too short")
        formatted = r.format_errors()
        assert "BETA_DOMAIN" in formatted
        assert "too short" in formatted

    def test_format_errors_redacts_secrets(self):
        r = ValidationResult()
        r.add_error("BETA_JWT_SECRET", "my_secret", "too short")
        formatted = r.format_errors()
        assert "my_secret" not in formatted
        assert "[REDACTED]" in formatted


class TestFieldCheckers:
    # BETA_ENV
    def test_check_env_valid_values(self):
        for v in ("dev", "beta", "production"):
            assert _check_env(v) is None

    def test_check_env_invalid(self):
        assert _check_env("staging") is not None
        assert _check_env("prod") is not None

    def test_check_env_empty_passes(self):
        assert _check_env("") is None  # presence check is separate

    # BETA_PORT
    def test_check_port_valid(self):
        assert _check_port("8080") is None
        assert _check_port("1024") is None
        assert _check_port("65535") is None

    def test_check_port_too_low(self):
        assert _check_port("80") is not None
        assert _check_port("1023") is not None

    def test_check_port_too_high(self):
        assert _check_port("65536") is not None

    def test_check_port_not_integer(self):
        assert _check_port("abc") is not None

    def test_check_port_empty_passes(self):
        assert _check_port("") is None

    # BETA_DATABASE_URL
    def test_check_database_url_valid(self):
        assert _check_database_url("postgresql://user:pass@host/db") is None
        assert _check_database_url("postgresql+asyncpg://user:pass@host/db") is None

    def test_check_database_url_invalid_scheme(self):
        assert _check_database_url("mysql://user:pass@host/db") is not None
        assert _check_database_url("http://example.com") is not None

    # BETA_JWT_SECRET
    def test_check_jwt_secret_valid(self):
        assert _check_jwt_secret("a" * 64) is None
        assert _check_jwt_secret("a" * 128) is None

    def test_check_jwt_secret_too_short(self):
        assert _check_jwt_secret("a" * 63) is not None
        assert _check_jwt_secret("short") is not None

    # BETA_REST_API_SECRET
    def test_check_rest_secret_valid(self):
        assert _check_rest_secret("a" * 32) is None
        assert _check_rest_secret("a" * 64) is None

    def test_check_rest_secret_too_short(self):
        assert _check_rest_secret("a" * 31) is not None

    # URLs
    def test_check_url_valid(self):
        assert _check_url("https://example.com") is None
        assert _check_url("http://example.com/path") is None

    def test_check_url_missing_scheme(self):
        assert _check_url("example.com") is not None
        assert _check_url("ftp://example.com") is not None

    # BETA_TIMEZONE
    def test_check_timezone_valid(self):
        assert _check_timezone("UTC") is None
        assert _check_timezone("Europe/Amsterdam") is None
        assert _check_timezone("America/New_York") is None

    def test_check_timezone_invalid(self):
        assert _check_timezone("Not/A/Timezone") is not None
        assert _check_timezone("Nowhere/Unknown_XYZ_9999") is not None

    # BETA_CURRENCY
    def test_check_currency_valid(self):
        assert _check_currency("EUR") is None
        assert _check_currency("USD") is None
        assert _check_currency("IRR") is None

    def test_check_currency_invalid(self):
        assert _check_currency("eur") is not None  # lowercase
        assert _check_currency("EU") is not None  # too short
        assert _check_currency("EURO") is not None  # too long
        assert _check_currency("123") is not None  # digits

    # BETA_ADMIN_EMAIL
    def test_check_email_valid(self):
        assert _check_email("admin@example.com") is None
        assert _check_email("user+tag@sub.domain.org") is None

    def test_check_email_invalid(self):
        assert _check_email("not-an-email") is not None
        assert _check_email("@example.com") is not None
        assert _check_email("user@") is not None

    # BETA_SSL_MODE
    def test_check_ssl_mode_valid(self):
        for v in ("off", "self-signed", "letsencrypt", "manual"):
            assert _check_ssl_mode(v) is None

    def test_check_ssl_mode_invalid(self):
        assert _check_ssl_mode("none") is not None
        assert _check_ssl_mode("auto") is not None

    # BETA_LOG_LEVEL
    def test_check_log_level_valid(self):
        for v in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            assert _check_log_level(v) is None

    def test_check_log_level_invalid(self):
        assert _check_log_level("VERBOSE") is not None
        assert _check_log_level("warn") is not None  # case-sensitive check

    # Positive int
    def test_check_positive_int_valid(self):
        assert _check_positive_int("1") is None
        assert _check_positive_int("100") is None

    def test_check_positive_int_zero(self):
        assert _check_positive_int("0") is not None

    def test_check_positive_int_negative(self):
        assert _check_positive_int("-5") is not None

    def test_check_positive_int_not_int(self):
        assert _check_positive_int("abc") is not None


class TestConfigValidatorFull:
    def test_valid_env_passes(self, valid_env):
        validator = ConfigValidator(check_paths=False)
        result = validator.validate(valid_env)
        assert result.is_valid, result.format_errors()

    def test_missing_required_field_adds_error(self, valid_env):
        del valid_env["BETA_DOMAIN"]
        validator = ConfigValidator(check_paths=False)
        result = validator.validate(valid_env)
        assert not result.is_valid
        fields = [e.field for e in result.errors]
        assert "BETA_DOMAIN" in fields

    def test_all_required_fields_missing(self):
        validator = ConfigValidator(check_paths=False)
        result = validator.validate({})
        fields_with_errors = {e.field for e in result.errors}
        from app.beta.config.validation import REQUIRED_FIELDS
        for f in REQUIRED_FIELDS:
            assert f in fields_with_errors

    def test_invalid_port_adds_error(self, valid_env):
        valid_env["BETA_PORT"] = "80"
        validator = ConfigValidator(check_paths=False)
        result = validator.validate(valid_env)
        assert not result.is_valid
        assert any(e.field == "BETA_PORT" for e in result.errors)

    def test_short_jwt_secret_adds_error(self, valid_env):
        valid_env["BETA_JWT_SECRET"] = "short"
        validator = ConfigValidator(check_paths=False)
        result = validator.validate(valid_env)
        assert any(e.field == "BETA_JWT_SECRET" for e in result.errors)

    def test_bad_url_adds_error(self, valid_env):
        valid_env["BETA_NEXTCLOUD_URL"] = "not-a-url"
        validator = ConfigValidator(check_paths=False)
        result = validator.validate(valid_env)
        assert any(e.field == "BETA_NEXTCLOUD_URL" for e in result.errors)

    def test_invalid_timezone_adds_error(self, valid_env):
        valid_env["BETA_TIMEZONE"] = "Invalid/Zone"
        validator = ConfigValidator(check_paths=False)
        result = validator.validate(valid_env)
        assert any(e.field == "BETA_TIMEZONE" for e in result.errors)

    def test_bad_currency_adds_error(self, valid_env):
        valid_env["BETA_CURRENCY"] = "eur"
        validator = ConfigValidator(check_paths=False)
        result = validator.validate(valid_env)
        assert any(e.field == "BETA_CURRENCY" for e in result.errors)

    def test_bad_email_adds_error(self, valid_env):
        valid_env["BETA_ADMIN_EMAIL"] = "not-an-email"
        validator = ConfigValidator(check_paths=False)
        result = validator.validate(valid_env)
        assert any(e.field == "BETA_ADMIN_EMAIL" for e in result.errors)

    def test_production_env_adds_warning(self, valid_env):
        valid_env["BETA_ENV"] = "production"
        validator = ConfigValidator(check_paths=False)
        result = validator.validate(valid_env)
        assert result.warnings
        assert any("production" in w.lower() for w in result.warnings)

    def test_path_check_nonexistent_path(self, valid_env, tmp_path):
        valid_env["BETA_STORAGE_PATH"] = str(tmp_path / "does_not_exist")
        validator = ConfigValidator(check_paths=True)
        result = validator.validate(valid_env)
        assert any(e.field == "BETA_STORAGE_PATH" for e in result.errors)

    def test_path_check_skipped_when_disabled(self, valid_env, tmp_path):
        valid_env["BETA_STORAGE_PATH"] = str(tmp_path / "does_not_exist")
        valid_env["BETA_BACKUP_PATH"] = str(tmp_path / "also_not_exist")
        validator = ConfigValidator(check_paths=False)
        result = validator.validate(valid_env)
        assert not any(e.field in ("BETA_STORAGE_PATH", "BETA_BACKUP_PATH") for e in result.errors)

    def test_multiple_errors_collected(self, valid_env):
        valid_env["BETA_PORT"] = "not_a_port"
        valid_env["BETA_CURRENCY"] = "xx"
        valid_env["BETA_TIMEZONE"] = "BadZone"
        validator = ConfigValidator(check_paths=False)
        result = validator.validate(valid_env)
        assert len(result.errors) >= 3
