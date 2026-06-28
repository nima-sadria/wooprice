"""CP1.3 — Runtime Configuration Service.

Write path for editable runtime configuration fields.
Completely separate from B3 ConfigurationManager (read-only, immutable schema).

Invariants:
- Only EDITABLE_FIELDS may be written.
- INSTALLER_ONLY_FIELDS and SECRET_RUNTIME_FIELDS are always rejected.
- Values are validated before any write occurs.
- Writes are in-place replacements within the existing .env file.
- No credentials are ever read or returned.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .record import (
    EDITABLE_FIELDS,
    INSTALLER_ONLY_FIELDS,
    SECRET_RUNTIME_FIELDS,
    ConfigChangeEvent,
    ConfigRecord,
)


@dataclass
class ValidationResult:
    valid: bool
    error: Optional[str] = None


@dataclass
class SetResult:
    success: bool
    field_name: str
    old_value: Optional[str]
    new_value: str
    error: Optional[str] = None
    change_event: Optional[ConfigChangeEvent] = None


class RuntimeConfigService:
    """Manages editable runtime configuration fields.

    Use set() to write a value. Use get() or get_all_editable() to read.
    Never reads or exposes secret or installer-only fields.
    """

    def __init__(self, env_file: Optional[Path] = None) -> None:
        self._env_file = env_file or Path(".env")

    def get(self, field_name: str) -> ConfigRecord:
        """Return a ConfigRecord for any known field."""
        name = field_name.upper()
        env_dict = self._read_env()
        return ConfigRecord(
            field_name=name,
            current_value="" if name in SECRET_RUNTIME_FIELDS else env_dict.get(name, ""),
            is_editable=name in EDITABLE_FIELDS,
            is_secret=name in SECRET_RUNTIME_FIELDS,
            is_installer_only=name in INSTALLER_ONLY_FIELDS,
        )

    def get_all_editable(self) -> list[ConfigRecord]:
        """Return ConfigRecord for every editable field in sorted order."""
        env_dict = self._read_env()
        return [
            ConfigRecord(
                field_name=name,
                current_value=env_dict.get(name, ""),
                is_editable=True,
                is_secret=False,
                is_installer_only=False,
            )
            for name in sorted(EDITABLE_FIELDS)
        ]

    def set(
        self,
        field_name: str,
        value: str,
        changed_by: str = "cli",
    ) -> SetResult:
        """Set an editable field. Validates before writing.

        Returns SetResult with success=False and error string if the field is
        not editable, is a secret, is installer-only, or fails validation.
        """
        name = field_name.upper()

        if name in SECRET_RUNTIME_FIELDS:
            return SetResult(
                success=False,
                field_name=name,
                old_value=None,
                new_value=value,
                error=f"'{name}' is a secret field and cannot be modified via this command.",
            )

        if name in INSTALLER_ONLY_FIELDS:
            return SetResult(
                success=False,
                field_name=name,
                old_value=None,
                new_value=value,
                error=f"'{name}' is installer-only and cannot be changed at runtime.",
            )

        if name not in EDITABLE_FIELDS:
            return SetResult(
                success=False,
                field_name=name,
                old_value=None,
                new_value=value,
                error=(
                    f"'{name}' is not an editable runtime field. "
                    f"Editable fields: {', '.join(sorted(EDITABLE_FIELDS))}"
                ),
            )

        env_dict = self._read_env()
        old_value = env_dict.get(name)

        validation = self._validate(name, value)
        if not validation.valid:
            return SetResult(
                success=False,
                field_name=name,
                old_value=old_value,
                new_value=value,
                error=validation.error,
            )

        self._write_field(name, value)

        event = ConfigChangeEvent(
            field_name=name,
            old_value=old_value,
            new_value=value,
            changed_by=changed_by,
        )
        return SetResult(
            success=True,
            field_name=name,
            old_value=old_value,
            new_value=value,
            change_event=event,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read_env(self) -> dict[str, str]:
        if not self._env_file.exists():
            return {}
        result: dict[str, str] = {}
        for line in self._env_file.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            k, _, v = stripped.partition("=")
            k = k.strip()
            if k:
                result[k] = v.strip()
        return result

    def _write_field(self, field_name: str, value: str) -> None:
        """Update a single field in the .env file (append if not present)."""
        if not self._env_file.exists():
            self._env_file.write_text(f"{field_name}={value}\n", encoding="utf-8")
            return

        lines = self._env_file.read_text(encoding="utf-8").splitlines()
        updated = False
        new_lines: list[str] = []
        for line in lines:
            stripped = line.strip()
            if re.match(rf"^{re.escape(field_name)}\s*=", stripped):
                new_lines.append(f"{field_name}={value}")
                updated = True
            else:
                new_lines.append(line)

        if not updated:
            new_lines.append(f"{field_name}={value}")

        content = "\n".join(new_lines)
        if not content.endswith("\n"):
            content += "\n"
        self._env_file.write_text(content, encoding="utf-8")

    def _validate(self, field_name: str, value: str) -> ValidationResult:
        validators = _FIELD_VALIDATORS.get(field_name, [])
        for fn in validators:
            error = fn(value)
            if error:
                return ValidationResult(valid=False, error=error)
        return ValidationResult(valid=True)


# ---------------------------------------------------------------------------
# Per-field validators — return error string or None
# ---------------------------------------------------------------------------

def _validate_log_level(value: str) -> Optional[str]:
    valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if value.upper() not in valid:
        return f"Invalid log level '{value}'. Must be one of: {', '.join(sorted(valid))}"
    return None


def _validate_url(value: str) -> Optional[str]:
    if not re.match(r"^https?://", value, re.IGNORECASE):
        return f"Invalid URL '{value}'. Must start with http:// or https://"
    return None


def _validate_currency(value: str) -> Optional[str]:
    if not re.match(r"^[A-Z]{3}$", value):
        return (
            f"Invalid currency code '{value}'. "
            "Must be a 3-letter uppercase ISO 4217 code (e.g., USD, EUR, IRR)"
        )
    return None


def _validate_timezone(value: str) -> Optional[str]:
    import zoneinfo
    try:
        zoneinfo.ZoneInfo(value)
    except Exception:
        return (
            f"Invalid timezone '{value}'. "
            "Must be a valid IANA timezone string (e.g., UTC, America/New_York)"
        )
    return None


def _validate_positive_int(value: str) -> Optional[str]:
    try:
        n = int(value)
        if n < 1:
            return f"Value must be a positive integer (got {value})"
    except ValueError:
        return f"Value must be a positive integer (got {value!r})"
    return None


_FIELD_VALIDATORS: dict[str, list[Callable[[str], Optional[str]]]] = {
    "BETA_LOG_LEVEL": [_validate_log_level],
    "BETA_NEXTCLOUD_URL": [_validate_url],
    "BETA_WOOCOMMERCE_URL": [_validate_url],
    "BETA_TIMEZONE": [_validate_timezone],
    "BETA_CURRENCY": [_validate_currency],
    "BETA_SCHEDULER_POLL_SECONDS": [_validate_positive_int],
    "BETA_BACKUP_RETAIN_DAYS": [_validate_positive_int],
    "BETA_MAX_UPLOAD_MB": [_validate_positive_int],
    "BETA_WORKER_CONCURRENCY": [_validate_positive_int],
}
