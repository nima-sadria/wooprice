"""Shared fixtures for app/beta/config/ tests."""

import pytest

# Minimal valid env that passes ConfigValidator with check_paths=False.
_BASE_VALID_ENV: dict[str, str] = {
    "BETA_ENV": "beta",
    "BETA_DOMAIN": "test.example.com",
    "BETA_PORT": "8080",
    "BETA_DATABASE_URL": "postgresql://user:pass@localhost/db",
    "BETA_POSTGRES_DB": "wooprice_beta",
    "BETA_POSTGRES_USER": "wooprice",
    "BETA_POSTGRES_PASSWORD": "pg_pass_secure_abc123",
    "BETA_JWT_SECRET": "a" * 64,
    "BETA_REST_API_SECRET": "b" * 32,
    "BETA_NEXTCLOUD_URL": "https://cloud.example.com",
    "BETA_NEXTCLOUD_FILE_PATH": "/prices/test.xlsx",
    "BETA_NEXTCLOUD_USERNAME": "wooprice_user",
    "BETA_NEXTCLOUD_PASSWORD": "nc_pass_secure_xyz789",
    "BETA_WOOCOMMERCE_URL": "https://shop.example.com",
    "BETA_WOOCOMMERCE_KEY": "ck_test_key_secure_deadbeef",
    "BETA_WOOCOMMERCE_SECRET": "cs_test_secret_secure_cafebabe",
    "BETA_TIMEZONE": "Europe/Amsterdam",
    "BETA_CURRENCY": "EUR",
    "BETA_ADMIN_EMAIL": "admin@example.com",
    "BETA_STORAGE_PATH": "/tmp/beta_storage",
    "BETA_BACKUP_PATH": "/tmp/beta_backup",
    "BETA_SSL_MODE": "off",
}


@pytest.fixture
def valid_env() -> dict[str, str]:
    """Complete valid env dict. check_paths=False to avoid filesystem deps."""
    return dict(_BASE_VALID_ENV)


@pytest.fixture
def valid_env_with_paths(tmp_path) -> dict[str, str]:
    """Complete valid env dict with real tmp_path directories."""
    storage = tmp_path / "storage"
    storage.mkdir()
    backup = tmp_path / "backup"
    backup.mkdir()
    env = dict(_BASE_VALID_ENV)
    env["BETA_STORAGE_PATH"] = str(storage)
    env["BETA_BACKUP_PATH"] = str(backup)
    return env
