# WooPrice Beta — Implementation Roadmap

**Document:** IMPLEMENTATION_ROADMAP.md
**Series:** B1 Architecture Blueprint
**Last revised:** 2026-06-26 — Owner Architecture Decision: Configuration Foundation first

---

## Overview

This document maps the B1–B18 phase plan to architecture documents, implementation
concerns, dependencies, and risk notes. It is a planning reference — not a schedule.

**Revision note (2026-06-26):** Configuration is a foundational concern shared by the
Installer, CLI, Docker runtime, Backend, Frontend, Plugins, Scheduler, and all future
services. The Owner decision inserts B3 Configuration Foundation before the Installer
and CLI phases, and adds B6 Docker Runtime Foundation and B7 Authentication Foundation
to establish all runtime prerequisites before the first UI work begins in B8.

---

## Phase Summary Table

| Phase | Name | Architecture docs | Key deliverables | Depends on |
|---|---|---|---|---|
| B1 | Master Specification + Architecture Blueprint | All 12 docs in `docs/beta/` | Architecture blueprint | — |
| B2 | Repository Skeleton | REPOSITORY_LAYOUT.md, DEVELOPMENT_GUIDE.md | Directory + package structure, placeholder modules | B1 |
| B3 | Configuration Foundation | CONFIGURATION_ARCHITECTURE.md | ConfigurationManager, schema, validation, secret abstraction, profiles | B2 |
| B4 | Installer Foundation | INSTALLER_ARCHITECTURE.md, CONFIGURATION_ARCHITECTURE.md | `install.sh`, `wooprice configure`, `.env` generation | B3 |
| B5 | CLI Foundation | CLI_ARCHITECTURE.md, DEVELOPMENT_GUIDE.md | `wooprice` command, 16 command groups, `health` working | B4 |
| B6 | Docker Runtime Foundation | DEPLOYMENT_ARCHITECTURE.md | Docker Compose stack, Dockerfiles, health checks, dev environment | B5 |
| B7 | Authentication Foundation | SECURITY_ARCHITECTURE.md | JWT auth, user models, permissions, session management | B6 |
| B8 | Read-only A2 Inspector UI | SYSTEM_ARCHITECTURE.md, UI_ARCHITECTURE.md | `/api/v2/` read endpoints, Dashboard, Products, Sources, Rules, Safety | B7 |
| B9 | Change Set Viewer + Dry Run UI | UI_ARCHITECTURE.md | Change Set list/detail, Dry Run viewer, A2.5 + A2.6 API | B8 |
| B10 | Execution Viewer + Approval Flow | UI_ARCHITECTURE.md | Execution history, Seller Confirmation UI, A2.7 API | B9 |
| B11 | Scheduler Viewer + CLI Scheduler | CLI_ARCHITECTURE.md | Scheduler list/detail, pause/resume, A2.8 API, worker container | B10 |
| B12 | AI Insights Viewer | UI_ARCHITECTURE.md, SYSTEM_ARCHITECTURE.md | A2.9 API, advisory insight viewer, AI CLI commands | B11 |
| B13 | Feature Flag Manager + Admin UI | FEATURE_FLAG_ARCHITECTURE.md, UI_ARCHITECTURE.md | Flag toggle UI, audit log viewer, admin panel | B7 |
| B14 | Plugin System | PLUGIN_ARCHITECTURE.md | Plugin Registry, loader, lifecycle, CLI, Plugin Manager UI | B13 |
| B15 | Backup + Update System | DEPLOYMENT_ARCHITECTURE.md | `wooprice backup`, `wooprice restore`, `wooprice update` | B14 |
| B16 | Security Hardening | SECURITY_ARCHITECTURE.md | CSP, audit log completeness, secret rotation, dependency scanning | B15 |
| B17 | Integration Testing + Diagnostics | DEVELOPMENT_GUIDE.md | End-to-end test suite, `wooprice diagnostics`, CI gate | B16 |
| B18 | Production Cutover Planning | All docs | Cutover checklist, rollback plan, Owner review | B17 |

