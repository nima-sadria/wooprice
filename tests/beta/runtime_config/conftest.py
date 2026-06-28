"""Shared fixtures for runtime configuration tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def env_file(tmp_path: Path) -> Path:
    """A minimal .env file with all editable and installer-only fields set."""
    content = (
        "BETA_ENV=beta\n"
        "BETA_DOMAIN=beta.example.com\n"
        "BETA_PORT=8080\n"
        "BETA_SSL_MODE=reverse_proxy\n"
        "BETA_DATABASE_URL=postgresql://user:pass@localhost/db\n"
        "BETA_POSTGRES_DB=wooprice_beta\n"
        "BETA_POSTGRES_USER=wooprice\n"
        "BETA_POSTGRES_PASSWORD=pgpass\n"
        "BETA_JWT_SECRET=" + "a" * 64 + "\n"
        "BETA_REST_API_SECRET=" + "b" * 32 + "\n"
        "BETA_NEXTCLOUD_URL=https://nextcloud.example.com\n"
        "BETA_NEXTCLOUD_FILE_PATH=/prices/prices.xlsx\n"
        "BETA_NEXTCLOUD_USERNAME=ncuser\n"
        "BETA_NEXTCLOUD_PASSWORD=ncpass\n"
        "BETA_WOOCOMMERCE_URL=https://shop.example.com\n"
        "BETA_WOOCOMMERCE_KEY=ck_abc\n"
        "BETA_WOOCOMMERCE_SECRET=cs_xyz\n"
        "BETA_TIMEZONE=UTC\n"
        "BETA_CURRENCY=USD\n"
        "BETA_ADMIN_EMAIL=admin@example.com\n"
        "BETA_STORAGE_PATH=/data/wooprice\n"
        "BETA_BACKUP_PATH=/data/backup\n"
        "BETA_LOG_LEVEL=INFO\n"
        "BETA_SCHEDULER_POLL_SECONDS=60\n"
        "BETA_BACKUP_RETAIN_DAYS=7\n"
        "BETA_MAX_UPLOAD_MB=100\n"
        "BETA_WORKER_CONCURRENCY=2\n"
    )
    p = tmp_path / ".env"
    p.write_text(content, encoding="utf-8")
    return p


@pytest.fixture
def empty_env_file(tmp_path: Path) -> Path:
    p = tmp_path / ".env"
    p.write_text("", encoding="utf-8")
    return p
