"""WooPrice Beta — Configuration schema (Pydantic v2).

BetaConfig is the typed, immutable configuration object returned by
ConfigurationManager.get(). All consumers receive this object — never
raw env vars or dicts.

Secrets are stored as pydantic.SecretStr so they are redacted in repr()
and __str__(). Callers use .get_secret_value() to access the raw value.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from .defaults import DEFAULTS, LOG_LEVELS, SSL_MODES
from .profiles import ConfigProfile


class BetaConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    # Profile
    env: ConfigProfile = Field(description="Deployment environment")

    # Network
    domain: str = Field(min_length=1, description="Hostname where Beta is served")
    port: int = Field(ge=1024, le=65535, description="Application server port")
    ssl_mode: str = Field(description="SSL termination mode")

    # Database (connection string is the authoritative source)
    database_url: str = Field(min_length=1, description="Full PostgreSQL connection URL")
    postgres_db: str = Field(min_length=1)
    postgres_user: str = Field(min_length=1)
    postgres_password: SecretStr

    # JWT and API secrets (auth implemented in B7; schema defined here)
    jwt_secret: SecretStr
    rest_api_secret: SecretStr

    # Nextcloud source
    nextcloud_url: str = Field(min_length=1)
    nextcloud_file_path: str = Field(min_length=1)
    nextcloud_username: str = Field(min_length=1)
    nextcloud_password: SecretStr

    # WooCommerce channel
    woocommerce_url: str = Field(min_length=1)
    woocommerce_key: SecretStr
    woocommerce_secret: SecretStr

    # Locale
    timezone: str = Field(min_length=1)
    currency: str = Field(min_length=3, max_length=3)

    # Admin bootstrap
    admin_email: str = Field(min_length=1)

    # Storage paths
    storage_path: str = Field(min_length=1)
    backup_path: str = Field(min_length=1)
    plugin_dir: str = Field(default="", description="Plugin installation directory")

    # Optional with defaults
    log_level: str = Field(default=str(DEFAULTS["BETA_LOG_LEVEL"]))
    jwt_access_ttl_minutes: int = Field(
        default=int(DEFAULTS["BETA_JWT_ACCESS_TTL_MINUTES"]), ge=1
    )
    jwt_refresh_ttl_days: int = Field(
        default=int(DEFAULTS["BETA_JWT_REFRESH_TTL_DAYS"]), ge=1
    )
    max_upload_mb: int = Field(default=int(DEFAULTS["BETA_MAX_UPLOAD_MB"]), ge=1)
    worker_concurrency: int = Field(
        default=int(DEFAULTS["BETA_WORKER_CONCURRENCY"]), ge=1
    )
    scheduler_poll_seconds: int = Field(
        default=int(DEFAULTS["BETA_SCHEDULER_POLL_SECONDS"]), ge=1
    )
    backup_retain_days: int = Field(
        default=int(DEFAULTS["BETA_BACKUP_RETAIN_DAYS"]), ge=1
    )

    # ── Validators ──────────────────────────────────────────────────────────

    @field_validator("ssl_mode")
    @classmethod
    def validate_ssl_mode(cls, v: str) -> str:
        if v not in SSL_MODES:
            raise ValueError(f"Must be one of: {', '.join(sorted(SSL_MODES))}")
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        if v.upper() not in LOG_LEVELS:
            raise ValueError(f"Must be one of: {', '.join(sorted(LOG_LEVELS))}")
        return v.upper()

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        if not re.match(r"^[A-Z]{3}$", v):
            raise ValueError("Must be a 3-letter uppercase ISO 4217 code")
        return v

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        import zoneinfo
        try:
            zoneinfo.ZoneInfo(v)
        except Exception:
            raise ValueError(
                f"Must be a valid IANA timezone string (got {v!r}). "
                "Install tzdata package if running in a minimal environment."
            )
        return v

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        valid_prefixes = (
            "postgresql://",
            "postgresql+asyncpg://",
            "postgresql+psycopg2://",
        )
        if not v.startswith(valid_prefixes):
            raise ValueError("Must be a valid PostgreSQL connection string")
        return v

    @field_validator("nextcloud_url", "woocommerce_url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not re.match(r"^https?://", v, re.IGNORECASE):
            raise ValueError("Must be a valid URL with http:// or https:// scheme")
        return v

    @field_validator("jwt_secret")
    @classmethod
    def validate_jwt_secret(cls, v: SecretStr) -> SecretStr:
        if len(v.get_secret_value()) < 64:
            raise ValueError("Must be at least 64 characters")
        return v

    @field_validator("rest_api_secret")
    @classmethod
    def validate_rest_api_secret(cls, v: SecretStr) -> SecretStr:
        if len(v.get_secret_value()) < 32:
            raise ValueError("Must be at least 32 characters")
        return v

    @field_validator("postgres_password", "nextcloud_password", "woocommerce_key", "woocommerce_secret")
    @classmethod
    def validate_non_empty_secret(cls, v: SecretStr) -> SecretStr:
        if not v.get_secret_value():
            raise ValueError("Secret value must not be empty")
        return v

    @model_validator(mode="before")
    @classmethod
    def compute_plugin_dir(cls, data: dict) -> dict:  # type: ignore[override]
        if isinstance(data, dict):
            if not data.get("plugin_dir") and data.get("storage_path"):
                data["plugin_dir"] = f"{data['storage_path']}/plugins"
        return data

    # ── Convenience ─────────────────────────────────────────────────────────

    def is_production(self) -> bool:
        return self.env.is_production()

    def is_dev(self) -> bool:
        return self.env.is_dev()

    def banner(self) -> str:
        return self.env.banner()

    # ── Factory ─────────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls, env: dict[str, str]) -> "BetaConfig":
        """Build BetaConfig from a flat env var dict (BETA_* keys).

        Call ConfigurationManager.validate() before this to get structured
        errors. This method raises pydantic.ValidationError on invalid input.
        """
        def _get(name: str, default: str = "") -> str:
            return env.get(name, default) or default

        def _get_int(name: str, default: int) -> int:
            try:
                return int(env[name]) if env.get(name) else default
            except ValueError:
                return default

        storage_path = _get("BETA_STORAGE_PATH")
        plugin_dir = _get("BETA_PLUGIN_DIR") or (
            f"{storage_path}/plugins" if storage_path else ""
        )

        return cls(
            env=ConfigProfile.from_string(_get("BETA_ENV", "beta")),
            domain=_get("BETA_DOMAIN"),
            port=_get_int("BETA_PORT", 0),
            ssl_mode=_get("BETA_SSL_MODE"),
            database_url=_get("BETA_DATABASE_URL"),
            postgres_db=_get("BETA_POSTGRES_DB"),
            postgres_user=_get("BETA_POSTGRES_USER"),
            postgres_password=_get("BETA_POSTGRES_PASSWORD"),
            jwt_secret=_get("BETA_JWT_SECRET"),
            rest_api_secret=_get("BETA_REST_API_SECRET"),
            nextcloud_url=_get("BETA_NEXTCLOUD_URL"),
            nextcloud_file_path=_get("BETA_NEXTCLOUD_FILE_PATH"),
            nextcloud_username=_get("BETA_NEXTCLOUD_USERNAME"),
            nextcloud_password=_get("BETA_NEXTCLOUD_PASSWORD"),
            woocommerce_url=_get("BETA_WOOCOMMERCE_URL"),
            woocommerce_key=_get("BETA_WOOCOMMERCE_KEY"),
            woocommerce_secret=_get("BETA_WOOCOMMERCE_SECRET"),
            timezone=_get("BETA_TIMEZONE"),
            currency=_get("BETA_CURRENCY"),
            admin_email=_get("BETA_ADMIN_EMAIL"),
            storage_path=storage_path,
            backup_path=_get("BETA_BACKUP_PATH"),
            plugin_dir=plugin_dir,
            log_level=_get("BETA_LOG_LEVEL", str(DEFAULTS["BETA_LOG_LEVEL"])),
            jwt_access_ttl_minutes=_get_int(
                "BETA_JWT_ACCESS_TTL_MINUTES", int(DEFAULTS["BETA_JWT_ACCESS_TTL_MINUTES"])
            ),
            jwt_refresh_ttl_days=_get_int(
                "BETA_JWT_REFRESH_TTL_DAYS", int(DEFAULTS["BETA_JWT_REFRESH_TTL_DAYS"])
            ),
            max_upload_mb=_get_int(
                "BETA_MAX_UPLOAD_MB", int(DEFAULTS["BETA_MAX_UPLOAD_MB"])
            ),
            worker_concurrency=_get_int(
                "BETA_WORKER_CONCURRENCY", int(DEFAULTS["BETA_WORKER_CONCURRENCY"])
            ),
            scheduler_poll_seconds=_get_int(
                "BETA_SCHEDULER_POLL_SECONDS", int(DEFAULTS["BETA_SCHEDULER_POLL_SECONDS"])
            ),
            backup_retain_days=_get_int(
                "BETA_BACKUP_RETAIN_DAYS", int(DEFAULTS["BETA_BACKUP_RETAIN_DAYS"])
            ),
        )