---

## Dependency Graph

```
B1 (Spec)
  └── B2 (Skeleton)
        └── B3 (Configuration Foundation)
              └── B4 (Installer Foundation)
                    └── B5 (CLI Foundation)
                          └── B6 (Docker Runtime Foundation)
                                └── B7 (Authentication Foundation)
                                      ├── B8 (Read-only A2 Inspector UI)
                                      │     └── B9 (Change Set Viewer)
                                      │           └── B10 (Execution Viewer)
                                      │                 └── B11 (Scheduler Viewer)
                                      │                       └── B12 (AI Insights Viewer)
                                      │                             └── B17 (Integration)
                                      │                                   └── B18 (Cutover)
                                      └── B13 (Feature Flag Manager + Admin UI)
                                            └── B14 (Plugin System)
                                                  └── B15 (Backup + Update System)
                                                        └── B16 (Security Hardening)
                                                              └── B17 (Integration)
```

B17 (Integration Testing) is the merge point for both the UI stream (B8–B12) and
the admin/ops stream (B13–B16). Both streams must be complete before B17.

---

## Phase Detail

### B1 — Master Specification + Architecture Blueprint

**Status:** CLOSED

**Goal:** Produce the complete specification and architecture blueprint before any
code is written.

**Deliverables:** ✓
- `docs/BETA_MASTER_SPEC.md`
- `docs/beta/` (12 architecture documents)

---

### B2 — Repository Skeleton

**Status:** CLOSED — commit `0687732`

**Goal:** Create the complete Beta repository structure with placeholder modules.
All B3+ phases work within this structure.

**Deliverables:** ✓
- `app/beta/` package (config, feature_flags, plugins, users, audit, backup, update, api/v2)
- `cli/` package (16 command modules + shared utilities)
- `installer/` placeholder scripts and templates
- `plugins/` workspace (JSON Schema, DummyChannelAdapter example)
- `alembic_beta/` migration environment
- `tests/beta/` test package stubs
- `scripts/` Beta dev scripts
- Root files: `alembic_beta.ini`, `docker-compose.beta.yml`, `pyproject.toml`

---

### B3 — Configuration Foundation

**Goal:** Implement the complete configuration subsystem before any other runtime
component. Configuration is consumed by the Installer, CLI, Docker runtime, Backend,
Frontend, Plugins, Scheduler, and all future services. It must be correct, validated,
and stable before those consumers are built.

**Key implementation concerns:**
- No application code may read `os.environ` directly — all access flows through ConfigurationManager
- Secrets never appear in managed config files, logs, or API responses
- Startup validation must be strict — missing or invalid required variables cause `exit(1)` with clear message
- Profile separation (dev / beta / production) enforced at initialization time; never mix
- Secret Provider Abstraction decouples the source of secrets from their consumers
  (allows future migration to Vault, AWS Secrets Manager, etc. without code changes)

**Deliverables:**

1. **Configuration Manager** (`app/beta/config/manager.py`)
   - `ConfigurationManager` class with `validate()`, `get()`, `set()`, `verify()`
   - Reads environment variables and the managed TOML config file
   - Provides a typed `BetaConfig` object to all services via dependency injection

2. **Environment Loader** (`app/beta/config/loader.py`)
   - Loads `.env` file via `python-dotenv` at application startup
   - Merges with process environment (process env takes priority)
   - Raises `ConfigurationError` on malformed `.env`

3. **Placeholder Expansion** (`app/beta/config/expander.py`)
   - Resolves `${VAR}` placeholders in the managed TOML config file
   - Used when reading the config file — values in TOML may reference env vars
   - Never writes expanded values back to disk (expansion is read-time only)

4. **Configuration Validation** (`app/beta/config/validation.py`)
   - Per-variable validators for all 21 required `BETA_*` variables
   - Validates types, formats, ranges, and enum membership
   - Produces a structured `ValidationResult` with field-level errors

