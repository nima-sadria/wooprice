"""WooPrice Beta — Configuration validation.

Validates a flat dict[str, str] of environment variables and returns a
structured ValidationResult. Never raises, never terminates the process.
The caller decides what to do with the result.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .defaults import DEFAULTS, LOG_LEVELS, SSL_MODES
from .secrets import SECRET_FIELDS

_URL_RE = re.compile(r"^https?://", re.IGNORECASE)
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

REQUIRED_FIELDS: tuple[str, ...] = (
    "BETA_ENV",
    "BETA_DOMAIN",
    "BETA_PORT",
    "BETA_DATABASE_URL",
    "BETA_POSTGRES_DB",
    "BETA_POSTGRES_USER",
    "BETA_POSTGRES_PASSWORD",
    "BETA_JWT_SECRET",
    "BETA_REST_API_SECRET",
    "BETA_NEXTCLOUD_URL",
    "BETA_NEXTCLOUD_FILE_PATH",
    "BETA_NEXTCLOUD_USERNAME",
    "BETA_NEXTCLOUD_PASSWORD",
    "BETA_WOOCOMMERCE_URL",
    "BETA_WOOCOMMERCE_KEY",
    "BETA_WOOCOMMERCE_SECRET",
    "BETA_TIMEZONE",
    "BETA_CURRENCY",
    "BETA_ADMIN_EMAIL",
    "BETA_STORAGE_PATH",
    "BETA_BACKUP_PATH",
    "BETA_SSL_MODE",
)

OPTIONAL_FIELDS: tuple[str, ...] = (
    "BETA_LOG_LEVEL",
    "BETA_JWT_ACCESS_TTL_MINUTES",
    "BETA_JWT_REFRESH_TTL_DAYS",
    "BETA_MAX_UPLOAD_MB",
    "BETA_PLUGIN_DIR",
    "BETA_WORKER_CONCURRENCY",
    "BETA_SCHEDULER_POLL_SECONDS",
    "BETA_BACKUP_RETAIN_DAYS",
)


@dataclass
class FieldError:
    field: str
    value: Any
    message: str

    def __str__(self) -> str:
        display = "[REDACTED]" if self.field in SECRET_FIELDS else repr(self.value)
        return f"{self.field}={display}: {self.message}"


@dataclass
class ValidationResult:
    errors: list[FieldError] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.errors

    def add_error(self, field_name: str, value: Any, message: str) -> None:
        self.errors.append(FieldError(field=field_name, value=value, message=message))

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)

    def __bool__(self) -> bool:
        return self.is_valid

    def format_errors(self) -> str:
        if not self.errors:
            return "No errors."
        return "\n".join(f"  • {e}" for e in self.errors)

    def format_warnings(self) -> str:
        if not self.warnings:
            return "No warnings."
        return "\n".join(f"  • {w}" for w in self.warnings)


class ConfigValidator:
    """Validates a flat env dict and returns structured ValidationResult."""

    def __init__(self, check_paths: bool = True) -> None:
        self._check_paths = check_paths

    def validate(self, env: dict[str, str]) -> ValidationResult:
        result = ValidationResult()
        self._check_required_present(env, result)
        self._check_field_values(env, result)
        return result

    def _check_required_present(self, env: dict[str, str], result: ValidationResult) -> None:
        for name in REQUIRED_FIELDS:
            if not env.get(name, "").strip():
                result.add_error(name, None, "Required variable is missing or empty")

    def _check_field_values(self, env: dict[str, str], result: ValidationResult) -> None:
        get = env.get

        _v(result, "BETA_ENV", get("BETA_ENV", ""), _check_env)
        _v(result, "BETA_PORT", get("BETA_PORT", ""), _check_port)
        _v(result, "BETA_DATABASE_URL", get("BETA_DATABASE_URL", ""), _check_database_url)
        _v(result, "BETA_JWT_SECRET", get("BETA_JWT_SECRET", ""), _check_jwt_secret)
        _v(result, "BETA_REST_API_SECRET", get("BETA_REST_API_SECRET", ""), _check_rest_secret)
        _v(result, "BETA_NEXTCLOUD_URL", get("BETA_NEXTCLOUD_URL", ""), _check_url)
        _v(result, "BETA_WOOCOMMERCE_URL", get("BETA_WOOCOMMERCE_URL", ""), _check_url)
        _v(result, "BETA_TIMEZONE", get("BETA_TIMEZONE", ""), _check_timezone)
        _v(result, "BETA_CURRENCY", get("BETA_CURRENCY", ""), _check_currency)
        _v(result, "BETA_ADMIN_EMAIL", get("BETA_ADMIN_EMAIL", ""), _check_email)
        _v(result, "BETA_SSL_MODE", get("BETA_SSL_MODE", ""), _check_ssl_mode)
        _v(result, "BETA_LOG_LEVEL", get("BETA_LOG_LEVEL", str(DEFAULTS["BETA_LOG_LEVEL"])), _check_log_level)
        _v(result, "BETA_JWT_ACCESS_TTL_MINUTES", get("BETA_JWT_ACCESS_TTL_MINUTES", str(DEFAULTS["BETA_JWT_ACCESS_TTL_MINUTES"])), _check_positive_int)
        _v(result, "BETA_JWT_REFRESH_TTL_DAYS", get("BETA_JWT_REFRESH_TTL_DAYS", str(DEFAULTS["BETA_JWT_REFRESH_TTL_DAYS"])), _check_positive_int)
        _v(result, "BETA_MAX_UPLOAD_MB", get("BETA_MAX_UPLOAD_MB", str(DEFAULTS["BETA_MAX_UPLOAD_MB"])), _check_positive_int)
        _v(result, "BETA_WORKER_CONCURRENCY", get("BETA_WORKER_CONCURRENCY", str(DEFAULTS["BETA_WORKER_CONCURRENCY"])), _check_positive_int)
        _v(result, "BETA_SCHEDULER_POLL_SECONDS", get("BETA_SCHEDULER_POLL_SECONDS", str(DEFAULTS["BETA_SCHEDULER_POLL_SECONDS"])), _check_positive_int)
        _v(result, "BETA_BACKUP_RETAIN_DAYS", get("BETA_BACKUP_RETAIN_DAYS", str(DEFAULTS["BETA_BACKUP_RETAIN_DAYS"])), _check_positive_int)

        if self._check_paths:
            _v(result, "BETA_STORAGE_PATH", get("BETA_STORAGE_PATH", ""), _check_writable_path)
            _v(result, "BETA_BACKUP_PATH", get("BETA_BACKUP_PATH", ""), _check_writable_path)

        env_val = get("BETA_ENV", "")
        if env_val == "production":
            result.add_warning(
                "BETA_ENV=production detected. Production guard is active. "
                "All destructive CLI operations require --i-know-what-i-am-doing."
            )


def _v(
    result: ValidationResult,
    field_name: str,
    value: str,
    checker: Callable[[str], str | None],
) -> None:
    message = checker(value)
    if message:
        result.add_error(field_name, value, message)


def _check_env(value: str) -> str | None:
    if not value:
        return None
    if value not in ("dev", "beta", "production"):
        return f"Must be one of: dev, beta, production (got {value!r})"
    return None


def _check_port(value: str) -> str | None:
    if not value:
        return None
    try:
        port = int(value)
    except ValueError:
        return f"Must be an integer (got {value!r})"
    if not (1024 <= port <= 65535):
        return f"Must be between 1024 and 65535 (got {port})"
    return None


def _check_database_url(value: str) -> str | None:
    if not value:
        return None
    valid_prefixes = ("postgresql://", "postgresql+asyncpg://", "postgresql+psycopg2://")
    if not value.startswith(valid_prefixes):
        return "Must be a PostgreSQL connection string (postgresql://...)"
    return None


def _check_jwt_secret(value: str) -> str | None:
    if not value:
        return None
    if len(value) < 64:
        return f"Must be at least 64 characters (got {len(value)})"
    return None


def _check_rest_secret(value: str) -> str | None:
    if not value:
        return None
    if len(value) < 32:
        return f"Must be at least 32 characters (got {len(value)})"
    return None


def _check_url(value: str) -> str | None:
    if not value:
        return None
    if not _URL_RE.match(value):
        return f"Must be a valid URL with http:// or https:// scheme (got {value!r})"
    return None


def _check_timezone(value: str) -> str | None:
    if not value:
        return None
    try:
        import zoneinfo
        zoneinfo.ZoneInfo(value)
    except Exception:
        return (
            f"Must be a valid IANA timezone string (got {value!r}). "
            "Install tzdata package if running in a minimal environment."
        )
    return None


def _check_currency(value: str) -> str | None:
    if not value:
        return None
    if not _CURRENCY_RE.match(value):
        return f"Must be a 3-letter uppercase ISO 4217 code (got {value!r})"
    return None


def _check_email(value: str) -> str | None:
    if not value:
        return None
    if not _EMAIL_RE.match(value):
        return f"Must be a valid email address (got {value!r})"
    return None


def _check_ssl_mode(value: str) -> str | None:
    if not value:
        return None
    if value not in SSL_MODES:
        return f"Must be one of: {', '.join(sorted(SSL_MODES))} (got {value!r})"
    return None


def _check_log_level(value: str) -> str | None:
    if not value:
        return None
    if value.upper() not in LOG_LEVELS:
        return f"Must be one of: {', '.join(sorted(LOG_LEVELS))} (got {value!r})"
    return None


def _check_positive_int(value: str) -> str | None:
    if not value:
        return None
    try:
        n = int(value)
    except ValueError:
        return f"Must be an integer (got {value!r})"
    if n <= 0:
        return f"Must be a positive integer (got {n})"
    return None


def _check_writable_path(value: str) -> str | None:
    if not value:
        return None
    p = Path(value)
    if not p.exists():
        return f"Path does not exist: {value}"
    if not os.access(p, os.W_OK):
        return f"Path is not writable: {value}"
    return None
