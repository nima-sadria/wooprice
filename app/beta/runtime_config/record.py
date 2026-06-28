"""CP1.3 — Runtime configuration field definitions and audit models.

EDITABLE_FIELDS: non-secret, non-identity fields that an operator can change
                 via 'wooprice configure set' without a reinstall.

INSTALLER_ONLY_FIELDS: set once during install; cannot be changed at runtime.

SECRET_RUNTIME_FIELDS: never exposed or written by RuntimeConfigService.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


EDITABLE_FIELDS: frozenset[str] = frozenset(
    {
        "BETA_LOG_LEVEL",
        "BETA_NEXTCLOUD_URL",
        "BETA_NEXTCLOUD_FILE_PATH",
        "BETA_WOOCOMMERCE_URL",
        "BETA_TIMEZONE",
        "BETA_CURRENCY",
        "BETA_SCHEDULER_POLL_SECONDS",
        "BETA_BACKUP_RETAIN_DAYS",
        "BETA_MAX_UPLOAD_MB",
        "BETA_WORKER_CONCURRENCY",
    }
)

INSTALLER_ONLY_FIELDS: frozenset[str] = frozenset(
    {
        "BETA_ENV",
        "BETA_DOMAIN",
        "BETA_PORT",
        "BETA_SSL_MODE",
        "BETA_DATABASE_URL",
        "BETA_POSTGRES_DB",
        "BETA_POSTGRES_USER",
        "BETA_ADMIN_EMAIL",
        "BETA_STORAGE_PATH",
        "BETA_BACKUP_PATH",
        "BETA_PLUGIN_DIR",
    }
)

SECRET_RUNTIME_FIELDS: frozenset[str] = frozenset(
    {
        "BETA_JWT_SECRET",
        "BETA_REST_API_SECRET",
        "BETA_POSTGRES_PASSWORD",
        "BETA_NEXTCLOUD_USERNAME",
        "BETA_NEXTCLOUD_PASSWORD",
        "BETA_WOOCOMMERCE_KEY",
        "BETA_WOOCOMMERCE_SECRET",
    }
)


@dataclass
class ConfigRecord:
    """Snapshot of a single configuration field — safe to display."""

    field_name: str
    current_value: str
    is_editable: bool
    is_secret: bool
    is_installer_only: bool
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_name": self.field_name,
            "current_value": "[REDACTED]" if self.is_secret else self.current_value,
            "is_editable": self.is_editable,
            "is_secret": self.is_secret,
            "is_installer_only": self.is_installer_only,
            "description": self.description,
        }


@dataclass
class ConfigChangeEvent:
    """Audit record of a runtime configuration change."""

    field_name: str
    old_value: Optional[str]
    new_value: str
    changed_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    changed_by: str = "cli"

    def to_dict(self) -> dict[str, Any]:
        is_secret = self.field_name in SECRET_RUNTIME_FIELDS
        return {
            "field_name": self.field_name,
            "old_value": "[REDACTED]" if is_secret else self.old_value,
            "new_value": "[REDACTED]" if is_secret else self.new_value,
            "changed_at": self.changed_at.isoformat(),
            "changed_by": self.changed_by,
        }
