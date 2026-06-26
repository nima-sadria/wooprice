# WooPrice Beta — Repository Layout

**Document:** REPOSITORY_LAYOUT.md
**Series:** B1 Architecture Blueprint

---

## Repository Strategy

WooPrice Beta lives in its own GitHub repository (created in B2). It is not a fork of
Production WooPrice — it is a new repository that imports A2 Platform Core as a
versioned dependency (or submodule, to be decided in B2).

---

## Proposed Repository Tree

```
wooprice-beta/
│
├── app/                          # Backend — FastAPI application
│   ├── main.py                   # App factory; router registration; startup lifecycle
│   ├── config.py                 # Config loader; env validation; typed config object
│   ├── auth.py                   # JWT auth; permission model; session handling
│   ├── dependencies.py           # FastAPI dependency injectors (db, config, user)
│   │
│   ├── a2/                       # A2 Platform Core (FROZEN — see note below)
│   │   ├── __init__.py
│   │   ├── database.py           # A2Base; engine; session factory
│   │   ├── models/               # ORM models A2.1–A2.9
│   │   ├── repositories/         # Persistence layer
│   │   ├── services/             # Business logic (Rule Engine, Safety, etc.)
│   │   ├── sources/              # Source adapter framework (A2.2)
│   │   ├── rules/                # Transformation Rule Engine (A2.3)
│   │   ├── engines/              # Safety Policy Engine (A2.4)
│   │   └── ai/                   # AI Foundation (A2.9 — advisory only)
│   │
│   └── beta/                     # Beta-only extensions
│       ├── __init__.py
│       ├── config/               # Configuration Manager
│       │   ├── __init__.py
│       │   ├── manager.py        # Config reader/writer/validator
│       │   ├── schema.py         # Pydantic config schema
│       │   └── defaults.py       # Default values per environment
│       ├── feature_flags/        # Feature Flag Evaluator
│       │   ├── __init__.py
│       │   ├── evaluator.py      # Flag evaluation logic
│       │   ├── models.py         # FeatureFlag ORM model
│       │   └── defaults.py       # Default flag states
│       ├── plugins/              # Plugin Registry and Loader
│       │   ├── __init__.py
│       │   ├── registry.py       # Plugin registry; discovery; lifecycle
│       │   ├── manifest.py       # Manifest validation; schema
│       │   └── loader.py         # Dynamic plugin loading
│       ├── users/                # User management
│       │   ├── __init__.py
│       │   ├── models.py         # BetaUser, Permission ORM models
│       │   ├── repository.py     # UserRepository
│       │   └── service.py        # UserService
│       ├── audit/                # Audit logging
│       │   ├── __init__.py
│       │   └── logger.py         # Structured audit event writer
│       ├── backup/               # Backup and restore
│       │   ├── __init__.py
│       │   ├── service.py        # BackupService; restore flow
│       │   └── manifest.py       # Backup manifest schema
│       ├── update/               # Version management
│       │   ├── __init__.py
│       │   └── service.py        # UpdateService; pre-update backup
│       └── api/                  # Beta REST endpoints
│           ├── __init__.py
│           ├── v2/               # Stable Beta endpoints
│           │   ├── products.py
│           │   ├── sources.py
│           │   ├── rules.py
│           │   ├── safety.py
│           │   ├── changesets.py
│           │   ├── dryrun.py
│           │   ├── execution.py
│           │   ├── scheduler.py
│           │   ├── ai.py
│           │   ├── plugins.py
│           │   ├── flags.py
│           │   ├── config.py
│           │   ├── backup.py
│           │   └── users.py
│           └── health.py         # Health probe; version; env label
│
├── cli/                          # wooprice CLI
│   ├── __init__.py
│   ├── main.py                   # Typer app; command registration; env check
│   ├── install.py                # wooprice install
│   ├── configure.py              # wooprice configure
│   ├── status.py                 # wooprice status
│   ├── health.py                 # wooprice health
│   ├── migrate.py                # wooprice migrate
│   ├── backup.py                 # wooprice backup / restore
│   ├── logs.py                   # wooprice logs
│   ├── update.py                 # wooprice update
│   ├── adapters.py               # wooprice adapters
│   ├── channels.py               # wooprice channels
│   ├── sources.py                # wooprice sources
│   ├── users.py                  # wooprice users
│   ├── scheduler.py              # wooprice scheduler
│   ├── ai.py                     # wooprice ai
│   ├── diagnostics.py            # wooprice diagnostics
│   └── shared/
│       ├── api_client.py         # HTTP client to running app
│       ├── config_reader.py      # Direct managed config file access (pre-server)
│       ├── env_guard.py          # Environment safety checks
│       └── output.py             # Rich console output; env label banner
│
├── installer/                    # Installer scripts and templates
│   ├── install.sh                # Main installer entry point (Bash)
│   ├── lib/
│   │   ├── checks.sh             # Prerequisite checks
│   │   ├── wizard.sh             # Interactive setup wizard
│   │   ├── secrets.sh            # Secret generation (openssl rand)
│   │   ├── env_gen.sh            # .env file generation from answers
│   │   ├── compose_gen.sh        # docker-compose.beta.yml from template
│   │   ├── db_init.sh            # DB initialization; Alembic migration run
│   │   ├── admin.sh              # Admin account creation
│   │   ├── ssl.sh                # SSL mode setup
│   │   └── storage.sh            # Storage/backup directory creation
│   └── templates/
│       ├── env.template          # .env template (placeholders only)
│       └── docker-compose.template.yml   # Compose template (placeholders only)
│
├── plugins/                      # Plugin development and bundled plugins
│   ├── README.md                 # Plugin development guide
│   ├── schema/
│   │   └── plugin_manifest.schema.json   # JSON Schema for plugin manifests
│   └── examples/
│       └── dummy_channel/        # Minimal example channel adapter plugin
│           ├── plugin.json       # Plugin manifest
│           └── adapter.py        # DummyChannelAdapter implementation
│
├── frontend/                     # React SPA
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── tailwind.config.ts
│   ├── index.html
│   └── src/
│       ├── App.tsx
│       ├── main.tsx
│       ├── auth/
│       │   ├── AuthProvider.tsx
│       │   ├── AuthGuard.tsx
│       │   ├── RequirePermission.tsx
│       │   └── tokenManager.ts
│       ├── config/
│       │   └── runtimeConfig.ts  # API base URL; env label
│       ├── api/
│       │   ├── client.ts         # Axios instance; auth interceptor; error handling
│       │   └── v2/               # Typed API modules per domain
│       ├── features/
│       │   ├── dashboard/
│       │   ├── products/
│       │   ├── sources/
│       │   ├── rules/
│       │   ├── safety/
│       │   ├── changesets/
│       │   ├── dryrun/
│       │   ├── execution/
│       │   ├── scheduler/
│       │   ├── ai/
│       │   ├── plugins/
│       │   └── admin/
│       ├── components/
│       │   ├── Layout/
│       │   │   ├── TopBar.tsx    # Persistent [BETA] environment label
│       │   │   └── Sidebar.tsx   # Permission-aware navigation
│       │   ├── DataTable/
│       │   ├── StatusBadge/
│       │   ├── ConfirmDialog/
│       │   └── FeatureGate.tsx   # Wraps sections behind feature flags
│       └── hooks/
│           ├── useFeatureFlag.ts
│           ├── usePermission.ts
│           └── usePagination.ts
│
├── alembic_a2/                   # A2 Platform Core migrations (FROZEN)
│   ├── alembic.ini  →  (referenced by alembic_a2.ini at root)
│   ├── env.py
│   └── versions/
│       └── ...                   # a2_000 through a2_008 (A2.1–A2.9)
│
├── alembic_beta/                 # Beta-only migrations (NEW)
│   ├── env.py
│   └── versions/
│       └── ...                   # beta_001, beta_002, ...
│
├── tests/
│   ├── a2/                       # A2 Platform Core tests (FROZEN — do not modify)
│   │   └── ...                   # Existing test files (860+ tests)
│   └── beta/                     # Beta-specific tests (NEW)
│       ├── config/
│       ├── feature_flags/
│       ├── plugins/
│       ├── users/
│       ├── api/
│       │   └── v2/
│       ├── cli/
│       ├── backup/
│       └── integration/          # End-to-end tests (B15)
│
├── docs/
│   ├── BETA_STRATEGY.md
│   ├── BETA_MASTER_SPEC.md
│   ├── ROADMAP.md
│   ├── PLATFORM_MAP.md
│   ├── WORKFLOW.md
│   ├── A2_ARCHITECTURE.md
│   ├── phases/                   # A2 phase documentation (closed)
│   └── beta/                     # Beta architecture blueprints (this directory)
│       ├── SYSTEM_ARCHITECTURE.md
│       ├── REPOSITORY_LAYOUT.md
│       ├── CONFIGURATION_ARCHITECTURE.md
│       ├── CLI_ARCHITECTURE.md
│       ├── INSTALLER_ARCHITECTURE.md
│       ├── PLUGIN_ARCHITECTURE.md
│       ├── FEATURE_FLAG_ARCHITECTURE.md
│       ├── UI_ARCHITECTURE.md
│       ├── SECURITY_ARCHITECTURE.md
│       ├── DEPLOYMENT_ARCHITECTURE.md
│       ├── DEVELOPMENT_GUIDE.md
│       └── IMPLEMENTATION_ROADMAP.md
│
├── scripts/
│   ├── dev_start.sh              # Start local dev stack (Docker Compose)
│   ├── dev_reset.sh              # Reset local dev DB and config
│   ├── lint.sh                   # Run all linters (Python + TypeScript)
│   ├── test.sh                   # Run full test suite
│   ├── build_frontend.sh         # Build React SPA (npm run build)
│   └── generate_openapi.sh       # Export OpenAPI schema for frontend type gen
│
├── docker-compose.beta.yml       # TEMPLATE ONLY — generated by installer
├── .env.example                  # Example env file (placeholders only — never real values)
├── .gitignore                    # Includes .env, *.secret, BETA_STORAGE_PATH/
├── pyproject.toml                # Python project; deps; tool config
├── requirements.txt              # Pinned Python deps
└── README.md                     # Project overview; quick-start pointer
```

