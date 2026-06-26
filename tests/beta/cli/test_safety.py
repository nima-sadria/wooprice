"""Safety tests for CLI — no secrets, no network, no Docker, no production hardcoding."""

import ast
from pathlib import Path

from typer.testing import CliRunner
from cli.main import app

runner = CliRunner()

_CLI_SOURCE_FILES = list(Path("cli").rglob("*.py"))

_FORBIDDEN_PRODUCTION_VALUES = [
    "woo.softpple",
    "softpple.business",
    "nextcloud.softpple",
    "192.168.1.",
    "10.0.0.",
]

_FORBIDDEN_CREDENTIAL_PATTERNS = [
    "ck_live_",
    "cs_live_",
]


class TestNoSecretsInOutput:
    def test_status_no_raw_secrets(self, valid_env_file: Path):
        result = runner.invoke(app, ["status", "--env-file", str(valid_env_file)])
        # JWT secret is 86 'a' chars
        assert "a" * 50 not in result.output
        # REST secret is 64 'b' chars
        assert "b" * 50 not in result.output
        assert "test_pg_pass_secure" not in result.output

    def test_configure_show_no_raw_secrets(self, valid_env_file: Path):
        result = runner.invoke(app, ["configure", "show", "--env-file", str(valid_env_file)])
        assert "a" * 50 not in result.output
        assert "b" * 50 not in result.output
        assert "test_nc_pass_secure" not in result.output

    def test_install_dry_run_no_raw_secrets(self, valid_env_file: Path, tmp_path: Path):
        result = runner.invoke(app, [
            "install", "dry-run",
            "--env-file", str(valid_env_file),
            "--install-dir", str(tmp_path / "install"),
        ])
        assert "a" * 50 not in result.output
        assert "b" * 50 not in result.output

    def test_diagnostics_no_raw_secrets(self, valid_env_file: Path):
        result = runner.invoke(app, ["diagnostics", "--env-file", str(valid_env_file)])
        assert "a" * 50 not in result.output
        assert "b" * 50 not in result.output
        assert "test_pg_pass" not in result.output


class TestNoProductionHardcoding:
    def test_no_production_domains_in_cli_source(self):
        for src_file in _CLI_SOURCE_FILES:
            source = src_file.read_text(encoding="utf-8")
            for forbidden in _FORBIDDEN_PRODUCTION_VALUES:
                assert forbidden not in source, (
                    f"Production value '{forbidden}' found in {src_file}"
                )

    def test_no_production_credentials_in_cli_source(self):
        for src_file in _CLI_SOURCE_FILES:
            source = src_file.read_text(encoding="utf-8")
            for pattern in _FORBIDDEN_CREDENTIAL_PATTERNS:
                assert pattern not in source, (
                    f"Production credential pattern '{pattern}' found in {src_file}"
                )


class TestNoDockerExecution:
    def test_no_docker_sdk_import_in_cli(self):
        for src_file in _CLI_SOURCE_FILES:
            source = src_file.read_text(encoding="utf-8")
            assert "import docker" not in source, f"Docker SDK import in {src_file}"
            assert "from docker" not in source, f"Docker SDK import in {src_file}"

    def test_no_subprocess_docker_calls_in_cli(self):
        for src_file in _CLI_SOURCE_FILES:
            source = src_file.read_text(encoding="utf-8")
            assert "subprocess.run" not in source, f"subprocess.run in {src_file}"
            assert "subprocess.Popen" not in source, f"subprocess.Popen in {src_file}"
            assert "subprocess.call" not in source, f"subprocess.call in {src_file}"


class TestNoNetworkCalls:
    def test_no_requests_import_in_cli(self):
        for src_file in _CLI_SOURCE_FILES:
            source = src_file.read_text(encoding="utf-8")
            assert "import requests" not in source, f"requests import in {src_file}"
            assert "import httpx" not in source, f"httpx import in {src_file}"
            assert "import urllib.request" not in source, f"urllib.request import in {src_file}"

    def test_no_socket_import_in_cli(self):
        for src_file in _CLI_SOURCE_FILES:
            source = src_file.read_text(encoding="utf-8")
            assert "import socket" not in source, f"socket import in {src_file}"


class TestNoA2Imports:
    def test_cli_does_not_import_a2(self):
        for src_file in _CLI_SOURCE_FILES:
            source = src_file.read_text(encoding="utf-8")
            assert "from app.a2" not in source, f"A2 import in {src_file}"
            assert "import app.a2" not in source, f"A2 import in {src_file}"


class TestProductionProfileBlocks:
    def test_production_blocks_install_dry_run(self, production_env_file: Path, tmp_path: Path):
        result = runner.invoke(app, [
            "install", "dry-run",
            "--env-file", str(production_env_file),
            "--install-dir", str(tmp_path / "install"),
        ])
        assert result.exit_code != 0

    def test_production_status_still_works(self, production_env_file: Path):
        result = runner.invoke(app, ["status", "--env-file", str(production_env_file)])
        # Status is read-only; must not be blocked
        assert result.exit_code == 0

    def test_production_health_still_works(self, production_env_file: Path):
        result = runner.invoke(app, ["health", "--env-file", str(production_env_file)])
        # Health is read-only — exit code can be 0 or 1 depending on storage path
        # but must not error out on the profile check itself
        assert result.exit_code in (0, 1)

    def test_production_diagnostics_still_works(self, production_env_file: Path):
        result = runner.invoke(app, ["diagnostics", "--env-file", str(production_env_file)])
        assert result.exit_code == 0

    def test_production_configure_show_still_works(self, production_env_file: Path):
        result = runner.invoke(app, ["configure", "show", "--env-file", str(production_env_file)])
        # configure show is read-only
        assert result.exit_code == 0


class TestEnvGuard:
    def test_require_beta_env_raises_for_production(self):
        from cli.shared.env_guard import require_beta_env, ProductionResourceError
        from app.beta.config import ConfigProfile
        try:
            require_beta_env(ConfigProfile.PRODUCTION)
            assert False, "Should have raised ProductionResourceError"
        except ProductionResourceError:
            pass

    def test_require_beta_env_passes_for_beta(self):
        from cli.shared.env_guard import require_beta_env
        from app.beta.config import ConfigProfile
        require_beta_env(ConfigProfile.BETA)  # Must not raise

    def test_require_beta_env_passes_for_dev(self):
        from cli.shared.env_guard import require_beta_env
        from app.beta.config import ConfigProfile
        require_beta_env(ConfigProfile.DEV)  # Must not raise
