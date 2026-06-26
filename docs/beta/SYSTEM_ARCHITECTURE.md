# WooPrice Beta — System Architecture

**Document:** SYSTEM_ARCHITECTURE.md
**Series:** B1 Architecture Blueprint
**Status:** APPROVED FOR IMPLEMENTATION PLANNING

---

## Overview

WooPrice Beta is a layered application built on top of the frozen A2 Platform Core.
It adds a product surface (UI, CLI, installer, plugin system) while consuming the A2
engine without modification.

```
┌─────────────────────────────────────────────────────────────────┐
│                      Product Surface Layer                       │
│                                                                  │
│   ┌──────────┐  ┌──────────┐  ┌───────────┐  ┌─────────────┐   │
│   │  Web UI   │  │   CLI    │  │ Installer │  │Plugin Mgr   │   │
│   │ (React)   │  │(wooprice)│  │  (shell)  │  │  (loader)   │   │
│   └──────────┘  └──────────┘  └───────────┘  └─────────────┘   │
├─────────────────────────────────────────────────────────────────┤
│                       API Layer (FastAPI)                        │
│                                                                  │
│   REST endpoints · Auth middleware · Feature flag gates          │
│   Plugin hook dispatch · Request validation · Rate limiting      │
├───────────────────────────────┬─────────────────────────────────┤
│   Application Services        │   Cross-cutting Concerns         │
│                               │                                  │
│   Auth Service                │   Config Manager                 │
│   User Manager                │   Feature Flag Evaluator         │
│   Plugin Registry             │   Audit Logger                   │
│   Update Manager              │   Secret Manager                 │
│   Backup Service              │   Environment Labels             │
│   Log Service                 │                                  │
├───────────────────────────────┼─────────────────────────────────┤
│         A2 Platform Core (FROZEN — consumed, never modified)     │
│                                                                  │
│   ┌────────┐ ┌────────┐ ┌─────────┐ ┌───────┐ ┌─────────────┐  │
│   │  A2.2  │ │  A2.3  │ │   A2.4  │ │  A2.5 │ │    A2.6     │  │
│   │Source  │ │ Rule   │ │ Safety  │ │Change │ │   Dry Run   │  │
│   │Adapter │ │Engine  │ │ Engine  │ │  Set  │ │   Engine    │  │
│   └────────┘ └────────┘ └─────────┘ └───────┘ └─────────────┘  │
│   ┌────────┐ ┌────────┐ ┌──────────────────────────────────┐    │
│   │  A2.7  │ │  A2.8  │ │    A2.9 — AI Foundation          │    │
│   │Execut. │ │Sched.  │ │  (advisory only — outside TEP)   │    │
│   └────────┘ └────────┘ └──────────────────────────────────┘    │
├─────────────────────────────────────────────────────────────────┤
│                        Data Layer                                │
│                                                                  │
│   PostgreSQL (A2)   SQLite (app config)   Redis (cache/session)  │
│   File storage      Backup store          Structured logs        │
└─────────────────────────────────────────────────────────────────┘
```

---

## Backend

**Technology:** Python · FastAPI · SQLAlchemy · Alembic

The backend is the existing WooPrice FastAPI application, extended with Beta-only
modules. The A2 platform package (`app/a2/`) is imported as a library — its files
are never modified for Beta concerns.

### Backend module boundaries

```
app/
├── main.py              — FastAPI app factory; mounts all routers
├── config.py            — Environment-based config loader
├── auth.py              — JWT auth; permissions; session
├── a2/                  — A2 Platform Core (FROZEN)
│   ├── models/          — ORM models (A2.1–A2.9)
│   ├── repositories/    — Persistence layer
│   ├── services/        — Business logic
│   ├── ai/              — AI Foundation (advisory only)
│   └── ...
└── beta/                — Beta-only extensions (NEW)
    ├── config/          — Configuration Manager
    ├── plugins/         — Plugin Registry and Loader
    ├── feature_flags/   — Feature Flag Evaluator
    ├── users/           — User management (extended)
    ├── audit/           — Audit log service
    ├── backup/          — Backup and restore service
    ├── update/          — Version and update manager
    └── api/             — Beta REST endpoints (v2)
```

### API versioning

- `/api/v1/` — Production-compatible endpoints (maintained for backward compatibility)
- `/api/v2/` — Beta endpoints (A2 inspector, plugin management, feature flags, AI)
- `/api/beta/` — Experimental endpoints behind `FEATURE_*` flags

### Authentication

JWT-based authentication. Tokens are:
- Short-lived access tokens (configurable TTL — default 15 minutes)
- Long-lived refresh tokens (configurable TTL — default 7 days, rotated on use)
- Signed with `BETA_JWT_SECRET` (unique per installation, never shared with Production)

All `/api/v2/` and `/api/beta/` endpoints require a valid JWT except health probes.

