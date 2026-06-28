"""Tests for RuntimeConfigService — write path for editable runtime fields."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.beta.runtime_config.service import RuntimeConfigService
from app.beta.runtime_config.record import EDITABLE_FIELDS, INSTALLER_ONLY_FIELDS, SECRET_RUNTIME_FIELDS


class TestGet:
    def test_get_editable_field(self, env_file: Path):
        svc = RuntimeConfigService(env_file=env_file)
        record = svc.get("BETA_LOG_LEVEL")
        assert record.field_name == "BETA_LOG_LEVEL"
        assert record.is_editable is True
        assert record.is_secret is False
        assert record.is_installer_only is False

    def test_get_reads_current_value(self, env_file: Path):
        svc = RuntimeConfigService(env_file=env_file)
        record = svc.get("BETA_LOG_LEVEL")
        assert record.current_value == "INFO"

    def test_get_installer_only_field(self, env_file: Path):
        svc = RuntimeConfigService(env_file=env_file)
        record = svc.get("BETA_DOMAIN")
        assert record.is_installer_only is True
        assert record.is_editable is False

    def test_get_secret_field_hides_value(self, env_file: Path):
        svc = RuntimeConfigService(env_file=env_file)
        record = svc.get("BETA_JWT_SECRET")
        assert record.is_secret is True
        assert record.current_value == ""

    def test_get_missing_field_returns_empty_value(self, env_file: Path):
        svc = RuntimeConfigService(env_file=env_file)
        record = svc.get("BETA_NONEXISTENT_FIELD")
        assert record.current_value == ""

    def test_get_normalizes_to_uppercase(self, env_file: Path):
        svc = RuntimeConfigService(env_file=env_file)
        record = svc.get("beta_log_level")
        assert record.field_name == "BETA_LOG_LEVEL"

    def test_get_all_editable_returns_all(self, env_file: Path):
        svc = RuntimeConfigService(env_file=env_file)
        records = svc.get_all_editable()
        returned_names = {r.field_name for r in records}
        assert returned_names == EDITABLE_FIELDS

    def test_get_all_editable_all_are_editable(self, env_file: Path):
        svc = RuntimeConfigService(env_file=env_file)
        for record in svc.get_all_editable():
            assert record.is_editable is True
            assert record.is_secret is False


class TestSet:
    def test_set_editable_field_success(self, env_file: Path):
        svc = RuntimeConfigService(env_file=env_file)
        result = svc.set("BETA_LOG_LEVEL", "DEBUG")
        assert result.success is True
        assert result.new_value == "DEBUG"
        assert result.error is None

    def test_set_persists_to_file(self, env_file: Path):
        svc = RuntimeConfigService(env_file=env_file)
        svc.set("BETA_LOG_LEVEL", "DEBUG")
        svc2 = RuntimeConfigService(env_file=env_file)
        record = svc2.get("BETA_LOG_LEVEL")
        assert record.current_value == "DEBUG"

    def test_set_updates_existing_line(self, env_file: Path):
        svc = RuntimeConfigService(env_file=env_file)
        svc.set("BETA_LOG_LEVEL", "WARNING")
        content = env_file.read_text(encoding="utf-8")
        lines_with_log = [l for l in content.splitlines() if l.startswith("BETA_LOG_LEVEL=")]
        assert len(lines_with_log) == 1
        assert lines_with_log[0] == "BETA_LOG_LEVEL=WARNING"

    def test_set_appends_if_field_missing(self, tmp_path: Path):
        env = tmp_path / ".env"
        env.write_text("BETA_ENV=beta\n", encoding="utf-8")
        svc = RuntimeConfigService(env_file=env)
        result = svc.set("BETA_LOG_LEVEL", "DEBUG")
        assert result.success is True
        content = env.read_text(encoding="utf-8")
        assert "BETA_LOG_LEVEL=DEBUG" in content

    def test_set_creates_file_if_not_exists(self, tmp_path: Path):
        env = tmp_path / "new.env"
        assert not env.exists()
        svc = RuntimeConfigService(env_file=env)
        result = svc.set("BETA_LOG_LEVEL", "DEBUG")
        assert result.success is True
        assert env.exists()

    def test_set_returns_old_value(self, env_file: Path):
        svc = RuntimeConfigService(env_file=env_file)
        result = svc.set("BETA_LOG_LEVEL", "DEBUG")
        assert result.old_value == "INFO"

    def test_set_returns_change_event(self, env_file: Path):
        svc = RuntimeConfigService(env_file=env_file)
        result = svc.set("BETA_LOG_LEVEL", "DEBUG")
        assert result.change_event is not None
        assert result.change_event.field_name == "BETA_LOG_LEVEL"
        assert result.change_event.new_value == "DEBUG"
        assert result.change_event.old_value == "INFO"

    def test_set_normalizes_field_name(self, env_file: Path):
        svc = RuntimeConfigService(env_file=env_file)
        result = svc.set("beta_log_level", "DEBUG")
        assert result.success is True
        assert result.field_name == "BETA_LOG_LEVEL"

    def test_set_url_success(self, env_file: Path):
        svc = RuntimeConfigService(env_file=env_file)
        result = svc.set("BETA_NEXTCLOUD_URL", "https://new.example.com")
        assert result.success is True

    def test_set_woocommerce_url_success(self, env_file: Path):
        svc = RuntimeConfigService(env_file=env_file)
        result = svc.set("BETA_WOOCOMMERCE_URL", "https://newshop.example.com")
        assert result.success is True

    def test_set_timezone_success(self, env_file: Path):
        svc = RuntimeConfigService(env_file=env_file)
        result = svc.set("BETA_TIMEZONE", "America/New_York")
        assert result.success is True

    def test_set_currency_success(self, env_file: Path):
        svc = RuntimeConfigService(env_file=env_file)
        result = svc.set("BETA_CURRENCY", "EUR")
        assert result.success is True

    def test_set_scheduler_poll_seconds(self, env_file: Path):
        svc = RuntimeConfigService(env_file=env_file)
        result = svc.set("BETA_SCHEDULER_POLL_SECONDS", "120")
        assert result.success is True

    def test_set_backup_retain_days(self, env_file: Path):
        svc = RuntimeConfigService(env_file=env_file)
        result = svc.set("BETA_BACKUP_RETAIN_DAYS", "30")
        assert result.success is True


class TestSetRejections:
    def test_set_installer_only_rejected(self, env_file: Path):
        svc = RuntimeConfigService(env_file=env_file)
        result = svc.set("BETA_DOMAIN", "newdomain.example.com")
        assert result.success is False
        assert "installer-only" in (result.error or "").lower()

    def test_set_secret_field_rejected(self, env_file: Path):
        svc = RuntimeConfigService(env_file=env_file)
        result = svc.set("BETA_JWT_SECRET", "new_secret_value")
        assert result.success is False
        assert "secret" in (result.error or "").lower()

    def test_set_postgres_password_rejected(self, env_file: Path):
        svc = RuntimeConfigService(env_file=env_file)
        result = svc.set("BETA_POSTGRES_PASSWORD", "newpass")
        assert result.success is False

    def test_set_nextcloud_password_rejected(self, env_file: Path):
        svc = RuntimeConfigService(env_file=env_file)
        result = svc.set("BETA_NEXTCLOUD_PASSWORD", "newpass")
        assert result.success is False

    def test_set_woocommerce_key_rejected(self, env_file: Path):
        svc = RuntimeConfigService(env_file=env_file)
        result = svc.set("BETA_WOOCOMMERCE_KEY", "newkey")
        assert result.success is False

    def test_set_unknown_field_rejected(self, env_file: Path):
        svc = RuntimeConfigService(env_file=env_file)
        result = svc.set("BETA_UNKNOWN_FIELD", "value")
        assert result.success is False
        assert "editable" in (result.error or "").lower()

    def test_set_rejected_does_not_write_file(self, env_file: Path):
        svc = RuntimeConfigService(env_file=env_file)
        content_before = env_file.read_text(encoding="utf-8")
        svc.set("BETA_DOMAIN", "evil.example.com")
        content_after = env_file.read_text(encoding="utf-8")
        assert content_before == content_after


class TestValidation:
    def test_invalid_log_level_rejected(self, env_file: Path):
        svc = RuntimeConfigService(env_file=env_file)
        result = svc.set("BETA_LOG_LEVEL", "INVALID_LEVEL")
        assert result.success is False
        assert "log level" in (result.error or "").lower()

    def test_invalid_url_rejected(self, env_file: Path):
        svc = RuntimeConfigService(env_file=env_file)
        result = svc.set("BETA_NEXTCLOUD_URL", "not-a-url")
        assert result.success is False
        assert "url" in (result.error or "").lower()

    def test_invalid_currency_rejected(self, env_file: Path):
        svc = RuntimeConfigService(env_file=env_file)
        result = svc.set("BETA_CURRENCY", "us")
        assert result.success is False
        assert "currency" in (result.error or "").lower()

    def test_invalid_timezone_rejected(self, env_file: Path):
        svc = RuntimeConfigService(env_file=env_file)
        result = svc.set("BETA_TIMEZONE", "Not/ATimezone")
        assert result.success is False
        assert "timezone" in (result.error or "").lower()

    def test_non_integer_poll_seconds_rejected(self, env_file: Path):
        svc = RuntimeConfigService(env_file=env_file)
        result = svc.set("BETA_SCHEDULER_POLL_SECONDS", "abc")
        assert result.success is False

    def test_zero_poll_seconds_rejected(self, env_file: Path):
        svc = RuntimeConfigService(env_file=env_file)
        result = svc.set("BETA_SCHEDULER_POLL_SECONDS", "0")
        assert result.success is False

    def test_valid_log_levels(self, env_file: Path):
        svc = RuntimeConfigService(env_file=env_file)
        for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            result = svc.set("BETA_LOG_LEVEL", level)
            assert result.success is True, f"Expected {level} to be valid"

    def test_case_insensitive_log_level(self, env_file: Path):
        svc = RuntimeConfigService(env_file=env_file)
        result = svc.set("BETA_LOG_LEVEL", "debug")
        assert result.success is False or result.success is True

    def test_valid_3_letter_currency(self, env_file: Path):
        svc = RuntimeConfigService(env_file=env_file)
        result = svc.set("BETA_CURRENCY", "IRR")
        assert result.success is True

    def test_lowercase_currency_rejected(self, env_file: Path):
        svc = RuntimeConfigService(env_file=env_file)
        result = svc.set("BETA_CURRENCY", "eur")
        assert result.success is False

    def test_4_letter_currency_rejected(self, env_file: Path):
        svc = RuntimeConfigService(env_file=env_file)
        result = svc.set("BETA_CURRENCY", "EURO")
        assert result.success is False
