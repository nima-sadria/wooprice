"""Integration and safety tests for installer_core.

Covers: cancellation, no Docker execution, no network calls,
no A2 imports, no production hardcoding, no production config writes,
TOML generation, confirmation flow.
"""

import ast
import importlib
import sys
from pathlib import Path

import pytest

from installer.installer_core import (
    InstallerConfig,
    InstallationCancelled,
    build_confirmation_summary,
    confirm_installation,
    generate_toml_content,
    write_toml_config,
    InstallerRollback,
)


# ---------------------------------------------------------------------------
# TOML config generation
# ---------------------------------------------------------------------------


class TestGenerateTomlContent:
    def test_returns_string(self, valid_config_with_paths: InstallerConfig):
        content = generate_toml_content(valid_config_with_paths)
        assert isinstance(content, str)

    def test_has_meta_section(self, valid_config_with_paths: InstallerConfig):
        content = generate_toml_content(valid_config_with_paths)
        assert "[meta]" in content

    def test_has_app_section(self, valid_config_with_paths: InstallerConfig):
        content = generate_toml_content(valid_config_with_paths)
        assert "[app]" in content

    def test_has_database_section(self, valid_config_with_paths: InstallerConfig):
        content = generate_toml_content(valid_config_with_paths)
        assert "[database]" in content

    def test_has_source_section(self, valid_config_with_paths: InstallerConfig):
        content = generate_toml_content(valid_config_with_paths)
        assert "[source]" in content

    def test_has_channel_section(self, valid_config_with_paths: InstallerConfig):
        content = generate_toml_content(valid_config_with_paths)
        assert "[channel]" in content

    def test_no_secrets_in_toml(self, valid_config_with_paths: InstallerConfig):
        content = generate_toml_content(valid_config_with_paths)
        # Secrets are in valid_config_with_paths but must NOT appear in TOML
        assert valid_config_with_paths.jwt_secret not in content
        assert valid_config_with_paths.rest_api_secret not in content
        assert valid_config_with_paths.nextcloud_password not in content
        assert valid_config_with_paths.woocommerce_key not in content
        assert valid_config_with_paths.woocommerce_secret not in content

    def test_uses_placeholder_syntax_for_env_vars(self, valid_config_with_paths: InstallerConfig):
        content = generate_toml_content(valid_config_with_paths)
        assert "${BETA_ENV}" in content
        assert "${BETA_DOMAIN}" in content
        assert "${BETA_TIMEZONE}" in content

    def test_port_is_integer_not_placeholder(self, valid_config_with_paths: InstallerConfig):
        content = generate_toml_content(valid_config_with_paths)
        assert f"port = {valid_config_with_paths.port}" in content

    def test_has_version_marker(self, valid_config_with_paths: InstallerConfig):
        content = generate_toml_content(valid_config_with_paths)
        assert "beta-1.0.0" in content

    def test_has_do_not_edit_warning(self, valid_config_with_paths: InstallerConfig):
        content = generate_toml_content(valid_config_with_paths)
        assert "DO NOT EDIT MANUALLY" in content

    def test_no_production_domains_in_toml(self, valid_config_with_paths: InstallerConfig):
        content = generate_toml_content(valid_config_with_paths)
        assert "woo.softpple" not in content
        assert "softpple.business" not in content


