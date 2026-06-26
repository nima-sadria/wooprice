"""Tests for dry-run installation mode."""

from pathlib import Path

import pytest

from installer.installer_core import (
    DryRunResult,
    InstallerConfig,
    dry_run_install,
)


class TestDryRunInstall:
    def test_returns_dry_run_result(self, valid_config_with_paths: InstallerConfig, tmp_path: Path):
        result = dry_run_install(valid_config_with_paths, install_dir=tmp_path)
        assert isinstance(result, DryRunResult)

    def test_writes_nothing_to_disk(self, valid_config_with_paths: InstallerConfig, tmp_path: Path):
        install_dir = tmp_path / "install"
        result = dry_run_install(valid_config_with_paths, install_dir=install_dir)
        # install_dir should not be created
        assert not install_dir.exists()
        # storage/backup dirs should not exist
        assert not Path(valid_config_with_paths.storage_path).exists()
        assert not Path(valid_config_with_paths.backup_path).exists()

    def test_env_file_not_written(self, valid_config_with_paths: InstallerConfig, tmp_path: Path):
        result = dry_run_install(valid_config_with_paths, install_dir=tmp_path)
        env_file = tmp_path / ".env"
        assert not env_file.exists()

    def test_returns_env_content_string(self, valid_config_with_paths: InstallerConfig, tmp_path: Path):
        result = dry_run_install(valid_config_with_paths, install_dir=tmp_path)
        assert isinstance(result.env_content, str)
        assert "BETA_ENV" in result.env_content

    def test_returns_toml_content_string(self, valid_config_with_paths: InstallerConfig, tmp_path: Path):
        result = dry_run_install(valid_config_with_paths, install_dir=tmp_path)
        assert isinstance(result.toml_content, str)
        assert "[meta]" in result.toml_content

    def test_returns_storage_dirs(self, valid_config_with_paths: InstallerConfig, tmp_path: Path):
        result = dry_run_install(valid_config_with_paths, install_dir=tmp_path)
        assert isinstance(result.storage_dirs, list)
        assert len(result.storage_dirs) > 0

    def test_returns_prerequisite_results(self, valid_config_with_paths: InstallerConfig, tmp_path: Path):
        result = dry_run_install(valid_config_with_paths, install_dir=tmp_path)
        assert isinstance(result.prerequisites, list)
        assert len(result.prerequisites) >= 1

    def test_shows_files_that_would_be_written(self, valid_config_with_paths: InstallerConfig, tmp_path: Path):
        result = dry_run_install(valid_config_with_paths, install_dir=tmp_path)
        assert isinstance(result.files_would_be_written, list)
        assert len(result.files_would_be_written) >= 1
        # .env should be in the list
        env_paths = [str(f) for f in result.files_would_be_written]
        assert any(".env" in p for p in env_paths)

    def test_flags_missing_secrets(self, tmp_path: Path):
        config = InstallerConfig(
            domain="test.example.com",
            jwt_secret="",      # empty → would need generation
            rest_api_secret="", # empty
            postgres_password="", # empty
            storage_path=str(tmp_path / "storage"),
            backup_path=str(tmp_path / "backups"),
        )
        result = dry_run_install(config, install_dir=tmp_path)
        assert result.secrets_would_be_generated is True

    def test_no_secrets_generated_flag_when_all_provided(self, valid_config_with_paths: InstallerConfig, tmp_path: Path):
        result = dry_run_install(valid_config_with_paths, install_dir=tmp_path)
        assert result.secrets_would_be_generated is False

    def test_all_prerequisites_passed_property(self, valid_config_with_paths: InstallerConfig, tmp_path: Path):
        result = dry_run_install(valid_config_with_paths, install_dir=tmp_path)
        # Property should match individual results
        expected = all(r.passed for r in result.prerequisites)
        assert result.all_prerequisites_passed == expected

    def test_no_docker_execution_in_dry_run(self, valid_config_with_paths: InstallerConfig, tmp_path: Path):
        import subprocess
        from unittest.mock import patch

        with patch.object(subprocess, "run", side_effect=AssertionError("subprocess.run must not be called")):
            result = dry_run_install(valid_config_with_paths, install_dir=tmp_path)
        assert result is not None
