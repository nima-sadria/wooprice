# WooPrice Beta — Runtime Configuration

**Document:** RUNTIME_CONFIGURATION.md
**Series:** CP1 Architecture Specification
**Status:** CHAT2 APPROVED with modifications — 2026-06-28. Specification complete. READY FOR OWNER REVIEW. No implementation has begun.

---

## 1. Problem Statement

In the production incident (WooPrice 7.5A), the administrator needed to update the
Nextcloud URL because it had changed. The only way to do this was:

1. SSH into the production server.
2. Manually edit `.env` or the managed TOML config file.
3. Restart the application.

This is unacceptable for a few reasons:

- SSH access may not always be available from the administrator's location.
- Editing `.env` directly risks introducing syntax errors or accidentally
  corrupting other values.
- The reason the Control Plane exists is precisely to enable configuration repair
  when integrations fail — requiring SSH to repair configuration defeats this purpose.

**Runtime Configuration is the subsystem that allows certain configuration values
to be edited through the CLI (CP1) and the UI (B8+) without SSH access and without
manual file editing.**

---

## 2. What Is and Is Not Runtime-Configurable

### 2.1 Runtime-Configurable (editable via CLI and UI)

**OD2 (CHAT2 decision — 2026-06-28):** Runtime configuration in CP1 covers endpoint
location, connection behavior, and operational metadata only: URL, timeout, TLS option,
retry policy, and connection metadata. Identity fields (`nextcloud.username`) remain
`.env`-only. Changing a username may invalidate shared folder access and API tokens,
making it an installation-level decision rather than a runtime one.

These values change the behavior of integration connections. They can be edited
while the application is running, take effect immediately on the next check, and
are written to the managed TOML config file by the RuntimeConfigService.

| Key | Type | Description |
|---|---|---|
| `nextcloud.url` | URL | Nextcloud base URL |
| `nextcloud.file_path` | string | Path to spreadsheet in Nextcloud |
| `nextcloud.timeout_s` | float | Connection timeout for Nextcloud (default: 10) |
| `nextcloud.retry_max` | int | Max retry attempts for Nextcloud (default: 2) |
| `woocommerce.url` | URL | WooCommerce store URL |
| `woocommerce.timeout_s` | float | Connection timeout for WooCommerce (default: 10) |
| `woocommerce.retry_max` | int | Max retry attempts for WooCommerce (default: 2) |
| `currency_api.url` | URL | Currency API base URL |
| `currency_api.cache_ttl_s` | int | Currency API response cache TTL (default: 300) |
| `app.timezone` | tz string | Application timezone |
| `app.log_level` | enum | Log level: DEBUG, INFO, WARN, ERROR |
| `app.ssl_mode` | enum | TLS mode: off, self-signed, letsencrypt, manual |
| `health.check_interval_s` | int | Background health check interval (default: 60) |
| `health.db_check_interval_s` | int | DB health check interval (default: 30) |

### 2.2 Not Runtime-Configurable (require .env + restart or reinstall)

These values are fundamentally installation parameters. Changing them requires a
deliberate reinstall or .env edit because they affect the application's identity,
security, or infrastructure.

| Variable | Why not runtime-configurable |
|---|---|
| `BETA_JWT_SECRET` | Rotating JWT secret invalidates all active sessions — requires `wooprice configure --rotate-secret jwt` |
| `BETA_DATABASE_URL` | Changing database connection requires migration state check + restart |
| `BETA_POSTGRES_PASSWORD` | Secret; must remain in .env |
| `BETA_NEXTCLOUD_USERNAME` | Username is identity — change requires reinstall of source adapter |
| `BETA_NEXTCLOUD_PASSWORD` | Secret; must remain in .env |
| `BETA_WOOCOMMERCE_KEY` | Secret; must remain in .env |
| `BETA_WOOCOMMERCE_SECRET` | Secret; must remain in .env |
| `BETA_ADMIN_EMAIL` | Identity field |
| `BETA_ENV` | Environment label is an installation identity |
| `BETA_PORT` | Port change requires Docker and Nginx reconfiguration |
| `BETA_DOMAIN` | Domain change requires TLS cert update |
| `BETA_STORAGE_PATH` | Path change requires data migration |

**Secrets are never stored in the managed TOML config file.** They always remain
in `.env`. The runtime configuration service never reads, writes, or references
secret values. Integration usernames and passwords are outside its scope.

---

## 3. ConfigRecord

