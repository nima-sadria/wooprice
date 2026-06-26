"""Shared fixtures for tests/beta/installer/."""

import pytest

from installer.installer_core import InstallerConfig, InstallerSecrets


@pytest.fixture
def valid_config() -> InstallerConfig:
    """InstallerConfig with all required fields populated with test values."""
    return InstallerConfig(
        domain="test.example.com",
        port=8080,
        ssl_mode="off",
        env="beta",
        postgres_db="wooprice_beta_test",
        postgres_user="wooprice_test",
        postgres_password="test_pg_pass_secure_abc123xyz",
        jwt_secret="a" * 64,
        rest_api_secret="b" * 32,
        nextcloud_url="https://cloud.example.com",
        nextcloud_file_path="/prices/test.xlsx",
        nextcloud_username="test_nc_user",
        nextcloud_password="test_nc_pass_secure",
        woocommerce_url="https://shop.example.com",
        woocommerce_key="ck_test_key_secure_deadbeef",
        woocommerce_secret="cs_test_secret_secure_cafebabe",
        timezone="UTC",
        currency="USD",
        admin_email="admin@example.com",
        storage_path="",   # overridden in tests using tmp_path
        backup_path="",    # overridden in tests using tmp_path
        log_level="INFO",
    )


@pytest.fixture
def valid_config_with_paths(valid_config: InstallerConfig, tmp_path) -> InstallerConfig:
    """InstallerConfig with storage/backup paths pointing to tmp_path."""
    from dataclasses import replace
    return replace(
        valid_config,
        storage_path=str(tmp_path / "storage"),
        backup_path=str(tmp_path / "backups"),
    )


@pytest.fixture
def generated_secrets() -> InstallerSecrets:
    from installer.installer_core import generate_secrets
    return generate_secrets()


@pytest.fixture
def valid_env_dict(valid_config_with_paths: InstallerConfig) -> dict[str, str]:
    """Parsed env dict from a valid InstallerConfig."""
    from installer.installer_core import generate_env_content, _parse_env_content
    content = generate_env_content(valid_config_with_paths)
    return _parse_env_content(content)
