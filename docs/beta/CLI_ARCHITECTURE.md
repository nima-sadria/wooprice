# WooPrice Beta — CLI Architecture

**Document:** CLI_ARCHITECTURE.md
**Series:** B1 Architecture Blueprint

---

## Overview

The `wooprice` CLI is the first-class management tool for WooPrice Beta. It covers
installation, configuration, operations, and administration — without requiring the
operator to edit configuration files manually.

**Technology:** Python · Typer · Rich

---

## Design Principles

1. **Environment safety first** — every command verifies the active environment and
   displays a persistent `[BETA]` banner before executing.
2. **Idempotent** — running the same command twice produces the same result or an
   informative "already done" message.
3. **Dry run by default for destructive operations** — all commands that modify state
   accept `--dry-run` and show what would happen before asking for confirmation.
4. **Never requires manual config editing** — all normal operations are achievable
   through the CLI.
5. **Two operating modes:**
   - **Pre-server mode** (install, configure): reads managed config files directly,
     does not require a running application.
   - **Connected mode** (operational commands): calls the running API through
     `cli/shared/api_client.py`.

---

## Entry Point

```
wooprice [--env <path>] [--json] [--no-color] <group> [subcommand] [options]
```

**Global flags:**

| Flag | Description |
|---|---|
| `--env <path>` | Path to `.env` file (default: auto-detected) |
| `--json` | Output structured JSON (for scripting and monitoring) |
| `--no-color` | Disable Rich color output |
| `--version` | Print installed version and exit |
| `--help` | Print help and exit |

On every invocation, the CLI:
1. Detects the environment (`BETA_ENV`)
2. Prints the environment banner (`[BETA ENVIRONMENT]`)
3. Validates connectivity (if in connected mode)
4. Executes the requested command

---

## Interactive Console

`wooprice` with no arguments opens an interactive REPL-style console:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  WooPrice  [BETA ENVIRONMENT]
  Version: 1.0.0  |  Status: Running
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Type a command, or 'help' for available commands.
  Type 'exit' to quit.

wooprice> _
```

The interactive console provides tab completion for command groups and subcommands.

---

## Command Hierarchy

```
wooprice
├── install         Interactive installation wizard
├── configure       Configuration management
│   ├── show        Display current config (secrets redacted)
│   ├── set         Set a single configuration value
│   ├── verify      Check config consistency; detect drift
│   └── rotate      Rotate a secret (jwt / api-key / db-password)
├── status          System status summary
├── health          Deep health check
│   ├── db          Database connectivity check
│   ├── sources     Source adapter health check
│   ├── channels    Channel adapter health check
│   └── all         Run all health checks
├── migrate         Database migration management
│   ├── status      Show current and pending migrations
│   ├── up          Run pending migrations
│   └── history     Show migration history
├── backup
│   ├── create      Create a backup now
│   ├── list        List available backups
│   └── restore     Restore from a backup
├── logs            Log streaming and export
│   ├── tail        Stream logs live
│   ├── show        Show recent log lines
│   └── export      Export logs to a file
├── update          Version management
│   ├── check       Check for available updates
│   └── apply       Apply an update (auto-backup before applying)
├── adapters        Plugin adapter management
│   ├── list        List installed adapters
│   ├── install     Install an adapter plugin
│   ├── enable      Enable an installed adapter
│   ├── disable     Disable an active adapter
│   └── remove      Uninstall an adapter
├── channels        Channel configuration
│   ├── list        List configured channels
│   ├── add         Add a channel
│   ├── test        Test channel connectivity
│   └── remove      Remove a channel configuration
├── sources         Source configuration
│   ├── list        List configured sources
│   ├── add         Add a source
│   ├── test        Test source connectivity and read access
│   └── remove      Remove a source configuration
├── users           User management
│   ├── list        List all users
│   ├── create      Create a new user
│   ├── set-role    Set user role/permissions
│   ├── deactivate  Deactivate a user (non-destructive)
│   └── reset-pw    Send password reset to a user
├── scheduler       Scheduled execution management
│   ├── list        List schedules (all / due / active)
│   ├── pause       Pause a schedule
│   ├── resume      Resume a paused schedule
│   └── cancel      Cancel a schedule
├── ai              AI Foundation management
│   ├── status      Show AI feature status
│   ├── insights    List recent advisory insights
│   └── toggle      Enable or disable AI feature flag
└── diagnostics     Full diagnostic suite
    ├── run         Run all diagnostics; output report
    └── report      Export last diagnostic report
```

---

## Command Specifications

### `wooprice install`

Runs the full interactive installation wizard. See [INSTALLER_ARCHITECTURE.md](INSTALLER_ARCHITECTURE.md).

```
wooprice install [--non-interactive] [--config-file <path>]
```

- `--non-interactive` + `--config-file <path>`: reads all answers from a YAML file
  (for automated deployment testing — never used in production installs)

---

### `wooprice configure`

```
wooprice configure show
wooprice configure set --key BETA_DOMAIN --value new.example.com
wooprice configure verify
wooprice configure rotate --secret jwt
```

`configure show` output (example — placeholders only in actual output):
```
WooPrice Beta Configuration [BETA ENVIRONMENT]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Domain:       BETA_DOMAIN
  Port:         BETA_PORT
  SSL Mode:     BETA_SSL_MODE
  Timezone:     BETA_TIMEZONE
  Currency:     BETA_CURRENCY
  DB:           BETA_POSTGRES_DB @ postgres:5432
  JWT Secret:   ••••••••••••••••••••••••••••••••  [set]
  API Secret:   ••••••••••••••••••••••••••••••••  [set]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

Secrets are always redacted in `configure show` output. They are never written to
the terminal, log files, or JSON output.

---

### `wooprice status`