5. **Secret Provider Abstraction** (`app/beta/config/secrets.py`)
   - `SecretProvider` abstract base class
   - `EnvSecretProvider` — reads secrets from environment variables (default)
   - Interface designed for future `VaultSecretProvider` without changing callers

6. **Runtime Configuration API** (`app/beta/api/v2/config.py` — implemented)
   - `GET /api/v2/config/` — returns current configuration (secrets redacted)
   - `POST /api/v2/config/verify` — runs drift check; returns discrepancy list
   - Admin permission required; no secret values in any response

7. **Environment Profiles** (`app/beta/config/profiles.py`)
   - `ConfigProfile` enum: `DEV`, `BETA`, `PRODUCTION`
   - Profile-specific defaults and validation rules
   - `PRODUCTION` profile activates all safety guards; `DEV` enables debug output

8. **Configuration Schema** (`app/beta/config/schema.py` — implemented)
   - Pydantic v2 model for `BetaConfig`
   - All 21 required variables + 7 optional variables with typed fields
   - Validators for URL format, timezone strings, ISO 4217 codes, secret length

9. **Configuration Migration Strategy** (`app/beta/config/migration.py`)
   - Detects when a managed config file is from an older Beta version
   - Applies field additions/renames without losing existing values
   - Used by `wooprice update apply` to migrate config between Beta versions

10. **Configuration Documentation** (`app/beta/config/README.md`)
    - Inline documentation of all config variables with examples
    - Explains the secret-separation model (env vars vs. TOML)
    - Explains profile behavior and the emergency manual edit procedure

**Tests:** `tests/beta/config/` — full test suite covering all validators,
profile switching, placeholder expansion, and startup failure modes.

**TEP impact:** None — B3 is infrastructure only.

---

### B4 — Installer Foundation

**Goal:** A working `install.sh` that produces a running stack on a clean server.
Requires B3 (Configuration Foundation) because the installer writes configuration
and must use the Configuration Manager's validation rules.

**Key implementation concerns:**
- Secret generation must use `openssl rand` (not Python `secrets` or random)
- `.env` file mode must be 600 on creation
- Managed config TOML must never contain secrets
- Rollback on failure must be clean — no partial state left

**Deliverables:**
- `installer/install.sh` with all `lib/` modules implemented
- Integration between installer and `ConfigurationManager.validate()`
- Working `wooprice configure show/set/verify/rotate` (B3 Config Manager backing it)
- `tests/beta/config/test_installer_integration.py`

**TEP impact:** None.

---

### B5 — CLI Foundation

**Goal:** The `wooprice` CLI is installable and all 16 command groups are operational
(even if most subcommands return "not yet implemented"). Health and status commands
are fully working. Requires B4 (Installer) because `wooprice configure` and
`wooprice migrate` rely on the Config Manager and the installed stack.

**Key implementation concerns:**
- `[BETA ENVIRONMENT]` banner is non-suppressible from day one
- `env_guard.py` production resource check active before any write operation
- `wooprice health all` fully working (requires B4 stack running)

**Deliverables:**
- `cli/main.py` with all 16 groups registered
- `wooprice status` working
- `wooprice health all` working
- `wooprice configure` commands working (from B3)
- `tests/beta/cli/` — unit tests for all CLI modules

---

### B6 — Docker Runtime Foundation

**Goal:** A complete, verified Docker Compose stack for development and Beta
deployment. The `app` and `worker` containers, Nginx, PostgreSQL, and Redis are
all running and healthy. Requires B5 (CLI) because `wooprice health all` is the
post-launch verification command.

**Key implementation concerns:**
- No secrets in Docker images — all secrets injected via env_file
- Non-root users in all containers
- Startup order enforced with health check dependencies
- `docker-compose.dev.yml` (host-mounted app) separate from `docker-compose.beta.yml`
- Resource limits configurable via managed config

