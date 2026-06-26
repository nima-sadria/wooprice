"""WooPrice Beta — CLI config loader helper.

Thin wrapper around B3 ConfigurationManager for CLI commands that run
in pre-server mode (before the application stack is running).
"""

from __future__ import annotations

from pathlib import Path

from app.beta.config import (
    ConfigurationManager,
    ConfigProfile,
    ConfigValidator,
    ValidationResult,
    SECRET_FIELDS,
    NotLoadedError,
    ConfigurationError,
)


def load_config(env_file: Path | None) -> tuple[ConfigurationManager, ConfigProfile | None]:
    """Load config from the given .env file path (or auto-detect).

    Returns (manager, profile). If loading fails, profile is None.
    Manager.load() has already been called if no exception was raised.
    """
    manager = ConfigurationManager(env_file=env_file)
    try:
        manager.load()
        profile = manager.profile()
        return manager, profile
    except ConfigurationError:
        return manager, None


def validate_env_file(env_file: Path | None) -> ValidationResult:
    """Validate an env file using B3 ConfigValidator directly.

    Does not require a running server. Never calls sys.exit.
    """
    env_dict: dict[str, str] = {}
    if env_file is not None and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key:
                env_dict[key] = value.strip()

    validator = ConfigValidator(check_paths=False)
    return validator.validate(env_dict)


# BETA_DATABASE_URL embeds BETA_POSTGRES_PASSWORD — redact it alongside secrets
_ALL_SENSITIVE: frozenset[str] = SECRET_FIELDS | frozenset({"BETA_DATABASE_URL"})


def redact_env_dict(env_dict: dict[str, str]) -> dict[str, str]:
    """Return a copy of env_dict with all secret fields replaced by [REDACTED].

    BETA_DATABASE_URL is also redacted because it contains BETA_POSTGRES_PASSWORD inline.
    """
    return {
        k: "[REDACTED]" if k in _ALL_SENSITIVE else v
        for k, v in env_dict.items()
    }


def secret_status(env_dict: dict[str, str]) -> dict[str, str]:
    """Return {field: 'set' | 'not set'} for each secret field."""
    return {
        field: ("set" if env_dict.get(field) else "not set")
        for field in sorted(SECRET_FIELDS)
    }
