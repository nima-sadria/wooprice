"""Tests for wooprice configure show and verify commands."""

from pathlib import Path

from typer.testing import CliRunner
from cli.main import app

runner = CliRunner()


class TestConfigureShow:
    def test_show_help_exits_zero(self):
        result = runner.invoke(app, ["configure", "show", "--help"])
        assert result.exit_code == 0

    def test_show_with_valid_env_exits_zero(self, valid_env_file: Path):
        result = runner.invoke(app, ["configure", "show", "--env-file", str(valid_env_file)])
        assert result.exit_code == 0

    def test_show_displays_domain(self, valid_env_file: Path):
        result = runner.invoke(app, ["configure", "show", "--env-file", str(valid_env_file)])
        assert "test.example.com" in result.output

    def test_show_displays_beta_env(self, valid_env_file: Path):
        result = runner.invoke(app, ["configure", "show", "--env-file", str(valid_env_file)])
        assert "beta" in result.output.lower()

    def test_show_redacts_jwt_secret(self, valid_env_file: Path):
        result = runner.invoke(app, ["configure", "show", "--env-file", str(valid_env_file)])
        assert "a" * 86 not in result.output
        assert "[REDACTED]" in result.output

    def test_show_redacts_rest_api_secret(self, valid_env_file: Path):
        result = runner.invoke(app, ["configure", "show", "--env-file", str(valid_env_file)])
        assert "b" * 64 not in result.output

    def test_show_redacts_postgres_password(self, valid_env_file: Path):
        result = runner.invoke(app, ["configure", "show", "--env-file", str(valid_env_file)])
        assert "test_pg_pass_secure" not in result.output

    def test_show_redacts_nextcloud_password(self, valid_env_file: Path):
        result = runner.invoke(app, ["configure", "show", "--env-file", str(valid_env_file)])
        assert "test_nc_pass" not in result.output

    def test_show_redacts_woocommerce_key(self, valid_env_file: Path):
        result = runner.invoke(app, ["configure", "show", "--env-file", str(valid_env_file)])
        assert "ck_test_key_secure_deadbeef" not in result.output

    def test_show_without_env_exits_nonzero(self, tmp_path: Path):
        result = runner.invoke(app, ["configure", "show", "--env-file", str(tmp_path / "missing.env")])
        assert result.exit_code != 0

    def test_show_json_exits_zero(self, valid_env_file: Path):
        import json
        result = runner.invoke(app, ["configure", "show", "--env-file", str(valid_env_file), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, dict)

    def test_show_json_secrets_are_redacted(self, valid_env_file: Path):
        import json
        result = runner.invoke(app, ["configure", "show", "--env-file", str(valid_env_file), "--json"])
        data = json.loads(result.output)
        for field in ["BETA_JWT_SECRET", "BETA_REST_API_SECRET", "BETA_POSTGRES_PASSWORD",
                      "BETA_NEXTCLOUD_PASSWORD", "BETA_WOOCOMMERCE_KEY", "BETA_WOOCOMMERCE_SECRET"]:
            if field in data:
                assert data[field] == "[REDACTED]", f"{field} was not redacted"


class TestConfigureVerify:
    def test_verify_help_exits_zero(self):
        result = runner.invoke(app, ["configure", "verify", "--help"])
        assert result.exit_code == 0

    def test_verify_with_valid_env_exits_zero(self, valid_env_file: Path):
        result = runner.invoke(app, ["configure", "verify", "--env-file", str(valid_env_file)])
        assert result.exit_code == 0

    def test_verify_valid_config_shows_valid(self, valid_env_file: Path):
        result = runner.invoke(app, ["configure", "verify", "--env-file", str(valid_env_file)])
        assert "valid" in result.output.lower()

    def test_verify_empty_config_exits_nonzero(self, empty_env_file: Path):
        result = runner.invoke(app, ["configure", "verify", "--env-file", str(empty_env_file)])
        assert result.exit_code != 0

    def test_verify_empty_config_shows_errors(self, empty_env_file: Path):
        result = runner.invoke(app, ["configure", "verify", "--env-file", str(empty_env_file)])
        assert "error" in result.output.lower() or "✗" in result.output

    def test_verify_never_prints_secret_values(self, valid_env_file: Path):
        result = runner.invoke(app, ["configure", "verify", "--env-file", str(valid_env_file)])
        assert "a" * 86 not in result.output
        assert "b" * 64 not in result.output
        assert "test_pg_pass" not in result.output

    def test_verify_json_valid_exits_zero(self, valid_env_file: Path):
        import json
        result = runner.invoke(app, ["configure", "verify", "--env-file", str(valid_env_file), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["valid"] is True

    def test_verify_json_invalid_exits_nonzero(self, empty_env_file: Path):
        import json
        result = runner.invoke(app, ["configure", "verify", "--env-file", str(empty_env_file), "--json"])
        assert result.exit_code != 0
        data = json.loads(result.output)
        assert data["valid"] is False
        assert data["error_count"] > 0