```
wooprice status [--json]
```

Returns a summary of all services:

```
WooPrice Beta  [BETA ENVIRONMENT]  v1.0.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  app         ● Running    (up 2d 14h)
  frontend    ● Running    (up 2d 14h)
  postgres    ● Running    (up 2d 14h)
  cache       ● Running    (up 2d 14h)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Migrations  ● Current    (a2_008, beta_003)
  Scheduler   ● Active     (2 schedules, 0 due)
  AI          ● Enabled
  Plugins     ● 1 installed, 1 active
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

### `wooprice health`

```
wooprice health [all | db | sources | channels] [--json]
```

Performs live checks:
- `db`: connects to PostgreSQL and SQLite; reports latency
- `sources`: attempts to read from configured source adapters
- `channels`: attempts connectivity check to configured channels (read-only probe)
- `all`: runs all checks; exits with non-zero if any fail

---

### `wooprice migrate`

```
wooprice migrate status
wooprice migrate up [--revision <rev>]
wooprice migrate history
```

Wraps Alembic. Before any `migrate up`, automatically creates a backup checkpoint.

---

### `wooprice backup create`

```
wooprice backup create [--label <label>] [--path <output-path>]
```

1. Creates timestamped directory in `BETA_BACKUP_PATH`
2. Runs `pg_dump` on the A2 PostgreSQL database
3. Dumps the Beta SQLite config database
4. Archives `BETA_STORAGE_PATH/` (excluding logs separately)
5. Writes `backup_manifest.json`
6. Reports archive size and checksum

### `wooprice backup restore`

```
wooprice backup restore <backup-id> [--yes]
```

**Warning banner:**
```
⚠  WARNING: This will overwrite the current database and storage.
   The current state will be LOST unless you have a separate backup.
   Active environment: [BETA ENVIRONMENT]

Type the backup ID to confirm, or Ctrl+C to abort:
> _
```

Restoration steps:
1. Stop the application service
2. Restore PostgreSQL from dump
3. Restore Beta SQLite database
4. Restore `BETA_STORAGE_PATH/`
5. Run `wooprice migrate status` to verify migration state
6. Start the application service

---

### `wooprice logs tail`

```
wooprice logs tail [--service app|scheduler|access] [--level INFO|WARN|ERROR]
```

Streams structured logs to the terminal using Docker's log following (`docker compose logs -f`).
Secrets appearing in log fields are replaced with `[REDACTED]`.

---

### `wooprice update apply`

```
wooprice update apply [--version <v>] [--dry-run]
```

Steps:
1. Check for running schedules (warn if any are active)
2. Create pre-update backup automatically
3. Pull new Docker image or release archive
4. Run `wooprice migrate up`
5. Restart services
6. Run `wooprice health all`
7. Report success or roll back on failure

---

### `wooprice adapters`

```
wooprice adapters list
wooprice adapters install --from <path|url>
wooprice adapters enable <plugin-id>
wooprice adapters disable <plugin-id>
wooprice adapters remove <plugin-id> [--yes]
```

Plugin install validates the manifest, checks version compatibility, copies plugin
files to `BETA_PLUGIN_DIR`, and registers the plugin in the database. No manual
file copying is needed.

---

### `wooprice diagnostics run`

```
wooprice diagnostics run [--output <path>]
```

Runs the full diagnostic suite:

1. Configuration consistency check
2. Database connectivity and schema check
3. Source adapter reachability
4. Channel adapter reachability
5. Storage path accessibility
6. Backup path accessibility
7. JWT secret strength check
8. Feature flag consistency
9. Plugin manifest validation
10. Migration status check

Produces a structured report written to the output path (default:
`BETA_STORAGE_PATH/diagnostics/YYYY-MM-DD_HHMMSS_diagnostics.json`).

---

## Error Handling

All CLI commands follow a consistent error handling pattern:

1. **Validate inputs** before any destructive action
2. **Display a clear error message** — never raw Python tracebacks (in non-debug mode)
3. **Exit with non-zero code** on any failure
4. **Log the error** to `BETA_STORAGE_PATH/logs/audit.log`
5. **Suggest recovery** — every error message includes what to do next

Example:
```
✗ Error: Cannot connect to PostgreSQL database
  Host: postgres:5432
  Error: connection refused

  Troubleshooting:
  1. Check that the postgres container is running: docker compose ps
  2. Verify BETA_DATABASE_URL in your .env file
  3. Run: wooprice health db
```

---

## Recovery Behavior

| Failure scenario | CLI behavior |
|---|---|
| `migrate up` fails mid-migration | Alert user; provide rollback command; do not silently continue |
| `backup restore` fails | Abort; restore from pre-restore checkpoint if it exists; log failure |
| `update apply` migration fails | Roll back to pre-update backup automatically; report failure |
| `adapters install` manifest invalid | Abort; display validation errors; do not install partial plugin |
| `configure rotate` fails mid-rotation | Leave old secret in place; log failure; do not write partial state |

---

## Environment Safety Warnings

The CLI enforces environment safety at multiple layers:

1. **Banner on every invocation:** The `[BETA ENVIRONMENT]` banner is printed before
   every command — it cannot be suppressed.

2. **`BETA_ENV` guard:** If `BETA_ENV=production` is detected (indicating misconfiguration),
   the CLI prints a DANGER warning and requires `--i-know-what-i-am-doing` for any
   write operation.

3. **Production resource detection:** Before any destructive operation, the CLI checks
   that the configured database URL, WooCommerce URL, and Nextcloud URL are not known
   production values (checked against an allowlist stored in the managed config).

4. **Never writes Production WooPrice config:** The CLI checks the application version
   and config format before writing any file — it will refuse to write if it detects
   a Production WooPrice configuration file.