**Deliverables:**
- `Dockerfile.app` (multi-stage; Python 3.12-slim final image)
- `Dockerfile.frontend` (multi-stage; Nginx final image)
- `docker-compose.beta.yml` (generated by installer from template; implemented)
- `docker-compose.dev.yml` (for local development; host-mounted app + hot reload)
- All 5 containers healthy: `nginx`, `app`, `worker`, `postgres`, `redis`
- `wooprice health all` passes against the running stack

**TEP impact:** None — B6 is infrastructure only.

---

### B7 — Authentication Foundation

**Goal:** JWT authentication is production-grade before any UI work begins.
All `/api/v2/` endpoints are protected from B8 onward. Requires B6 (Docker) so
that the authentication service runs inside the containerized stack.

**Revision note:** Authentication was originally planned as B10. The Owner decision
moves it to B7 so that no UI phase (B8+) ever ships with stub authentication.
The B2 stub-auth decision is superseded — real auth is in place before B8.

**Key implementation concerns:**
- httpOnly + Secure + SameSite=Strict cookie for refresh token
- Access token stored in React state only (never `localStorage`)
- Silent refresh on 401 before redirecting to login
- Session invalidation on secret rotation must be immediate
- Bootstrap admin endpoint (`/api/v2/users/bootstrap-admin`) callable only once (idempotent after first use)

**Deliverables:**
- `app/beta/users/` — `BetaUser`, `Permission` ORM models + Beta migration `beta_001`
- `app/beta/users/repository.py` — `UserRepository` implemented
- `app/beta/users/service.py` — `UserService` (create, authenticate, reset-pw)
- `app/beta/audit/logger.py` — `AuditLogger` implemented (login events first)
- `/api/auth/login`, `/api/auth/refresh`, `/api/auth/logout`
- `/api/v2/users/bootstrap-admin` (installer hook — one-time admin creation)
- `/api/v2/users/` CRUD
- React: Login page, `AuthProvider`, `AuthGuard`, `tokenManager`
- `wooprice users list/create/set-role/deactivate/reset-pw`
- `tests/beta/users/` — full auth + permission test suite

---

### B8 — Read-only A2 Inspector UI

**Goal:** The UI shows products, sources, rules, and safety policies in read-only
views. The A2 Platform Core is fully exposed through the read API. Real authentication
(B7) is in place from day one.

**Key implementation concerns:**
- All `/api/v2/` read endpoints protected by real JWT auth (not stub)
- Feature flag gates wired for all flagged endpoints
- Frontend pages: Dashboard, Products, Sources, Rules, Safety

**Deliverables:**
- `/api/v2/products/`, `/api/v2/sources/`, `/api/v2/rules/`, `/api/v2/safety/` (read endpoints)
- React pages: Dashboard, Products, Sources, Rules, Safety
- `tests/beta/api/v2/` — read endpoint tests
- OpenAPI schema generated; TypeScript types auto-generated

---

### B9 — Change Set Viewer + Dry Run UI

**Goal:** Change Sets and Dry Run results are visible in the UI. Approve/Reject
flow is wired up. Safety override is auditable.

**Deliverables:**
- `/api/v2/changesets/`, `/api/v2/dryrun/`
- React pages: Change Sets, Dry Run Viewer
- Approve/Reject actions with confirmation dialogs
- Safety override form with mandatory reason field

---

### B10 — Execution Viewer + Approval Flow

**Goal:** Execution history is visible. Seller Confirmation step is exposed.
No execution without prior Dry Run (enforced server-side).

**Deliverables:**
- `/api/v2/execution/`
- React page: Execution Viewer
- Seller Confirmation UI
- Server-side guard: no execution without `dry_run_status IN (passed, warnings)`

---

### B11 — Scheduler Viewer + CLI Scheduler

**Goal:** Schedules are visible and manageable. The scheduler worker container
is running. Pause/Resume/Cancel work from UI and CLI.

