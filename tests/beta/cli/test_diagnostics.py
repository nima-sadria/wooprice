"""Tests for wooprice diagnostics command."""

from pathlib import Path

from typer.testing import CliRunner
from cli.main import app

runner = CliRunner()


class TestDiagnosticsCommand:
    def test_diagnostics_help_exits_zero(self):
        result = runner.invoke(app, ["diagnostics", "--help"])
        assert result.exit_code == 0

    def test_diagnostics_without_env_exits_zero(self, tmp_path: Path):
        result = runner.invoke(app, ["diagnostics", "--env-file", str(tmp_path / "missing.env")])
        assert result.exit_code == 0

    def test_diagnostics_with_valid_env_exits_zero(self, valid_env_file: Path):
        result = runner.invoke(app, ["diagnostics", "--env-file", str(valid_env_file)])
        assert result.exit_code == 0

    def test_diagnostics_shows_python_version(self, valid_env_file: Path):
        result = runner.invoke(app, ["diagnostics", "--env-file", str(valid_env_file)])
        assert "Python" in result.output

    def test_diagnostics_shows_profile(self, valid_env_file: Path):
        result = runner.invoke(app, ["diagnostics", "--env-file", str(valid_env_file)])
        assert "beta" in result.output.lower()

    def test_diagnostics_shows_secret_status_not_values(self, valid_env_file: Path):
        result = runner.invoke(app, ["diagnostics", "--env-file", str(valid_env_file)])
        # Must show "set" or "not set" but NOT actual secret values
        assert "set" in result.output.lower()
        # Never print actual secrets
        assert "a" * 86 not in result.output
        assert "b" * 64 not in result.output

    def test_diagnostics_redacts_secret_values(self, valid_env_file: Path):
        result = runner.invoke(app, ["diagnostics", "--env-file", str(valid_env_file)])
        assert "test_pg_pass_secure" not in result.output
        assert "test_nc_pass" not in result.output

    def test_diagnostics_shows_prerequisite_summary(self, valid_env_file: Path):
        result = runner.invoke(app, ["diagnostics", "--env-file", str(valid_env_file)])
        assert "Prerequisite" in result.output or "Python" in result.output

    def test_diagnostics_shows_validation_summary(self, valid_env_file: Path):
        result = runner.invoke(app, ["diagnostics", "--env-file", str(valid_env_file)])
        assert "valid" in result.output.lower() or "Validation" in result.output

    def test_diagnostics_json_exits_zero(self, valid_env_file: Path):
        import json
        result = runner.invoke(app, ["diagnostics", "--env-file", str(valid_env_file), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "python_version" in data
        assert "config_valid" in data
        assert "secret_status" in data
        assert "prerequisites" in data

    def test_diagnostics_json_secret_status_no_values(self, valid_env_file: Path):
        import json
        result = runner.invoke(app, ["diagnostics", "--env-file", str(valid_env_file), "--json"])
        data = json.loads(result.output)
        for field, status in data["secret_status"].items():
            assert status in ("set", "not set"), f"Unexpected secret status for {field}: {status!r}"
            # Ensure no actual secret values leaked
            assert len(status) < 20, f"Secret value may have leaked for {field}"

    def test_diagnostics_no_network_calls(self, valid_env_file: Path):
        import socket
        import unittest.mock as mock
        with mock.patch.object(socket, "socket") as mock_socket:
            runner.invoke(app, ["diagnostics", "--env-file", str(valid_env_file)])
            mock_socket.assert_not_called()
