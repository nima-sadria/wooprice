# WooPrice Beta — Configuration Core

**Phase:** B3 Configuration Foundation  
**Architecture:** Framework-independent. No FastAPI, Typer, or HTTP imports.

---

## Quick Start

```python
from pathlib import Path
from app.beta.config import ConfigurationManager

manager = ConfigurationManager(env_file=Path(".env"))
manager.load()
result = manager.validate()
if not result:
    print(result.format_errors())
    raise SystemExit(1)
config = manager.get()
print(config.domain)
print(config.jwt_secret.get_secret_value())  # SecretStr — use .get_secret_value()
```

---

## Environment Variables

### Required (22)

| Variable | Type | Validation |
|---|---|---|
| `BETA_ENV` | `dev` \| `beta` \| `production` | Enum membership |
| `BETA_DOMAIN` | string | Non-empty |
| `BETA_PORT` | integer | 1024–65535 |
| `BETA_DATABASE_URL` | string | `postgresql://` prefix |
| `BETA_POSTGRES_DB` | string | Non-empty |
| `BETA_POSTGRES_USER` | string | Non-empty |
| `BETA_POSTGRES_PASSWORD` | **secret** | Non-empty |
| `BETA_JWT_SECRET` | **secret** | Min 64 chars |
| `BETA_REST_API_SECRET` | **secret** | Min 32 chars |
| `BETA_NEXTCLOUD_URL` | URL | `http(s)://` prefix |
| `BETA_NEXTCLOUD_FILE_PATH` | path | Non-empty |
| `BETA_NEXTCLOUD_USERNAME` | string | Non-empty |
| `BETA_NEXTCLOUD_PASSWORD` | **secret** | Non-empty |
| `BETA_WOOCOMMERCE_URL` | URL | `http(s)://` prefix |
| `BETA_WOOCOMMERCE_KEY` | **secret** | Non-empty |
| `BETA_WOOCOMMERCE_SECRET` | **secret** | Non-empty |
| `BETA_TIMEZONE` | IANA tz string | `zoneinfo.ZoneInfo()` |
| `BETA_CURRENCY` | ISO 4217 | 3 uppercase letters |
| `BETA_ADMIN_EMAIL` | email | Basic format check |
| `BETA_STORAGE_PATH` | path | Exists + writable |
| `BETA_BACKUP_PATH` | path | Exists + writable |
| `BETA_SSL_MODE` | enum | `off` \| `self-signed` \| `letsencrypt` \| `manual` |

### Optional (8, with defaults)

| Variable | Default | Description |
|---|---|---|
| `BETA_LOG_LEVEL` | `INFO` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` \| `CRITICAL` |
| `BETA_JWT_ACCESS_TTL_MINUTES` | `15` | Access token lifetime |
| `BETA_JWT_REFRESH_TTL_DAYS` | `7` | Refresh token lifetime |
| `BETA_MAX_UPLOAD_MB` | `50` | Max upload size in MB |
| `BETA_PLUGIN_DIR` | `$BETA_STORAGE_PATH/plugins` | Plugin installation directory |
| `BETA_WORKER_CONCURRENCY` | `2` | Background worker concurrency |
| `BETA_SCHEDULER_POLL_SECONDS` | `30` | Scheduler polling interval |
| `BETA_BACKUP_RETAIN_DAYS` | `30` | Backup retention period |

---

## Secret Separation Model

Secrets live **only** in environment variables (`.env` file, mode 600).  
They are **never** stored in:
- The managed TOML config file (`$BETA_STORAGE_PATH/config/wooprice-beta.toml`)
- The database
- Log files
- API responses

The six secret variables are `BETA_JWT_SECRET`, `BETA_REST_API_SECRET`,
`BETA_POSTGRES_PASSWORD`, `BETA_NEXTCLOUD_PASSWORD`, `BETA_WOOCOMMERCE_KEY`,
`BETA_WOOCOMMERCE_SECRET`. They are declared in `SECRET_FIELDS`.

In `BetaConfig`, secrets are `pydantic.SecretStr`. They are redacted in `repr()`
and `str()`. To access the raw value: `config.jwt_secret.get_secret_value()`.

---

## Profile Behavior

| Profile | `BETA_ENV` value | CLI banner | Behavior |
|---|---|---|---|
| `ConfigProfile.BETA` | `"beta"` | `[BETA ENVIRONMENT]` | Normal Beta operation |
| `ConfigProfile.DEV` | `"dev"` | `[DEVELOPMENT ENVIRONMENT]` | Debug output; relaxed guards |
| `ConfigProfile.PRODUCTION` | `"production"` | `[PRODUCTION]` | All guards active; destructive CLI ops blocked |

---

## Validation

`ConfigValidator.validate(env)` never raises. It returns a `ValidationResult`:

```python
result = manager.validate()
if not result.is_valid:
    print(result.format_errors())  # structured field-level errors
if result.warnings:
    print(result.format_warnings())
```

Errors list all problems at once — no fail-fast. Callers decide whether to abort.

Path existence and writability checks (`BETA_STORAGE_PATH`, `BETA_BACKUP_PATH`)
can be disabled with `ConfigValidator(check_paths=False)` for unit tests.

---

## Managed TOML Config File

The installer (B4) writes `$BETA_STORAGE_PATH/config/wooprice-beta.toml`.

The config file may contain `${VAR}` placeholders referencing env vars.
These are expanded at read time by `expand_placeholders()`. Expanded values
are never written back to disk.

```toml
[meta]
version = "beta-1.0.0"

[app]
env = "${BETA_ENV}"
domain = "${BETA_DOMAIN}"
port = 8080
```

To check for drift between live env and config file:

```python
drifts = manager.verify()
for drift in drifts:
    print(drift)
```

---

## Emergency Manual Editing

Manual edits to `.env` or the TOML config are emergency-only. After any manual
edit, run:

```python
manager.load()
drifts = manager.verify()
```

(or: `wooprice configure --verify` once CLI is implemented in B5)

---

## Config Migration

When upgrading WooPrice Beta between versions, `manager.migrate()` applies any
necessary schema changes to the TOML config dict:

```python
changes = manager.migrate()
for change in changes:
    print(f"Migrated: {change}")
```

File write after migration is implemented in B4 (Installer Foundation).
