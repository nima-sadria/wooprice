"""Tests for app.beta.config.loader."""

import os

import pytest

from app.beta.config.loader import ConfigurationError, EnvironmentLoader


class TestEnvironmentLoader:
    def test_load_from_process_env(self, monkeypatch):
        monkeypatch.setenv("BETA_TEST_VAR_LOADER", "value_from_env")
        loader = EnvironmentLoader()
        result = loader.load()
        assert result.get("BETA_TEST_VAR_LOADER") == "value_from_env"

    def test_process_env_overrides_dotenv(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("BETA_DOMAIN=from_file\n", encoding="utf-8")
        monkeypatch.setenv("BETA_DOMAIN", "from_process")
        loader = EnvironmentLoader()
        result = loader.load(env_file=env_file)
        assert result["BETA_DOMAIN"] == "from_process"

    def test_load_from_dotenv_file(self, tmp_path, monkeypatch):
        monkeypatch.delenv("BETA_DOMAIN", raising=False)
        env_file = tmp_path / ".env"
        env_file.write_text("BETA_DOMAIN=from_file_only\n", encoding="utf-8")
        loader = EnvironmentLoader()
        result = loader.load(env_file=env_file)
        assert result.get("BETA_DOMAIN") == "from_file_only"

    def test_missing_env_file_raises(self, tmp_path):
        loader = EnvironmentLoader()
        with pytest.raises(ConfigurationError, match="not found"):
            loader.load(env_file=tmp_path / "nonexistent.env")

    def test_load_beta_only_filters_prefix(self, monkeypatch):
        monkeypatch.setenv("BETA_FILTERED_VAR_XYZ", "beta_val")
        monkeypatch.setenv("OTHER_FILTERED_VAR_XYZ", "non_beta_val")
        loader = EnvironmentLoader()
        result = loader.load_beta_only()
        assert "BETA_FILTERED_VAR_XYZ" in result
        assert "OTHER_FILTERED_VAR_XYZ" not in result

    def test_load_manual_dotenv_fallback(self, tmp_path, monkeypatch):
        # Test the fallback manual parser (no-dotenv path)
        env_file = tmp_path / ".env"
        env_file.write_text(
            '# comment\nBETA_MANUAL_KEY=manual_value\nBETA_QUOTED_KEY="quoted"\n',
            encoding="utf-8",
        )
        monkeypatch.delenv("BETA_MANUAL_KEY", raising=False)
        monkeypatch.delenv("BETA_QUOTED_KEY", raising=False)
        result = EnvironmentLoader._load_dotenv_file(env_file)
        assert result.get("BETA_MANUAL_KEY") == "manual_value"
        assert result.get("BETA_QUOTED_KEY") == "quoted"