---

## Directory Explanations

### `app/`

Backend Python application. The `app/a2/` subdirectory contains the A2 Platform Core —
it is treated as frozen library code and must never be modified for Beta-only concerns.
New Beta functionality lives exclusively in `app/beta/`.

### `app/a2/`

A2 Platform Core — the complete implementation of A2.1 through A2.9. This directory is
identical to the Production WooPrice `app/a2/` directory. It is imported as a package.
Beta-phase work must never add imports into this directory from `app/beta/` (one-way
dependency enforcement mirrors the A2.9 isolation rule).

### `app/beta/`

All Beta-specific backend code. Organized by concern: config, feature_flags, plugins,
users, audit, backup, update, api. Each subdirectory is a Python package with its own
models, repositories, and services.

### `cli/`

The `wooprice` CLI package. Each command group is its own module. The CLI may operate
in two modes: (1) pre-server mode (reads managed config files directly, used by
`install` and `configure`); (2) connected mode (calls the running API, used by all
operational commands). The `env_guard.py` module ensures the CLI never operates
against a Production environment.

### `installer/`

Bash installer scripts and templates. All templates contain only placeholders — no real
values are embedded. The installer library (`lib/`) is modular; each concern is isolated
to its own script file for testability and maintainability.

### `plugins/`

Plugin development workspace and bundled example plugins. The `schema/` directory
contains the JSON Schema for plugin manifests (used by the Plugin Loader for validation).
The `examples/` directory contains a minimal reference implementation.

