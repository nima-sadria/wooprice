"""WooPrice Beta — Configuration defaults and constants.

Default values applied when optional environment variables are absent.
Required variables have no defaults — absence causes startup failure.
"""

DEFAULTS: dict[str, str | int | bool] = {
    "BETA_LOG_LEVEL": "INFO",
    "BETA_JWT_ACCESS_TTL_MINUTES": 15,
    "BETA_JWT_REFRESH_TTL_DAYS": 7,
    "BETA_MAX_UPLOAD_MB": 50,
    "BETA_PLUGIN_DIR": "",  # computed at runtime: $BETA_STORAGE_PATH/plugins
    "BETA_WORKER_CONCURRENCY": 2,
    "BETA_SCHEDULER_POLL_SECONDS": 30,
    "BETA_BACKUP_RETAIN_DAYS": 30,
}

LOG_LEVELS: frozenset[str] = frozenset({
    "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"
})

SSL_MODES: frozenset[str] = frozenset({
    "off", "self-signed", "letsencrypt", "manual"
})
