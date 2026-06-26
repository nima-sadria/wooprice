"""Tests for wooprice status command."""

from pathlib import Path

from typer.testing import CliRunner
from cli.main import app

runner = CliRunner()


class TestStatusCommand:
    def test_status_without_env_file_exits_zero(self, tmp_path: Path):
        result = runner.invoke(app, ["status", "--env-file", str(tmp_path / ".env.missing")])
        assert result.exit_code == 0

    def test_status_shows_not_loaded_without_env(self, tmp_path: Path):
        result = runner.invoke(app, ["status", "--env-file", str(tmp_path / ".env.missing")])
        assert "NOT LOADED" in result.output or "not loaded" in result.output.lower()

    def test_status_with_valid_env_exits_zero(self, valid_env_file: Path):
        result = runner.invoke(app, ["status", "--env-file", str(valid_env_file)])
        assert result.exit_code == 0

    def test_status_with_valid_env_shows_loaded(self, valid_env_file: Path):
        result = runner.invoke(app, ["status", "--env-file", str(valid_env_file)])
        assert "LOADED" in result.output

    def test_status_with_valid_env_shows_profile(self, valid_env_file: Path):
        result = runner.invoke(app, ["status", "--env-file", str(valid_env_file)])
        assert "beta" in result.output.lower()

    def test_status_with_valid_env_shows_domain(self, valid_env_file: Path):
        result = runner.invoke(app, ["status", "--env-file", str(valid_env_file)])
        assert "test.example.com" in result.output

    def test_status_shows_storage_path(self, valid_env_file: Path):
        result = runner.invoke(app, ["status", "--env-file", str(valid_env_file)])
        assert "storage" in result.output.lower()

    def test_status_does_not_print_secrets(self, valid_env_file: Path):
        result = runner.invoke(app, ["status", "--env-file", str(valid_env_file)])
        assert "a" * 86 not in result.output
        assert "b" * 64 not in result.output
        assert "test_pg_pass" not in result.output

    def test_status_json_exits_zero(self, valid_env_file: Path):
        import json
        result = runner.invoke(app, ["status", "--env-file", str(valid_env_file), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "config_loaded" in data
        assert "profile" in data

    def test_status_json_has_no_secret_values(self, valid_env_file: Path):
        import json
        result = runner.invoke(app, ["status", "--env-file", str(valid_env_file), "--json"])
        data = json.loads(result.output)
        output_str = json.dumps(data)
        assert "a" * 86 not in output_str
        assert "b" * 64 not in output_str