**Deliverables:**
- `worker` container in Docker Compose with scheduler polling (A2.8 `list_due_schedules()`)
- `/api/v2/scheduler/`
- React page: Scheduler Viewer
- `wooprice scheduler list/pause/resume/cancel`

---

### B12 — AI Insights Viewer

**Goal:** A2.9 advisory insights surfaced in the UI and CLI. AI gated behind
`FEATURE_AI`. `TD-A2.9-001` remains open (still rule-based).

**Deliverables:**
- `/api/v2/ai/insights/`
- React page: AI Insights Viewer
- `wooprice ai insights`, `wooprice ai toggle`
- AI insight panel integrated with Product detail page

---

### B13 — Feature Flag Manager + Admin UI

**Goal:** Feature flags can be toggled at runtime. The Admin panel is complete.
Depends on B7 (auth) — admin panel requires the permission model.

**Deliverables:**
- `app/beta/feature_flags/` — evaluator, dependency chain enforcement, Beta migration seeding
- `/api/v2/flags/` (snapshot, toggle)
- React pages: Admin → Feature Flags, Admin → Audit Log
- All existing feature gates verified to use the live evaluator

---

### B14 — Plugin System

**Goal:** Plugins can be installed, enabled, disabled, and removed.
The Dummy Channel Adapter example plugin works end-to-end.

**Key implementation concerns:**
- Plugin isolation enforced: no direct DB access from plugin code
- Version compatibility check on install
- Admin permission required for all plugin operations

**Deliverables:**
- `app/beta/plugins/` (registry, loader, manifest validator) — implemented
- `/api/v2/plugins/` CRUD
- `wooprice adapters install/enable/disable/remove`
- React page: Plugin Manager
- `plugins/examples/dummy_channel/` — functional reference implementation
- `tests/beta/plugins/` — full test suite

---

### B15 — Backup + Update System

**Goal:** Backup and restore work reliably. The update system auto-backs-up
before applying any update. Rollback on update failure is automatic.

**Deliverables:**
- `app/beta/backup/` and `app/beta/update/` — implemented
- `wooprice backup create/list/restore`
- `wooprice update check/apply`

---

### B16 — Security Hardening

**Goal:** All security architecture requirements from SECURITY_ARCHITECTURE.md
are implemented and verified.

**Key implementation concerns:**
- CSP header blocks XSS
- All audit log events complete (no gaps vs. SECURITY_ARCHITECTURE.md table)
- Dependency scanning in CI (`pip-audit`, `npm audit`)
- JWT secret rotation tested end-to-end

**Deliverables:**
- CSP and security headers on Nginx verified
- Audit log completeness verified against SECURITY_ARCHITECTURE.md event table
- `pip-audit` and `npm audit` in CI pipeline
- `wooprice configure rotate --all-secrets` tested

---

### B17 — Integration Testing + Diagnostics

**Goal:** End-to-end test suite validates the complete TEP flow. Both the UI
stream (B8–B12) and the admin/ops stream (B13–B16) must be complete before B17.

**Deliverables:**
- `tests/beta/integration/` — source → TEP → execution end-to-end suite
- `wooprice diagnostics run` — all 10 checks implemented
- CI pipeline with full test gate
- All 911 A2 tests still passing

---

### B18 — Production Cutover Planning

**Goal:** Prepare the cutover plan for when WooPrice Beta is ready to replace
Production WooPrice. No actual cutover in B18 — only planning and Owner review.

**Note:** Owner decision point. Beta may run alongside Production indefinitely.

**Deliverables:**
- Cutover checklist document
- Rollback plan document
- Data migration plan (Production WooPrice → Beta)
- Owner review session

---

## Risk Register

