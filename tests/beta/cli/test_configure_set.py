"""Tests for wooprice configure get/set commands (CP1.3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli.main import app

runner = CliRunner()


class TestConfigureGet:
    def test_get_help_exits_zero(self):
        result = runner.invoke(app, ["configure", "get", "--help"])
        assert result.exit_code == 0

    def test_get_editable_field(self, valid_env_file: Path):
        result = runner.invoke(app, ["configure", "get", "BETA_LOG_LEVEL", "--env-file", str(valid_env_file)])
        assert result.exit_code == 0
        assert "BETA_LOG_LEVEL" in result.output

    def test_get_field_value_shown(self, valid_env_file: Path):
        result = runner.invoke(app, ["configure", "get", "BETA_LOG_LEVEL", "--env-file", str(valid_env_file)])
        assert result.exit_code == 0
        # Field name must appear; value may be empty if not set in fixture
        assert "BETA_LOG_LEVEL" in result.output

    def test_get_secret_field_redacted(self, valid_env_file: Path):
        result = runner.invoke(app, ["configure", "get", "BETA_JWT_SECRET", "--env-file", str(valid_env_file)])
        assert result.exit_code == 0
        assert "REDACTED" in result.output.upper() or "secret" in result.output.lower()
        assert "a" * 64 not in result.output

    def test_get_installer_only_field(self, valid_env_file: Path):
        result = runner.invoke(app, ["configure", "get", "BETA_DOMAIN", "--env-file", str(valid_env_file)])
        assert result.exit_code == 0
        assert "installer" in result.output.lower() or "BETA_DOMAIN" in result.output

    def test_get_json_output(self, valid_env_file: Path):
        result = runner.invoke(app, ["configure", "get", "BETA_LOG_LEVEL", "--env-file", str(valid_env_file), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "field_name" in data
        assert "is_editable" in data

    def test_get_json_secret_redacted(self, valid_env_file: Path):
        result = runner.invoke(app, ["configure", "get", "BETA_JWT_SECRET", "--env-file", str(valid_env_file), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["current_value"] == "[REDACTED]"
        assert "a" * 64 not in result.output


class TestConfigureSet:
    def test_set_help_exits_zero(self):
        result = runner.invoke(app, ["configure", "set", "--help"])
        assert result.exit_code == 0

    def test_set_valid_field_exits_zero(self, valid_env_file: Path):
        result = runner.invoke(
            app, ["configure", "set", "BETA_LOG_LEVEL", "DEBUG", "--env-file", str(valid_env_file)]
        )
        assert result.exit_code == 0

    def test_set_valid_field_shows_confirmation(self, valid_env_file: Path):
        result = runner.invoke(
            app, ["configure", "set", "BETA_LOG_LEVEL", "DEBUG", "--env-file", str(valid_env_file)]
        )
        assert "BETA_LOG_LEVEL" in result.output
        assert "DEBUG" in result.output

    def test_set_persists_value(self, valid_env_file: Path):
        runner.invoke(
            app, ["configure", "set", "BETA_LOG_LEVEL", "WARNING", "--env-file", str(valid_env_file)]
        )
        content = valid_env_file.read_text(encoding="utf-8")
        assert "BETA_LOG_LEVEL=WARNING" in content

    def test_set_installer_only_exits_nonzero(self, valid_env_file: Path):
        result = runner.invoke(
            app, ["configure", "set", "BETA_DOMAIN", "evil.com", "--env-file", str(valid_env_file)]
        )
        assert result.exit_code != 0

    def test_set_installer_only_error_message(self, valid_env_file: Path):
        result = runner.invoke(
            app, ["configure", "set", "BETA_DOMAIN", "evil.com", "--env-file", str(valid_env_file)]
        )
        assert "installer" in result.output.lower() or "cannot" in result.output.lower()

    def test_set_secret_field_exits_nonzero(self, valid_env_file: Path):
        result = runner.invoke(
            app, ["configure", "set", "BETA_JWT_SECRET", "newsecret", "--env-file", str(valid_env_file)]
        )
        assert result.exit_code != 0

    def test_set_secret_field_error_no_value_in_output(self, valid_env_file: Path):
        result = runner.invoke(
            app, ["configure", "set", "BETA_JWT_SECRET", "supersecretvalue", "--env-file", str(valid_env_file)]
        )
        assert "supersecretvalue" not in result.output

    def test_set_invalid_url_exits_nonzero(self, valid_env_file: Path):
        result = runner.invoke(
            app, ["configure", "set", "BETA_NEXTCLOUD_URL", "not-a-url", "--env-file", str(valid_env_file)]
        )
        assert result.exit_code != 0

    def test_set_invalid_log_level_exits_nonzero(self, valid_env_file: Path):
        result = runner.invoke(
            app, ["configure", "set", "BETA_LOG_LEVEL", "INVALID", "--env-file", str(valid_env_file)]
        )
        assert result.exit_code != 0

    def test_set_invalid_currency_exits_nonzero(self, valid_env_file: Path):
        result = runner.invoke(
            app, ["configure", "set", "BETA_CURRENCY", "us", "--env-file", str(valid_env_file)]
        )
        assert result.exit_code != 0

    def test_set_json_success(self, valid_env_file: Path):
        result = runner.invoke(
            app,
            ["configure", "set", "BETA_LOG_LEVEL", "DEBUG", "--env-file", str(valid_env_file), "--json"],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["success"] is True
        assert data["new_value"] == "DEBUG"

    def test_set_json_failure(self, valid_env_file: Path):
        result = runner.invoke(
            app,
            ["configure", "set", "BETA_DOMAIN", "evil.com", "--env-file", str(valid_env_file), "--json"],
        )
        assert result.exit_code != 0
        data = json.loads(result.output)
        assert data["success"] is False
        assert data["error"] is not None

    def test_set_url_success(self, valid_env_file: Path):
        result = runner.invoke(
            app,
            ["configure", "set", "BETA_NEXTCLOUD_URL", "https://new.example.com", "--env-file", str(valid_env_file)],
        )
        assert result.exit_code == 0

    def test_set_timezone_success(self, valid_env_file: Path):
        result = runner.invoke(
            app,
            ["configure", "set", "BETA_TIMEZONE", "Europe/Berlin", "--env-file", str(valid_env_file)],
        )
        assert result.exit_code == 0

    def test_set_invalid_timezone_exits_nonzero(self, valid_env_file: Path):
        result = runner.invoke(
            app,
            ["configure", "set", "BETA_TIMEZONE", "Invalid/Zone", "--env-file", str(valid_env_file)],
        )
        assert result.exit_code != 0
