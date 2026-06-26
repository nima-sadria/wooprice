"""Tests for .env file generation."""

import stat
import sys
from pathlib import Path

import pytest

from installer.installer_core import (
    InstallerConfig,
    InstallerRollback,
    _parse_env_content,
    generate_env_content,
    write_env_file,
)

# Production domains / URLs that must never appear in generated content
_FORBIDDEN_PRODUCTION_DOMAINS = [
    "woo.softpple.business",
    "softpple.com",
    "softpple.business",
]
_FORBIDDEN_PRODUCTION_URLS = [
    "woo.softpple",
    "nextcloud.softpple",
    "192.168.1.",
    "10.0.0.",
]


class TestGenerateEnvContent:
    def test_returns_string(self, valid_config_with_paths: InstallerConfig):
        content = generate_env_content(valid_config_with_paths)
        assert isinstance(content, str)

    def test_contains_beta_env(self, valid_config_with_paths: InstallerConfig):
        content = generate_env_content(valid_config_with_paths)
        assert "BETA_ENV=beta" in content

    def test_contains_all_required_field_names(self, valid_config_with_paths: InstallerConfig):
        content = generate_env_content(valid_config_with_paths)
        required = [
            "BETA_DOMAIN", "BETA_PORT", "BETA_DATABASE_URL",
            "BETA_POSTGRES_DB", "BETA_POSTGRES_USER", "BETA_POSTGRES_PASSWORD",
            "BETA_JWT_SECRET", "BETA_REST_API_SECRET",
            "BETA_NEXTCLOUD_URL", "BETA_NEXTCLOUD_FILE_PATH",
            "BETA_NEXTCLOUD_USERNAME", "BETA_NEXTCLOUD_PASSWORD",
            "BETA_WOOCOMMERCE_URL", "BETA_WOOCOMMERCE_KEY", "BETA_WOOCOMMERCE_SECRET",
            "BETA_TIMEZONE", "BETA_CURRENCY", "BETA_ADMIN_EMAIL",
            "BETA_STORAGE_PATH", "BETA_BACKUP_PATH", "BETA_SSL_MODE",
        ]
        for var in required:
            assert var in content, f"Missing: {var}"

    def test_constructs_database_url_from_parts(self, valid_config_with_paths: InstallerConfig):
        content = generate_env_content(valid_config_with_paths)
        assert "BETA_DATABASE_URL=postgresql://" in content
        assert valid_config_with_paths.postgres_user in content
        assert valid_config_with_paths.postgres_db in content

    def test_has_header_comment(self, valid_config_with_paths: InstallerConfig):
        content = generate_env_content(valid_config_with_paths)
        assert "WooPrice Beta" in content
        assert "generated environment file" in content

    def test_has_do_not_commit_warning(self, valid_config_with_paths: InstallerConfig):
        content = generate_env_content(valid_config_with_paths)
        assert "DO NOT COMMIT" in content

    def test_no_hardcoded_production_domains(self, valid_config_with_paths: InstallerConfig):
        content = generate_env_content(valid_config_with_paths)
        for domain in _FORBIDDEN_PRODUCTION_DOMAINS:
            assert domain not in content, f"Production domain found: {domain}"

    def test_no_hardcoded_production_urls(self, valid_config_with_paths: InstallerConfig):
        content = generate_env_content(valid_config_with_paths)
        for url in _FORBIDDEN_PRODUCTION_URLS:
            assert url not in content, f"Production URL found: {url}"

    def test_domain_value_in_content(self, valid_config_with_paths: InstallerConfig):
        content = generate_env_content(valid_config_with_paths)
        assert f"BETA_DOMAIN={valid_config_with_paths.domain}" in content

    def test_port_value_in_content(self, valid_config_with_paths: InstallerConfig):
        content = generate_env_content(valid_config_with_paths)
        assert f"BETA_PORT={valid_config_with_paths.port}" in content

    def test_ends_with_newline(self, valid_config_with_paths: InstallerConfig):
        content = generate_env_content(valid_config_with_paths)
        assert content.endswith("\n")


class TestParseEnvContent:
    def test_round_trip(self, valid_config_with_paths: InstallerConfig):
        content = generate_env_content(valid_config_with_paths)
        parsed = _parse_env_content(content)
        assert parsed["BETA_ENV"] == "beta"
        assert parsed["BETA_DOMAIN"] == valid_config_with_paths.domain
        assert parsed["BETA_PORT"] == str(valid_config_with_paths.port)

    def test_skips_comment_lines(self):
        content = "# this is a comment\nFOO=bar\n"
        parsed = _parse_env_content(content)
        assert "FOO" in parsed
        assert len(parsed) == 1

    def test_skips_empty_lines(self):
        content = "\n\nFOO=bar\n\n\n"
        parsed = _parse_env_content(content)
        assert parsed == {"FOO": "bar"}

    def test_skips_lines_without_equals(self):
        content = "not a variable\nFOO=bar\n"
        parsed = _parse_env_content(content)
        assert parsed == {"FOO": "bar"}

    def test_handles_value_with_equals(self):
        content = "DATABASE_URL=postgresql://user:pass@host/db\n"
        parsed = _parse_env_content(content)
        assert parsed["DATABASE_URL"] == "postgresql://user:pass@host/db"

    def test_empty_content(self):
        assert _parse_env_content("") == {}

    def test_only_comments(self):
        assert _parse_env_content("# comment\n# another\n") == {}


class TestWriteEnvFile:
    def test_writes_content_to_path(self, tmp_path: Path, valid_config_with_paths: InstallerConfig):
        content = generate_env_content(valid_config_with_paths)
        env_path = tmp_path / ".env"
        write_env_file(content, env_path)
        assert env_path.read_text(encoding="utf-8") == content

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="chmod 600 is not enforced by the Windows file permission model",
    )
    def test_file_mode_is_600(self, tmp_path: Path, valid_config_with_paths: InstallerConfig):
        content = generate_env_content(valid_config_with_paths)
        env_path = tmp_path / ".env"
        write_env_file(content, env_path)
        file_mode = stat.S_IMODE(env_path.stat().st_mode)
        assert file_mode == 0o600

    def test_tracks_new_file_in_rollback(self, tmp_path: Path, valid_config_with_paths: InstallerConfig):
        content = generate_env_content(valid_config_with_paths)
        env_path = tmp_path / ".env"
        rollback = InstallerRollback()
        write_env_file(content, env_path, rollback=rollback)
        assert env_path in rollback.tracked_files

    def test_does_not_track_preexisting_file_in_rollback(self, tmp_path: Path, valid_config_with_paths: InstallerConfig):
        content = generate_env_content(valid_config_with_paths)
        env_path = tmp_path / ".env"
        env_path.write_text("existing content")  # pre-create
        rollback = InstallerRollback()
        write_env_file(content, env_path, rollback=rollback)
        assert env_path not in rollback.tracked_files

    def test_no_rollback_no_error(self, tmp_path: Path, valid_config_with_paths: InstallerConfig):
        content = generate_env_content(valid_config_with_paths)
        env_path = tmp_path / ".env"
        write_env_file(content, env_path, rollback=None)
        assert env_path.exists()
