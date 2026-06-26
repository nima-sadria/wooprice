"""Shared fixtures for CLI tests."""

from __future__ import annotations

from pathlib import Path

import pytest


_VALID_ENV_CONTENT = """\
BETA_ENV=beta
BETA_DOMAIN=test.example.com
BETA_PORT=8080
BETA_DATABASE_URL=postgresql://wooprice_test:test_pg_pass_secure@postgres:5432/wooprice_test
BETA_POSTGRES_DB=wooprice_test
BETA_POSTGRES_USER=wooprice_test
BETA_POSTGRES_PASSWORD=test_pg_pass_secure_abc123xyz
BETA_JWT_SECRET={}
BETA_REST_API_SECRET={}
BETA_NEXTCLOUD_URL=https://cloud.example.com
BETA_NEXTCLOUD_FILE_PATH=/prices/test.xlsx
BETA_NEXTCLOUD_USERNAME=test_nc_user
BETA_NEXTCLOUD_PASSWORD=test_nc_pass_secure_abc123
BETA_WOOCOMMERCE_URL=https://shop.example.com
BETA_WOOCOMMERCE_KEY=ck_test_key_secure_deadbeef_abcdef
BETA_WOOCOMMERCE_SECRET=cs_test_secret_secure_cafebabe_xyz
BETA_TIMEZONE=UTC
BETA_CURRENCY=USD
BETA_ADMIN_EMAIL=admin@example.com
BETA_STORAGE_PATH=/tmp/wooprice-beta-test/storage
BETA_BACKUP_PATH=/tmp/wooprice-beta-test/backups
BETA_SSL_MODE=off
""".format("a" * 86, "b" * 64)

_PRODUCTION_ENV_CONTENT = """\
BETA_ENV=production
BETA_DOMAIN=prod.example.com
BETA_PORT=8080
BETA_DATABASE_URL=postgresql://prod_user:prod_pass@postgres:5432/prod_db
BETA_POSTGRES_DB=prod_db
BETA_POSTGRES_USER=prod_user
BETA_POSTGRES_PASSWORD=test_pg_pass_secure_abc123xyz
BETA_JWT_SECRET={}
BETA_REST_API_SECRET={}
BETA_NEXTCLOUD_URL=https://cloud.example.com
BETA_NEXTCLOUD_FILE_PATH=/prices/prod.xlsx
BETA_NEXTCLOUD_USERNAME=prod_nc_user
BETA_NEXTCLOUD_PASSWORD=prod_nc_pass_secure_abc123
BETA_WOOCOMMERCE_URL=https://shop.example.com
BETA_WOOCOMMERCE_KEY=ck_test_key_secure_deadbeef_abcdef
BETA_WOOCOMMERCE_SECRET=cs_test_secret_secure_cafebabe_xyz
BETA_TIMEZONE=UTC
BETA_CURRENCY=USD
BETA_ADMIN_EMAIL=admin@example.com
BETA_STORAGE_PATH=/tmp/wooprice-prod-test/storage
BETA_BACKUP_PATH=/tmp/wooprice-prod-test/backups
BETA_SSL_MODE=off
""".format("a" * 86, "b" * 64)


@pytest.fixture
def valid_env_file(tmp_path: Path) -> Path:
    """A valid .env file with beta profile (no real/production values)."""
    env_file = tmp_path / ".env"
    env_file.write_text(_VALID_ENV_CONTENT, encoding="utf-8")
    return env_file


@pytest.fixture
def production_env_file(tmp_path: Path) -> Path:
    """A .env file with production profile (for testing production blocks)."""
    env_file = tmp_path / ".env.prod"
    env_file.write_text(_PRODUCTION_ENV_CONTENT, encoding="utf-8")
    return env_file


@pytest.fixture
def empty_env_file(tmp_path: Path) -> Path:
    """An empty (no variables) .env file."""
    env_file = tmp_path / ".env.empty"
    env_file.write_text("", encoding="utf-8")
    return env_file


@pytest.fixture
def valid_env_content() -> str:
    return _VALID_ENV_CONTENT
