"""WooPrice Beta — Configuration Manager.

Framework-independent orchestrator for all configuration concerns.
Usable from backend, CLI, installer, tests, and future services
without any FastAPI, Typer, or other framework dependency.

Public API:
    load()      — load env vars and optional TOML config file
    validate()  — run all validators; return ValidationResult (never raises)
    get()       — return typed BetaConfig; raise if not loaded or invalid
    set()       — update a single value in-memory (file write: B4)
    verify()    — compare live env with TOML config file; return drift list
    profile()   — return the current ConfigProfile
    migrate()   — apply config file schema migration; return change list
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from .defaults import DEFAULTS
from .expander import expand_placeholders
from .loader import ConfigurationError, EnvironmentLoader
from .migration import ConfigMigration
from .profiles import ConfigProfile
from .schema import BetaConfig
from .secrets import EnvSecretProvider, SecretProvider, SECRET_FIELDS
from .validation import ConfigValidator, ValidationResult

_TOML_PATH_TO_ENV: dict[str, str] = {
    "app.env": "BETA_ENV",
    "app.domain": "BETA_DOMAIN",
    "app.port": "BETA_PORT",
    "app.timezone": "BETA_TIMEZONE",
    "app.currency": "BETA_CURRENCY",
    "app.storage_path": "BETA_STORAGE_PATH",
    "app.backup_path": "BETA_BACKUP_PATH",
    "app.ssl_mode": "BETA_SSL_MODE",
    "app.log_level": "BETA_LOG_LEVEL",
    "database.postgres_db": "BETA_POSTGRES_DB",
    "database.postgres_user": "BETA_POSTGRES_USER",
    "source.nextcloud_url": "BETA_NEXTCLOUD_URL",
    "source.nextcloud_file_path": "BETA_NEXTCLOUD_FILE_PATH",
    "source.nextcloud_username": "BETA_NEXTCLOUD_USERNAME",
    "channel.woocommerce_url": "BETA_WOOCOMMERCE_URL",
}


class NotLoadedError(ConfigurationError):
    """Raised when get() or verify() is called before load()."""


class NotValidError(ConfigurationError):
    """Raised when get() is called but validation has errors."""


class ConfigurationManager:
    """Framework-independent configuration manager for WooPrice Beta."""

    def __init__(
        self,
        env_file: Path | None = None,
        config_file: Path | None = None,
        secret_provider: SecretProvider | None = None,
        check_paths: bool = True,
    ) -> None:
        self._env_file = env_file
        self._config_file = config_file
        self._secret_provider = secret_provider or EnvSecretProvider()
        self._check_paths = check_paths
        self._loader = EnvironmentLoader()
        self._migration = ConfigMigration()
        self._env: dict[str, str] = {}
        self._config_dict: dict[str, Any] = {}
        self._config: BetaConfig | None = None
        self._loaded = False
        self._validation_result: ValidationResult | None = None

    # ── Core API ────────────────────────────────────────────────────────────

    def load(self, env_file: Path | None = None) -> None:
        """Load environment variables and the optional managed TOML config file.

        If env_file is provided here, it overrides the one passed at construction.
        Safe to call multiple times — re-loading resets cached state.
        """
        effective_env_file = env_file or self._env_file
        self._env = self._loader.load(effective_env_file)
        self._apply_defaults()

        self._config_dict = {}
        if self._config_file and self._config_file.exists():
            raw_toml = self._config_file.read_text(encoding="utf-8")
            expanded = expand_placeholders(raw_toml, self._env)
            self._config_dict = tomllib.loads(expanded)

        self._loaded = True
        self._config = None
        self._validation_result = None

    def validate(self) -> ValidationResult:
        """Validate all configuration values. Never raises — returns ValidationResult.

        Callers interpret the result and decide whether to abort, warn, or proceed.
        Successful validation is a precondition for get().
        """
        if not self._loaded:
            self.load()

        validator = ConfigValidator(check_paths=self._check_paths)
        result = validator.validate(self._env)
        self._validation_result = result
        return result

    def get(self) -> BetaConfig:
        """Return the typed BetaConfig object.

        Raises NotLoadedError if load() has not been called.
        Raises NotValidError if validate() found errors.
        Auto-validates if validate() has not been called yet.
        """
        if not self._loaded:
            raise NotLoadedError("Call load() before get()")
        if self._validation_result is None:
            self.validate()
        if not self._validation_result.is_valid:
            count = len(self._validation_result.errors)
            raise NotValidError(
                f"Configuration has {count} error(s):\n"
                + self._validation_result.format_errors()
            )
        if self._config is None:
            self._config = BetaConfig.from_env(self._env)
        return self._config

    def set(self, key: str, value: str) -> None:
        """Update a configuration value.

        Updates the in-memory env dict immediately. Persisting to the TOML
        config file is implemented in B4 (Installer Foundation).
        Invalidates the cached BetaConfig and ValidationResult.
        """
        self._env[key] = value
        self._config = None
        self._validation_result = None

    def verify(self) -> list[str]:
        """Compare the live env with the managed TOML config file.

        Returns a list of drift descriptions. Empty list means no drift.
        Secrets are never included in drift output — only "value differs" is noted.
        """
        if not self._loaded:
            self.load()

        if not self._config_dict:
            return []

        drifts: list[str] = []
        flat = _flatten_toml(self._config_dict)

        for toml_path, toml_val in flat.items():
            if toml_path.startswith("meta."):
                continue
            env_name = _TOML_PATH_TO_ENV.get(toml_path)
            if env_name is None:
                continue
            env_val = self._env.get(env_name, "")
            if str(toml_val) != env_val:
                if env_name in SECRET_FIELDS:
                    drifts.append(f"{env_name}: value differs (secret — not shown)")
                else:
                    drifts.append(
                        f"{env_name}: env={env_val!r}, config_file={str(toml_val)!r}"
                    )

        return drifts

    def profile(self) -> ConfigProfile:
        """Return the current ConfigProfile (DEV, BETA, or PRODUCTION)."""
        if not self._loaded:
            self.load()
        env_value = self._env.get("BETA_ENV", "beta")
        return ConfigProfile.from_string(env_value)

    def migrate(self) -> list[str]:
        """Apply config file schema migration if needed.

        Returns a list of applied change descriptions. Empty list if no migration
        was needed. Does not write the migrated config to disk in B3 — file
        persistence is implemented in B4 (Installer Foundation).
        """
        if not self._loaded:
            self.load()

        if not self._config_dict:
            return []

        updated, changes = self._migration.migrate(self._config_dict)
        if changes:
            self._config_dict = updated
        return changes

    # ── Private helpers ──────────────────────────────────────────────────────

    def _apply_defaults(self) -> None:
        for key, default in DEFAULTS.items():
            if not self._env.get(key):
                self._env[key] = str(default)
        if not self._env.get("BETA_PLUGIN_DIR") and self._env.get("BETA_STORAGE_PATH"):
            self._env["BETA_PLUGIN_DIR"] = f"{self._env['BETA_STORAGE_PATH']}/plugins"


def _flatten_toml(d: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Recursively flatten a nested TOML dict to dot-notation keys."""
    result: dict[str, Any] = {}
    for key, value in d.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            result.update(_flatten_toml(value, full_key))
        else:
            result[full_key] = value
    return result