```python
@dataclass
class ConfigRecord:
    key: str                        # e.g., "nextcloud.url"
    value: str                      # string representation; typed at validation
    previous_value: Optional[str]   # value before this change; None if new
    changed_by: str                 # "cli" or "api:<user_id>"
    changed_at: datetime
    validated: bool                 # True if B3 ConfigValidator accepted this value
    applied: bool                   # True if ConnectionManager reloaded this value


@dataclass
class ConfigChangeEvent:
    record: ConfigRecord
    requires_restart: bool          # True for values needing service restart
    restart_services: list[str]     # e.g., ["app", "worker"] — empty if no restart needed
```

---

## 4. RuntimeConfigService

`app/beta/runtime_config/service.py`

```python
class RuntimeConfigService:

    def get(self, key: str) -> Optional[str]:
        """Return current value for key. Returns None if key is not set."""

    def set(self, key: str, value: str, changed_by: str) -> ConfigRecord:
        """
        Validate, write to managed TOML, notify ConnectionManager.
        Raises ConfigurationError if value is invalid.
        Raises ProtectedKeyError if key is not runtime-configurable.
        Writes to audit log.
        """

    def get_all(self) -> dict[str, str]:
        """Return all runtime-configurable keys and their current values.
        Never includes secret values."""

    def validate(self, key: str, value: str) -> ValidationResult:
        """Validate a value without writing it. Uses B3 ConfigValidator."""

    def reload_from_toml(self) -> None:
        """Re-read the managed TOML file. Called on startup and after file change."""

    def notify_connection_manager(self, key: str, value: str) -> None:
        """Notify ConnectionManager of changed URL or timeout. Triggers cache invalidation."""
```

### 4.1 Write Path

```
Administrator sets key via CLI or API
  ↓
RuntimeConfigService.set(key, value, changed_by)
  ↓
Validate: key in ALLOWED_RUNTIME_KEYS  →  raise ProtectedKeyError if not
  ↓
Validate: B3 ConfigValidator.validate_field(key, value)  →  raise ConfigurationError if invalid
  ↓
Read current managed TOML (B3 ConfigurationManager)
  ↓
Update the field in the TOML structure
  ↓
Write back to managed TOML file (atomic: write to .tmp, then os.replace)
  ↓
Write ConfigRecord to audit log (key, previous value, new value, changed_by, timestamp)
  ↓
Notify ConnectionManager (update service URL or timeout; invalidate cache)
  ↓
Return ConfigRecord to caller
```

### 4.2 Atomic Write

The TOML file is written atomically to prevent corruption:

1. Write new content to `<toml_path>.tmp`
2. `os.replace("<toml_path>.tmp", toml_path)` — atomic rename on POSIX systems
3. If any step fails, `.tmp` is removed; original file is unchanged

### 4.3 Restart Detection

When a key change requires a service restart, the RuntimeConfigService:
1. Sets `ConfigRecord.requires_restart = True`
2. Sets `ConfigRecord.restart_services` to the list of affected services
3. Returns the record to the CLI or API caller
4. The CLI shows a warning: "⚠ This change requires a service restart to take effect."
5. The CLI optionally triggers restart: `wooprice configure set <key> <value> --restart`

In CP1, no Docker services are running, so restart is a no-op and only the TOML
is updated. The restart logic is fully implemented in B6.

---

## 5. CLI Contract

### wooprice configure show

```
$ python -m cli.main configure show

[BETA ENVIRONMENT]  WooPrice Beta — Current Configuration

Section: nextcloud
  url                https://nextcloud.example.com
  file_path          /Documents/WooPrice/prices.xlsx
  timeout_s          10.0
  retry_max          2
  username           admin               (from .env — read-only here)
  password           [REDACTED]          (from .env — read-only here)

Section: woocommerce
  url                https://shop.example.com
  timeout_s          10.0
  retry_max          2
  key                [REDACTED]          (from .env — read-only here)
  secret             [REDACTED]          (from .env — read-only here)

Section: app
  timezone           Europe/Amsterdam
  log_level          INFO
  ssl_mode           letsencrypt

Note: Secrets are never shown. Use 'wooprice configure --rotate-secret' to rotate secrets.
```

### wooprice configure set

```
$ python -m cli.main configure set nextcloud.url https://new-nextcloud.example.com

[BETA ENVIRONMENT]

Validating...  ✓ Valid URL

Previous value:  https://nextcloud.example.com
New value:       https://new-nextcloud.example.com

Save this change? [y/N]: y

✓  Saved to managed configuration.
✓  Connection Manager notified — cache cleared for Nextcloud.
   Run 'wooprice integrations test nextcloud' to verify the new URL.
```

### wooprice configure get

```
$ python -m cli.main configure get nextcloud.url

https://nextcloud.example.com
```

### wooprice configure verify

