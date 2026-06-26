"""Tests for wooprice health command."""

from pathlib import Path

from typer.testing import CliRunner
from cli.main import app

runner = CliRunner()


class TestHealthCommand:
    def test_health_help_exits_zero(self):
        result = runner.invoke(app, ["health", "--help"])
        assert result.exit_code == 0

    def test_health_without_env_shows_checks(self, tmp_path: Path):
        result = runner.invoke(app, ["health", "--env-file", str(tmp_path / "missing.env")])
        # Exits 1 because env file not found, but still shows check results
        assert "Python" in result.output or "check" in result.output.lower()

    def test_health_with_valid_env_shows_python_check(self, valid_env_file: Path):
        result = runner.invoke(app, ["health", "--env-file", str(valid_env_file)])
        assert "Python" in result.output

    def test_health_with_valid_env_shows_import_checks(self, valid_env_file: Path):
        result = runner.invoke(app, ["health", "--env-file", str(valid_env_file)])
        assert "Import" in result.output or "import" in result.output.lower()

    def test_health_with_valid_env_config_check(self, valid_env_file: Path):
        result = runner.invoke(app, ["health", "--env-file", str(valid_env_file)])
        assert "Config" in result.output

    def test_health_does_not_print_secrets(self, valid_env_file: Path):
        result = runner.invoke(app, ["health", "--env-file", str(valid_env_file)])
        assert "a" * 86 not in result.output
        assert "b" * 64 not in result.output
        assert "test_pg_pass" not in result.output
        assert "test_nc_pass" not in result.output

    def test_health_json_exits_zero_with_valid_config(self, valid_env_file: Path):
        import json
        result = runner.invoke(app, ["health", "--env-file", str(valid_env_file), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "all_passed" in data
        assert "checks" in data
        assert isinstance(data["checks"], list)

    def test_health_no_network_calls(self, valid_env_file: Path):
        import unittest.mock as mock
        with mock.patch("socket.socket") as mock_socket:
            runner.invoke(app, ["health", "--env-file", str(valid_env_file)])
            mock_socket.assert_not_called()

    def test_health_no_docker_execution(self, valid_env_file: Path):
        import subprocess
        import unittest.mock as mock
        with mock.patch.object(subprocess, "run") as mock_run:
            runner.invoke(app, ["health", "--env-file", str(valid_env_file)])
            mock_run.assert_not_called()