### `frontend/`

React + TypeScript SPA. Each A2 domain has its own feature directory under `features/`.
Feature flags are enforced at the route level via `FeatureGate.tsx`. The environment
label is rendered by `TopBar.tsx` and is never suppressible.

### `alembic_a2/`

A2 Platform Core migrations. Frozen — no new versions are added here for Beta concerns.

### `alembic_beta/`

Beta-specific migrations for the Beta application database (users, feature flags, plugin
registry, audit log, backup manifest). Follows the same Alembic pattern as `alembic_a2/`.
Versioning starts at `beta_001`.

### `tests/`

The `tests/a2/` directory is frozen (A2 Platform Core tests — do not modify). New Beta
tests live in `tests/beta/`. Integration tests (B15) live in `tests/beta/integration/`.

### `docs/`

All documentation. `docs/beta/` contains this architecture blueprint series.

### `scripts/`

Developer convenience scripts. Never run in production. All scripts are guarded against
running if `BETA_ENV=production`.

---

## A2 Platform Core — Dependency Note

The `app/a2/` directory is included directly (not as an installable package) in the Beta
repository for Phase B2–B4. The exact long-term packaging strategy (submodule vs. pip
package vs. direct copy) is an Owner decision deferred to B2. Either strategy must
preserve the frozen constraint: A2 files are read-only to Beta development.

---

## Naming Conventions

| Scope | Convention |
|---|---|
| Beta migrations | `beta_NNN_description.py` |
| Beta ORM tables | Prefixed `beta_` (e.g., `beta_users`, `beta_feature_flags`) |
| A2 ORM tables | Prefixed `a2_` (unchanged — frozen) |
| Plugin manifests | `plugin.json` in plugin root directory |
| Feature flags | `FEATURE_` prefix, uppercase |
| Environment variables | `BETA_` prefix, uppercase |
| CLI commands | `wooprice <group> [subcommand]` |
| API endpoints | `/api/v2/<resource>/` |