```
$ python -m cli.main configure verify

[BETA ENVIRONMENT]  Configuration Verification

  ✓  All 22 required BETA_* variables are set
  ✓  BETA_NEXTCLOUD_URL: valid URL format
  ✓  BETA_WOOCOMMERCE_URL: valid URL format
  ✓  BETA_JWT_SECRET: 64+ characters
  ✓  BETA_TIMEZONE: valid IANA timezone
  ✓  Managed TOML: consistent with environment variables

  Status: VALID — 0 errors, 0 warnings
```

---

## 6. API Contract (B8 UI)

### GET /api/v2/config/

Returns all runtime-configurable keys and their current values. Secrets are never
included in the response. Admin permission required.

```json
{
  "config": {
    "nextcloud.url": "https://nextcloud.example.com",
    "nextcloud.file_path": "/Documents/WooPrice/prices.xlsx",
    "nextcloud.timeout_s": "10.0",
    "nextcloud.retry_max": "2",
    "woocommerce.url": "https://shop.example.com",
    "woocommerce.timeout_s": "10.0",
    "app.log_level": "INFO",
    "app.timezone": "Europe/Amsterdam"
  },
  "read_only_keys": ["nextcloud.username", "woocommerce.key"],
  "read_only_note": "Secrets and identity fields are managed via .env only."
}
```

### PUT /api/v2/config/{key}

Updates a single runtime-configurable key. Admin permission required.

```json
// Request
{"value": "https://new-nextcloud.example.com"}

// Response (success)
{
  "key": "nextcloud.url",
  "previous_value": "https://nextcloud.example.com",
  "new_value": "https://new-nextcloud.example.com",
  "validated": true,
  "applied": true,
  "requires_restart": false,
  "message": "Configuration updated. Cache cleared for Nextcloud."
}

// Response (validation error)
{
  "error": "validation_failed",
  "key": "nextcloud.url",
  "message": "Value must be a valid URL with http:// or https:// scheme.",
  "value": "not-a-url"
}

// Response (protected key)
{
  "error": "protected_key",
  "key": "BETA_JWT_SECRET",
  "message": "This key cannot be updated through the API. Use 'wooprice configure --rotate-secret jwt'."
}
```

### POST /api/v2/config/validate

Validates a key-value pair without writing.

```json
// Request
{"key": "nextcloud.url", "value": "https://new-nextcloud.example.com"}

// Response
{"valid": true, "message": "Valid URL"}
```

---

## 7. Audit Trail

Every configuration change is written to the audit log with:
- Timestamp
- Key changed
- Previous value (or `[NOT SET]`)
- New value (secrets are `[REDACTED]`; URLs are logged in full)
- Who made the change: `cli` or `api:<user_email>`
- Whether the change was applied immediately or requires restart

```json
{
  "event": "config_change",
  "timestamp": "2026-06-28T10:35:00Z",
  "key": "nextcloud.url",
  "previous_value": "https://nextcloud.example.com",
  "new_value": "https://new-nextcloud.example.com",
  "changed_by": "api:admin@example.com",
  "validated": true,
  "applied": true,
  "requires_restart": false
}
```

---

## 8. Relationship to B3 Configuration Foundation

**OD6 (CHAT2 decision — 2026-06-28):** `RuntimeConfigService` is implemented as a
separate service in `app/beta/runtime_config/`. B3 `ConfigurationManager` remains
read-only. CP1 does not modify any B3 file or behavior.

RuntimeConfigService is a **consumer** of B3 — it does not replace or modify B3.

| B3 component | How CP1 uses it |
|---|---|
| `ConfigurationManager` | Used to read the current managed TOML on load and after changes |
| `ConfigValidator` | Used to validate values before writing |
| `BetaConfig` | Read at startup to populate initial ConfigRecord values |
| `EnvironmentLoader` | Not used by RuntimeConfigService — only reads TOML |

The managed TOML file format is defined by B3. RuntimeConfigService writes updates
using the same TOML structure.

---

## 9. Relationship to B7 Authentication

The RuntimeConfigService endpoint (`PUT /api/v2/config/{key}`) is protected by JWT
and requires admin permission. This is consistent with all admin-only endpoints.

During an integration outage (the scenario RuntimeConfigService is specifically
designed for), the administrator must be logged in to use the API. Because login
is local (B7 invariant), the administrator can always authenticate and then use
the Runtime Configuration editor to repair the integration endpoint.

This is the correct sequence:
```
Integration fails → Administrator logs in locally (no Nextcloud needed)
  → Opens Settings / Runtime Configuration
  → Updates endpoint URL
  → Saves
  → Runs health check
  → Integration recovers
```