class TestWriteTomlConfig:
    def test_writes_file(self, valid_config_with_paths: InstallerConfig, tmp_path: Path):
        content = generate_toml_content(valid_config_with_paths)
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        path = write_toml_config(content, config_dir)
        assert path.exists()
        assert path.name == "wooprice-beta.toml"

    def test_content_correct(self, valid_config_with_paths: InstallerConfig, tmp_path: Path):
        content = generate_toml_content(valid_config_with_paths)
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        path = write_toml_config(content, config_dir)
        assert path.read_text(encoding="utf-8") == content

    def test_tracks_new_file_in_rollback(self, valid_config_with_paths: InstallerConfig, tmp_path: Path):
        content = generate_toml_content(valid_config_with_paths)
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        rollback = InstallerRollback()
        path = write_toml_config(content, config_dir, rollback=rollback)
        assert path in rollback.tracked_files

    def test_does_not_track_preexisting_toml_in_rollback(self, valid_config_with_paths: InstallerConfig, tmp_path: Path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        existing = config_dir / "wooprice-beta.toml"
        existing.write_text("old content")
        content = generate_toml_content(valid_config_with_paths)
        rollback = InstallerRollback()
        write_toml_config(content, config_dir, rollback=rollback)
        assert existing not in rollback.tracked_files


# ---------------------------------------------------------------------------
# Confirmation and cancellation
# ---------------------------------------------------------------------------


class TestConfirmInstallation:
    def test_y_confirms(self):
        assert confirm_installation("y") is True

    def test_yes_confirms(self):
        assert confirm_installation("yes") is True

    def test_capital_Y_confirms(self):
        assert confirm_installation("Y") is True

    def test_empty_string_confirms(self):
        assert confirm_installation("") is True

    def test_n_cancels(self):
        assert confirm_installation("n") is False

    def test_no_cancels(self):
        assert confirm_installation("no") is False

    def test_N_cancels(self):
        assert confirm_installation("N") is False

    def test_random_string_cancels(self):
        assert confirm_installation("maybe") is False


class TestBuildConfirmationSummary:
    def test_returns_string(self, valid_config_with_paths: InstallerConfig):
        summary = build_confirmation_summary(valid_config_with_paths)
        assert isinstance(summary, str)

    def test_contains_domain(self, valid_config_with_paths: InstallerConfig):
        summary = build_confirmation_summary(valid_config_with_paths)
        assert valid_config_with_paths.domain in summary

    def test_contains_admin_email(self, valid_config_with_paths: InstallerConfig):
        summary = build_confirmation_summary(valid_config_with_paths)
        assert valid_config_with_paths.admin_email in summary

    def test_does_not_reveal_jwt_secret(self, valid_config_with_paths: InstallerConfig):
        summary = build_confirmation_summary(valid_config_with_paths)
        assert valid_config_with_paths.jwt_secret not in summary

    def test_does_not_reveal_rest_secret(self, valid_config_with_paths: InstallerConfig):
        summary = build_confirmation_summary(valid_config_with_paths)
        assert valid_config_with_paths.rest_api_secret not in summary

    def test_does_not_reveal_postgres_password(self, valid_config_with_paths: InstallerConfig):
        summary = build_confirmation_summary(valid_config_with_paths)
        assert valid_config_with_paths.postgres_password not in summary

    def test_shows_will_be_generated_for_empty_secrets(self):
        config = InstallerConfig(
            domain="test.example.com",
            jwt_secret="",
            rest_api_secret="",
            postgres_password="",
        )
        summary = build_confirmation_summary(config)
        assert "[will be generated]" in summary


class TestInstallationCancelledException:
    def test_is_exception(self):
        assert issubclass(InstallationCancelled, Exception)

    def test_can_be_raised_and_caught(self):
        with pytest.raises(InstallationCancelled):
            raise InstallationCancelled("user pressed N")

    def test_message_preserved(self):
        with pytest.raises(InstallationCancelled, match="user pressed N"):
            raise InstallationCancelled("user pressed N")


# ---------------------------------------------------------------------------
# Safety verification: no Docker execution, no network, no A2 imports
# ---------------------------------------------------------------------------


class TestNoDockerExecution:
    def test_installer_core_does_not_import_docker_sdk(self):
        import installer.installer_core as core
        source_file = Path(core.__file__)
        source = source_file.read_text(encoding="utf-8")
        assert "import docker" not in source
        assert "from docker" not in source

    def test_installer_core_does_not_call_subprocess_to_docker(self):
        import installer.installer_core as core
        source_file = Path(core.__file__)
        source = source_file.read_text(encoding="utf-8")
        assert 'import subprocess' not in source
        assert 'subprocess.run' not in source
        assert 'subprocess.call' not in source
        assert 'subprocess.Popen' not in source


class TestNoNetworkCalls:
    def test_installer_core_does_not_import_requests(self):
        import installer.installer_core as core
        source_file = Path(core.__file__)
        source = source_file.read_text(encoding="utf-8")
        assert "import requests" not in source
        assert "import httpx" not in source
        assert "import urllib.request" not in source

    def test_installer_core_does_not_import_socket_directly(self):
        import installer.installer_core as core
        source_file = Path(core.__file__)
        source = source_file.read_text(encoding="utf-8")
        assert "import socket" not in source


class TestNoA2Mutation:
    def test_installer_core_does_not_import_from_a2(self):
        import installer.installer_core as core
        source_file = Path(core.__file__)
        source = source_file.read_text(encoding="utf-8")
        assert "from app.a2" not in source
        assert "import app.a2" not in source

    def test_installer_core_imports_only_from_app_beta_config(self):
        import installer.installer_core as core
        source_file = Path(core.__file__)
        source = source_file.read_text(encoding="utf-8")
        # Only allowed app.beta import is app.beta.config
        lines_with_app = [l for l in source.splitlines() if "from app." in l or "import app." in l]
        for line in lines_with_app:
            assert "app.beta.config" in line, f"Unexpected app import: {line}"


class TestNoProductionHardcoding:
    def test_no_production_domain_in_installer_core(self):
        import installer.installer_core as core
        source_file = Path(core.__file__)
        source = source_file.read_text(encoding="utf-8")
        assert "woo.softpple" not in source
        assert "softpple.business" not in source

    def test_no_production_urls_in_installer_core(self):
        import installer.installer_core as core
        source_file = Path(core.__file__)
        source = source_file.read_text(encoding="utf-8")
        assert "nextcloud.softpple" not in source
        assert "192.168.1." not in source

    def test_no_real_credentials_in_installer_core(self):
        import installer.installer_core as core
        source_file = Path(core.__file__)
        source = source_file.read_text(encoding="utf-8")
        # No WooCommerce live credential patterns
        assert "ck_live_" not in source
        assert "cs_live_" not in source
        # No hardcoded API key values (pattern: ck_ or cs_ followed by hex)
        import re
        assert not re.search(r'ck_[0-9a-f]{20,}', source)
        assert not re.search(r'cs_[0-9a-f]{20,}', source)

    def test_test_fixtures_use_example_domains_only(self):
        conftest_path = Path(__file__).parent / "conftest.py"
        source = conftest_path.read_text(encoding="utf-8")
        assert "example.com" in source
        assert "woo.softpple" not in source
        assert "softpple.business" not in source