---

## Frontend

**Technology:** React 18 · TypeScript · Tailwind CSS · Vite

The frontend is a React SPA served from a dedicated Nginx container. It communicates
with the backend exclusively through the versioned REST API — never directly to the
database or file system.

### SPA shell structure

```
frontend/
├── src/
│   ├── App.tsx              — Root router; auth provider; feature flag provider
│   ├── auth/                — Auth context; token management; guards
│   ├── config/              — Runtime config (API base URL, env label)
│   ├── features/            — Feature-flagged UI modules
│   │   ├── dashboard/
│   │   ├── products/
│   │   ├── sources/
│   │   ├── rules/
│   │   ├── safety/
│   │   ├── changesets/
│   │   ├── dryrun/
│   │   ├── execution/
│   │   ├── scheduler/
│   │   ├── ai/
│   │   ├── plugins/
│   │   └── admin/
│   ├── components/          — Shared UI components
│   ├── hooks/               — Shared hooks
│   └── api/                 — Typed API client (auto-generated from OpenAPI)
```

### Environment labeling

The environment label (`[BETA]` / `[DEV]`) is displayed persistently in the top navigation
bar. This label is driven by the `BETA_ENV` configuration value returned from the API health
endpoint — the frontend never infers the environment from URL or hostname.

---

## CLI

**Technology:** Python · Typer · Rich

The `wooprice` CLI is a Python package installed alongside the backend. It communicates
with the running application through the API (for runtime operations) and directly with
the managed config file (for install/configure operations, before the server is running).

See [CLI_ARCHITECTURE.md](CLI_ARCHITECTURE.md) for full design.

---

## Installer

**Technology:** Bash shell script (Phase B3) — optionally promoted to Python (Phase B4+)

The installer is a self-contained script that runs on a clean Linux server, performs
prerequisite checks, runs the interactive setup wizard, generates configuration
artifacts, and launches the stack.

See [INSTALLER_ARCHITECTURE.md](INSTALLER_ARCHITECTURE.md) for full design.

---

## Configuration Manager

The Configuration Manager is a Python service within `app/beta/config/`. It owns:

- Reading and validating environment variables
- Reading and writing managed config files
- Providing a typed config object to all application services
- Reporting configuration drift on startup

Config is never read directly from `os.environ` outside of the Configuration Manager.
All other services receive config through dependency injection.

See [CONFIGURATION_ARCHITECTURE.md](CONFIGURATION_ARCHITECTURE.md) for full design.

---

## Plugin Loader

The Plugin Loader is a Python service within `app/beta/plugins/`. It:

- Discovers installed plugins from a declared plugins directory
- Validates plugin manifests (version compatibility, declared permissions)
- Registers plugins with the appropriate adapter registry or hook
- Enforces plugin isolation (plugins cannot access each other's internals)
- Provides enable/disable/reload lifecycle

See [PLUGIN_ARCHITECTURE.md](PLUGIN_ARCHITECTURE.md) for full design.

---

## Feature Flags

The Feature Flag Evaluator is a Python service within `app/beta/feature_flags/`. It:

- Reads flag values from database-backed settings on startup
- Provides a typed flag evaluation API to all services and API endpoints
- Enforces flag-level access rules (admin-only, dev-only)
- Logs flag evaluation decisions to the audit log

See [FEATURE_FLAG_ARCHITECTURE.md](FEATURE_FLAG_ARCHITECTURE.md) for full design.

---

## Authentication and Authorization

```
Request
  ↓
API Gateway (rate limiting, CORS)
  ↓
Auth Middleware
  ├── Extract JWT from Authorization: Bearer header
  ├── Validate signature against BETA_JWT_SECRET
  ├── Check expiry
  └── Load user context (id, email, permissions, is_admin)
  ↓
Permission Guard (per-endpoint)
  ├── Check user has required permission
  └── Check feature flag is enabled for user scope
  ↓
Handler
```

Permissions are stored in the Beta database (not A2 PostgreSQL). Each user has a set
of named permissions. Admin users have all permissions. The permission model mirrors
the Production WooPrice model and extends it with Beta-specific permissions.

---

## API Layer

The API layer is organized as FastAPI routers, one per domain:

| Router | Prefix | Auth required | Feature flag |
|---|---|---|---|
| Health | `/api/health` | No | None |
| Auth | `/api/auth` | Partial | None |
| Users | `/api/v2/users` | Yes | None |
| Products | `/api/v2/products` | Yes | None |
| Sources | `/api/v2/sources` | Yes | None |
| Rules | `/api/v2/rules` | Yes | `FEATURE_RULE_ENGINE` |
| Safety | `/api/v2/safety` | Yes | `FEATURE_SAFETY_ENGINE` |
| ChangeSets | `/api/v2/changesets` | Yes | `FEATURE_CHANGE_SETS` |
| DryRun | `/api/v2/dryrun` | Yes | `FEATURE_DRY_RUN` |
| Execution | `/api/v2/execution` | Yes | `FEATURE_EXECUTION` |
| Scheduler | `/api/v2/scheduler` | Yes | `FEATURE_SCHEDULER` |
| AI | `/api/v2/ai` | Yes | `FEATURE_AI` |
| Plugins | `/api/v2/plugins` | Yes (admin) | `FEATURE_PLUGIN_SYSTEM` |
| FeatureFlags | `/api/v2/flags` | Yes (admin) | None |
| Config | `/api/v2/config` | Yes (admin) | None |
| Backup | `/api/v2/backup` | Yes (admin) | None |

All write endpoints return a structured response with `status`, `data`, and optional
`warnings` fields. Read endpoints return paginated responses with `items`, `total`,
`page`, and `page_size`.

---

## Scheduler Integration

The Scheduling Engine (A2.8) is run through the Beta backend as a periodic task.
In Phase B6+, a dedicated worker service polls `list_due_schedules()` and dispatches
runs. Until then, scheduling is exposed read-only through the Scheduler Viewer (B11).

The scheduler worker must never share a database session with the API process. It
uses its own connection pool to the A2 PostgreSQL database.

---

## AI Advisory Layer

The AI Foundation (A2.9) is advisory-only. The Beta API exposes AdvisoryInsight
records through `/api/v2/ai/insights`. No AI endpoint triggers execution.

The AI layer is behind `FEATURE_AI`. When disabled, all `/api/v2/ai/` endpoints
return 404 and the AI Viewer section is hidden from the UI.

---

## Storage

| Storage type | Location | Contents |
|---|---|---|
| A2 PostgreSQL | Docker volume (`BETA_POSTGRES_DB`) | All A2 platform data |
| App config DB | `BETA_STORAGE_PATH/config.db` (SQLite) | Feature flags, users, plugin registry |
| Redis | Docker volume | Session cache, rate limiting, scheduler coordination |
| File storage | `BETA_STORAGE_PATH/` | Uploads, logs, temp files |
| Backup store | `BETA_BACKUP_PATH/` | Timestamped backup archives |
| Static assets | Served by Nginx container | Built React SPA |

---

## Logging

All logs are structured JSON (one object per line). Log levels: DEBUG / INFO / WARN / ERROR.

| Log stream | Location | Rotation |
|---|---|---|
| Application log | `BETA_STORAGE_PATH/logs/app.log` | Daily, 30-day retention |
| Audit log | `BETA_STORAGE_PATH/logs/audit.log` | Daily, 90-day retention |
| Access log | Nginx container stdout → `BETA_STORAGE_PATH/logs/access.log` | Daily, 14-day retention |
| Scheduler log | `BETA_STORAGE_PATH/logs/scheduler.log` | Daily, 30-day retention |
| Installer log | `BETA_STORAGE_PATH/install.log` | Not rotated; append-only |

Secrets must never appear in any log stream. The logger sanitizes known secret field names
before writing.

---

## Backup

The backup service (`app/beta/backup/`) produces timestamped archives containing:

1. PostgreSQL dump (`pg_dump`) of the A2 database
2. SQLite dump of the app config database
3. All files under `BETA_STORAGE_PATH/` (excluding logs, which are backed up separately)
4. Manifest file (`backup_manifest.json`) with version, timestamp, and checksums

Archives are written to `BETA_BACKUP_PATH/YYYY-MM-DD_HHMMSS/`.
`wooprice backup` and `wooprice restore` are the CLI interfaces.

---

## Update System

The update service (`app/beta/update/`) manages version updates:

1. `wooprice update --check` — compare installed version with latest release
2. `wooprice update` — pull new version, run migrations, restart services
3. Before applying any update, `wooprice update` automatically runs `wooprice backup`
4. After update, `wooprice status` is run and output displayed

Updates must be rollback-safe: if a migration fails, the update is aborted and the
previous version is restored from the pre-update backup.

---

## Trusted Execution Path Boundary

The Trusted Execution Path (TEP) is the set of A2 components that validate and execute
price changes. It is immutable — Beta code must never modify, intercept, or shortcut it.

```
Source → Rule Engine → Safety Engine → Change Set Engine
      → Dry Run Engine → Seller Confirmation → Execution Engine → Scheduling Engine
```

**Beta code may:**
- Call TEP components through their documented service interfaces
- Read TEP outputs (Change Sets, Dry Run results, Execution records)
- Display TEP state in the UI
- Trigger TEP operations on behalf of an authenticated, authorized user

**Beta code must never:**
- Import internal TEP implementation details (repository internals, private methods)
- Bypass validation steps (e.g., skip Dry Run before execution)
- Allow AI output to become TEP input without explicit human action
- Allow plugin code to modify TEP service behavior