| ID | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R-B1 | A2 submodule UX causes integration friction | Low | Medium | **MITIGATED** — submodule decided; CI must pin submodule ref on every PR |
| R-B2 | Stub auth diverges from real auth | N/A | N/A | **SUPERSEDED** — Auth moves to B7; no stub auth shipped in any UI phase |
| R-B3 | Configuration schema drift between B3 and later phases | Low | High | ConfigurationManager is the single source of truth; all consumers depend on it |
| R-B4 | B3 Configuration Foundation delays the rest of the sequence | Medium | Medium | B3 is well-specified; skeleton already in place from B2; risk is scope creep |
| R-B5 | Docker Runtime Foundation (B6) reveals server resource constraints | Medium | Medium | Document minimum server spec; test on reference hardware in B6 |
| R-B6 | Authentication Foundation (B7) scope is underestimated | Low | High | Auth is fully specified in SECURITY_ARCHITECTURE.md; scope is fixed |
| R-B7 | Plugin isolation is hard to enforce at runtime | Low | High | Interface-based isolation; AST scanning in B14 |
| R-B8 | TEP flag disabling causes production-like bugs in Beta | Low | High | Dependency chain enforced in evaluator; UI shows cascading consequences |
| R-B9 | Secret rotation invalidates all sessions unexpectedly | Low | Medium | Document rotation procedure; warn operator; add rotation test in B16 |
| R-B10 | B17 (Integration) blocked by either B12 or B16 being incomplete | Low | High | Track both streams independently; do not begin B17 until both are done |

---

## B2 Planning Decisions — Owner Approved 2026-06-26

### Decision 1 — A2 Packaging Strategy

**APPROVED: Git Submodule**

A2 Platform Core consumed as a Git submodule. Future migration to standalone pip package
is possible but not part of any current B phase.

---

### Decision 2 — CI Platform

**APPROVED: GitHub Actions**

GitHub repository. GitHub Actions CI pipeline.

---

### Decision 3 — Auth Sequencing

**SUPERSEDED by B7 Architecture Decision (2026-06-26)**

Original decision: stub auth for B5, real auth in B10.

Revised decision: Authentication Foundation is now **B7**, implemented before the first
UI phase (B8). No UI phase ships with stub authentication. The stub-auth approach is no
longer applicable.

---

### Decision 4 — A2.4 Status Dependency

**RESOLVED: No longer a blocker**

A2 Platform Core is COMPLETE. A2.4 Safety Policy Engine is available for Beta consumption.
B8 Safety UI (formerly B5) and B9 Change Set Viewer (formerly B6) are unblocked.

---

## Architecture Document Index

| # | Document | Phase(s) |
|---|---|---|
| 1 | [SYSTEM_ARCHITECTURE.md](SYSTEM_ARCHITECTURE.md) | B1, B8 |
| 2 | [REPOSITORY_LAYOUT.md](REPOSITORY_LAYOUT.md) | B1, B2 |
| 3 | [CONFIGURATION_ARCHITECTURE.md](CONFIGURATION_ARCHITECTURE.md) | B1, B3, B4 |
| 4 | [CLI_ARCHITECTURE.md](CLI_ARCHITECTURE.md) | B1, B5 |
| 5 | [INSTALLER_ARCHITECTURE.md](INSTALLER_ARCHITECTURE.md) | B1, B4 |
| 6 | [PLUGIN_ARCHITECTURE.md](PLUGIN_ARCHITECTURE.md) | B1, B14 |
| 7 | [FEATURE_FLAG_ARCHITECTURE.md](FEATURE_FLAG_ARCHITECTURE.md) | B1, B13 |
| 8 | [UI_ARCHITECTURE.md](UI_ARCHITECTURE.md) | B1, B8, B9, B10 |
| 9 | [SECURITY_ARCHITECTURE.md](SECURITY_ARCHITECTURE.md) | B1, B7, B16 |
| 10 | [DEPLOYMENT_ARCHITECTURE.md](DEPLOYMENT_ARCHITECTURE.md) | B1, B4, B6, B15 |
| 11 | [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) | B1, B2 |
| 12 | [IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md) (this document) | B1 |
