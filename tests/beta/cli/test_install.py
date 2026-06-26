"""Tests for wooprice install dry-run command."""

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner
from cli.main import app

runner = CliRunner()


class TestInstallDryRun:
    def test_dry_run_help_exits_zero(self):
        result = runner.invoke(app, ["install", "dry-run", "--help"])
        assert result.exit_code == 0

    def test_dry_run_exits_zero(self, valid_env_file: Path, tmp_path: Path):
        result = runner.invoke(app, [
            "install", "dry-run",
            "--env-file", str(valid_env_file),
            "--install-dir", str(tmp_path / "install"),
        ])
        assert result.exit_code == 0

    def test_dry_run_writes_nothing(self, valid_env_file: Path, tmp_path: Path):
        install_dir = tmp_path / "install"
        runner.invoke(app, [
            "install", "dry-run",
            "--env-file", str(valid_env_file),
            "--install-dir", str(install_dir),
        ])
        # Nothing should be written to install_dir
        assert not install_dir.exists()

    def test_dry_run_shows_planned_files(self, valid_env_file: Path, tmp_path: Path):
        result = runner.invoke(app, [
            "install", "dry-run",
            "--env-file", str(valid_env_file),
            "--install-dir", str(tmp_path / "install"),
        ])
        assert ".env" in result.output or "env" in result.output.lower()

    def test_dry_run_shows_planned_dirs(self, valid_env_file: Path, tmp_path: Path):
        result = runner.invoke(app, [
            "install", "dry-run",
            "--env-file", str(valid_env_file),
            "--install-dir", str(tmp_path / "install"),
        ])
        assert "storage" in result.output.lower() or "Directories" in result.output

    def test_dry_run_shows_validation_result(self, valid_env_file: Path, tmp_path: Path):
        result = runner.invoke(app, [
            "install", "dry-run",
            "--env-file", str(valid_env_file),
            "--install-dir", str(tmp_path / "install"),
        ])
        assert "valid" in result.output.lower() or "Validation" in result.output

    def test_dry_run_shows_nothing_written_message(self, valid_env_file: Path, tmp_path: Path):
        result = runner.invoke(app, [
            "install", "dry-run",
            "--env-file", str(valid_env_file),
            "--install-dir", str(tmp_path / "install"),
        ])
        assert "Nothing was written" in result.output or "dry-run" in result.output.lower()

    def test_dry_run_never_prints_raw_jwt_secret(self, valid_env_file: Path, tmp_path: Path):
        result = runner.invoke(app, [
            "install", "dry-run",
            "--env-file", str(valid_env_file),
            "--install-dir", str(tmp_path / "install"),
        ])
        assert "a" * 86 not in result.output

    def test_dry_run_never_prints_raw_rest_secret(self, valid_env_file: Path, tmp_path: Path):
        result = runner.invoke(app, [
            "install", "dry-run",
            "--env-file", str(valid_env_file),
            "--install-dir", str(tmp_path / "install"),
        ])
        assert "b" * 64 not in result.output

    def test_dry_run_shows_masked_secrets(self, valid_env_file: Path, tmp_path: Path):
        result = runner.invoke(app, [
            "install", "dry-run",
            "--env-file", str(valid_env_file),
            "--install-dir", str(tmp_path / "install"),
        ])
        assert "****" in result.output or "REDACTED" in result.output or "Secrets" in result.output

    def test_dry_run_calls_b4_logic(self, valid_env_file: Path, tmp_path: Path):
        from installer import installer_core
        original = installer_core.dry_run_install
        called = []

        def mock_dry_run(config, install_dir):
            called.append(True)
            return original(config, install_dir)

        with patch.object(installer_core, "dry_run_install", side_effect=mock_dry_run):
            runner.invoke(app, [
                "install", "dry-run",
                "--env-file", str(valid_env_file),
                "--install-dir", str(tmp_path / "install"),
            ])
        assert called, "dry_run_install was not called"

    def test_dry_run_no_subprocess_calls(self, valid_env_file: Path, tmp_path: Path):
        import subprocess
        with patch.object(subprocess, "run") as mock_run:
            runner.invoke(app, [
                "install", "dry-run",
                "--env-file", str(valid_env_file),
                "--install-dir", str(tmp_path / "install"),
            ])
            mock_run.assert_not_called()

    def test_production_profile_blocks_dry_run(self, production_env_file: Path, tmp_path: Path):
        result = runner.invoke(app, [
            "install", "dry-run",
            "--env-file", str(production_env_file),
            "--install-dir", str(tmp_path / "install"),
        ])
        assert result.exit_code != 0

    def test_production_block_message_shown(self, production_env_file: Path, tmp_path: Path):
        result = runner.invoke(app, [
            "install", "dry-run",
            "--env-file", str(production_env_file),
            "--install-dir", str(tmp_path / "install"),
        ])
        assert "PRODUCTION" in result.output or "blocked" in result.output.lower()
