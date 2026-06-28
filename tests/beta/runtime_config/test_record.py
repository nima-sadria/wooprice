"""Tests for ConfigRecord and ConfigChangeEvent models."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.beta.runtime_config.record import (
    EDITABLE_FIELDS,
    INSTALLER_ONLY_FIELDS,
    SECRET_RUNTIME_FIELDS,
    ConfigChangeEvent,
    ConfigRecord,
)


class TestFieldSets:
    def test_editable_fields_non_empty(self):
        assert len(EDITABLE_FIELDS) >= 5

    def test_installer_only_fields_non_empty(self):
        assert len(INSTALLER_ONLY_FIELDS) >= 5

    def test_secret_fields_non_empty(self):
        assert len(SECRET_RUNTIME_FIELDS) >= 5

    def test_no_overlap_editable_installer(self):
        assert EDITABLE_FIELDS.isdisjoint(INSTALLER_ONLY_FIELDS)

    def test_no_overlap_editable_secret(self):
        assert EDITABLE_FIELDS.isdisjoint(SECRET_RUNTIME_FIELDS)

    def test_no_overlap_installer_secret(self):
        assert INSTALLER_ONLY_FIELDS.isdisjoint(SECRET_RUNTIME_FIELDS)

    def test_known_editable_fields(self):
        assert "BETA_LOG_LEVEL" in EDITABLE_FIELDS
        assert "BETA_NEXTCLOUD_URL" in EDITABLE_FIELDS
        assert "BETA_WOOCOMMERCE_URL" in EDITABLE_FIELDS
        assert "BETA_TIMEZONE" in EDITABLE_FIELDS
        assert "BETA_CURRENCY" in EDITABLE_FIELDS

    def test_known_installer_fields(self):
        assert "BETA_DOMAIN" in INSTALLER_ONLY_FIELDS
        assert "BETA_PORT" in INSTALLER_ONLY_FIELDS
        assert "BETA_DATABASE_URL" in INSTALLER_ONLY_FIELDS

    def test_known_secret_fields(self):
        assert "BETA_JWT_SECRET" in SECRET_RUNTIME_FIELDS
        assert "BETA_POSTGRES_PASSWORD" in SECRET_RUNTIME_FIELDS
        assert "BETA_NEXTCLOUD_PASSWORD" in SECRET_RUNTIME_FIELDS
        assert "BETA_WOOCOMMERCE_KEY" in SECRET_RUNTIME_FIELDS
        assert "BETA_WOOCOMMERCE_SECRET" in SECRET_RUNTIME_FIELDS


class TestConfigRecord:
    def test_to_dict_hides_secret_value(self):
        record = ConfigRecord(
            field_name="BETA_JWT_SECRET",
            current_value="actual_secret_value",
            is_editable=False,
            is_secret=True,
            is_installer_only=False,
        )
        d = record.to_dict()
        assert d["current_value"] == "[REDACTED]"
        assert "actual_secret_value" not in str(d)

    def test_to_dict_shows_non_secret_value(self):
        record = ConfigRecord(
            field_name="BETA_LOG_LEVEL",
            current_value="DEBUG",
            is_editable=True,
            is_secret=False,
            is_installer_only=False,
        )
        d = record.to_dict()
        assert d["current_value"] == "DEBUG"

    def test_to_dict_has_required_keys(self):
        record = ConfigRecord(
            field_name="BETA_LOG_LEVEL",
            current_value="INFO",
            is_editable=True,
            is_secret=False,
            is_installer_only=False,
        )
        d = record.to_dict()
        for key in ("field_name", "current_value", "is_editable", "is_secret", "is_installer_only"):
            assert key in d

    def test_editable_flag_correct(self):
        record = ConfigRecord(
            field_name="BETA_TIMEZONE",
            current_value="UTC",
            is_editable=True,
            is_secret=False,
            is_installer_only=False,
        )
        assert record.is_editable is True

    def test_installer_only_flag_correct(self):
        record = ConfigRecord(
            field_name="BETA_DOMAIN",
            current_value="example.com",
            is_editable=False,
            is_secret=False,
            is_installer_only=True,
        )
        assert record.is_installer_only is True
        d = record.to_dict()
        assert d["is_installer_only"] is True


class TestConfigChangeEvent:
    def test_to_dict_hides_secret_field(self):
        event = ConfigChangeEvent(
            field_name="BETA_JWT_SECRET",
            old_value="old_secret",
            new_value="new_secret",
        )
        d = event.to_dict()
        assert d["old_value"] == "[REDACTED]"
        assert d["new_value"] == "[REDACTED]"
        assert "old_secret" not in str(d)
        assert "new_secret" not in str(d)

    def test_to_dict_shows_non_secret_values(self):
        event = ConfigChangeEvent(
            field_name="BETA_LOG_LEVEL",
            old_value="INFO",
            new_value="DEBUG",
        )
        d = event.to_dict()
        assert d["old_value"] == "INFO"
        assert d["new_value"] == "DEBUG"

    def test_to_dict_has_required_keys(self):
        event = ConfigChangeEvent(
            field_name="BETA_LOG_LEVEL",
            old_value="INFO",
            new_value="DEBUG",
        )
        d = event.to_dict()
        for key in ("field_name", "old_value", "new_value", "changed_at", "changed_by"):
            assert key in d

    def test_changed_by_default_is_cli(self):
        event = ConfigChangeEvent(field_name="BETA_LOG_LEVEL", old_value="INFO", new_value="DEBUG")
        assert event.changed_by == "cli"

    def test_changed_at_is_utc(self):
        event = ConfigChangeEvent(field_name="BETA_LOG_LEVEL", old_value="INFO", new_value="DEBUG")
        assert event.changed_at.tzinfo is not None

    def test_old_value_can_be_none(self):
        event = ConfigChangeEvent(
            field_name="BETA_LOG_LEVEL",
            old_value=None,
            new_value="DEBUG",
        )
        d = event.to_dict()
        assert d["old_value"] is None
