# WooPrice Beta — Implementation Roadmap

**Document:** IMPLEMENTATION_ROADMAP.md
**Series:** B1 Architecture Blueprint
**Last revised:** 2026-06-27 — B5 implemented; READY FOR OWNER REVIEW

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

**Status:** CLOSED — Owner approved 2026-06-27

**Permanent Record:**
- Implementation commit: `9a487c7` — "B3: implement framework-independent configuration foundation"
- Status update commit: `74f5ee1` — "B3: mark READY FOR OWNER REVIEW; update test count to 146"
- CHAT2 Final Review: APPROVE (2026-06-27) — all 8 criteria satisfied
- Owner approval date: 2026-06-27
- Test summary: 146 passed, 0 failed, 0 skipped (0.30s)
- Technical debt: LOW only — `set()` file write and migration file write deferred to B4 (expected and documented)

**Architecture constraint (CHAT2 decision):** B3 Configuration Core is
framework-independent. Zero FastAPI, Typer, Docker, or HTTP imports.
Usable from backend, CLI, installer, tests, and future services without modification.
The Runtime Configuration REST API has been moved to B5 (CLI Foundation).

**Goal:** Implement the complete configuration subsystem before any other runtime
component. Configuration is consumed by the Installer, CLI, Docker runtime, Backend,
Frontend, Plugins, Scheduler, and all future services. It must be correct, validated,
and stable before those consumers are built.

**Key implementation concerns:**
- No application code may read `os.environ` directly — all access flows through ConfigurationManager
- Secrets stored as `pydantic.SecretStr` — redacted in repr(), accessible via `.get_secret_value()`
- Startup validation returns structured `ValidationResult` — never raises, never terminates
- Profile separation (dev / beta / production) enforced at initialization time; never mix
- Secret Provider Abstraction decouples the source of secrets from their consumers
  (allows future migration to Vault, AWS Secrets Manager, etc. without code changes)
- TOML config file write path deferred to B4 (Installer Foundation)

**Deliverables:**

1. **Configuration Manager** (`app/beta/config/manager.py`) ✓
   - Public API: `load()`, `validate()`, `get()`, `set()`, `verify()`, `profile()`, `migrate()`
   - Reads environment variables and optional managed TOML config file
   - Provides typed `BetaConfig` to all consumers — no raw env dicts passed around

2. **Environment Loader** (`app/beta/config/loader.py`) ✓
   - `EnvironmentLoader` with `.load()` and `.load_beta_only()`
   - Merges `.env` file with process environment (process env takes priority)
   - Raises `ConfigurationError` on missing `.env` file; fallback manual parser if dotenv unavailable

3. **Placeholder Expansion** (`app/beta/config/expander.py`) ✓
   - `expand_placeholders(text, env)` — resolves `${VAR}` in TOML config text at read time
   - `find_unexpanded(text, env)` — lists unexpanded variable names for diagnostics
   - Never writes expanded values back to disk

4. **Configuration Validation** (`app/beta/config/validation.py`) ✓
   - `ConfigValidator` with per-variable validators for all 22 required `BETA_*` variables
   - Validates types, formats, ranges, URL schemes, IANA timezones, ISO 4217 currency codes
   - Returns structured `ValidationResult` with `FieldError` list — never raises, never exits

5. **Secret Provider Abstraction** (`app/beta/config/secrets.py`) ✓
   - `SecretProvider` abstract base class with `get()` and `names()`
   - `EnvSecretProvider` — reads secrets from environment variables (default)
   - `SECRET_FIELDS` frozenset — canonical list of 6 secret variable names

6. **~~Runtime Configuration API~~** — **moved to B5 (CLI Foundation)**
   - `app/beta/api/v2/config.py` placeholder updated to reference B5

7. **Environment Profiles** (`app/beta/config/profiles.py`) ✓
   - `ConfigProfile(str, Enum)`: `DEV`, `BETA`, `PRODUCTION`
   - `from_string()`, `is_production()`, `is_dev()`, `banner()`
   - PRODUCTION profile adds CLI warning; never used for new test data

8. **Configuration Schema** (`app/beta/config/schema.py`) ✓
   - Pydantic v2 `BetaConfig` (frozen model) with 22 required + 8 optional typed fields
   - Secrets as `SecretStr`; URL, timezone, currency, secret-length validators
   - `from_env(dict)` factory; `plugin_dir` computed from `storage_path` if not set
   - Validators for URL format, timezone strings, ISO 4217 codes, secret length

9. **Configuration Migration Strategy** (`app/beta/config/migration.py`) ✓
   - `ConfigMigration` with `detect_version()`, `needs_migration()`, `migrate()`
   - Returns updated config dict + list of change descriptions; never modifies in-place
   - First version (beta-1.0.0) has no predecessor; new steps added as schema evolves
   - TOML file write on migration deferred to B4 (Installer Foundation)

10. **Configuration Documentation** (`app/beta/config/README.md`) ✓
    - All 22 required + 8 optional variables documented with type, description, example
    - Secret-separation model, profile behavior, emergency edit procedure

**Tests:** `tests/beta/config/` — 9 test modules, 146 tests passing
- `conftest.py` — shared fixtures (`valid_env`, `valid_env_with_paths`)
- `test_profiles.py` — ConfigProfile enum, from_string(), banner()
- `test_secrets.py` — SECRET_FIELDS, EnvSecretProvider
- `test_expander.py` — expand_placeholders(), find_unexpanded()
- `test_validation.py` — per-field validators, ConfigValidator, ValidationResult
- `test_schema.py` — BetaConfig.from_env() valid/invalid, SecretStr redaction
- `test_loader.py` — EnvironmentLoader, .env file loading, process env priority
- `test_migration.py` — detect_version(), needs_migration(), migrate()
- `test_manager.py` — integration: load, validate, get, set, verify, profile, migrate

**TEP impact:** None — B3 is infrastructure only.

**Framework dependency scan:** Zero FastAPI, Typer, HTTP, Docker, Auth, Plugin, or UI imports.
All modules: pure Python 3.12 standard library + Pydantic v2 + python-dotenv.

---

### B4 — Installer Foundation

**Status:** CLOSED — Owner approved 2026-06-27

**Permanent Record:**
- Implementation commit: `a864503` — "B4: implement installer foundation"
- Owner approval date: 2026-06-27
- Test summary: 315 passed, 1 skipped (0.63s) — 169 B4 installer tests + 146 B3 regression
- Technical debt: LOW only — TD-B4-01 (Windows chmod not enforced), TD-B4-02 (Docker daemon check deferred to B6), TD-B4-03 (non-interactive completeness not enforced in Bash), TD-B4-04 (dry-run empty-path edge case in subdirectory planning)

**Architecture constraint:** B4 Installer Foundation implements only the foundation
steps: prerequisite checks, interactive wizard, secret generation, .env file
generation, managed TOML config generation, storage setup, dry-run mode, and
rollback. Docker stack launch (B6), database init (B6), admin account (B7),
and SSL setup (B6) are explicitly out of scope. No production deployment.
No Docker execution. No network calls.

**Goal:** Implement a safe, testable installer foundation that uses B3 Configuration
Core for all validation. The Python core (`installer/installer_core.py`) is the
testable layer; Bash scripts (`install.sh`, `lib/`) are the Linux deployment
entry point.

**Key implementation concerns:**
- Python installer core delegates all validation to B3 ConfigValidator — no duplicate logic
- `.env` file written with mode 600; secrets never appear in TOML or logs
- Rollback tracks only files/dirs created by this install attempt
- Dry-run mode writes nothing; shows everything that would happen
- No hardcoded real domains, URLs, or credentials anywhere

**Deliverables:**

1. **Python Installer Core** (`installer/installer_core.py`) ✓
   - `InstallerConfig`, `InstallerSecrets`, `PrerequisiteResult`, `DryRunResult`
   - `generate_secrets()`, `check_prerequisites()`, `generate_env_content()`
   - `generate_toml_content()`, `validate_generated_config()`, `setup_storage()`
   - `dry_run_install()`, `InstallerRollback`, `confirm_installation()`
   - `InstallationCancelled` exception

2. **Bash Entry Point** (`installer/install.sh`) ✓
   - Full 13-step orchestration; steps 8–13 are documented stubs for B6/B7
   - `--dry-run` and `--non-interactive` flags
   - `trap ERR` → `rollback_all()` on failure

3. **Prerequisite Checks** (`installer/lib/checks.sh`) ✓
   - Python version, docker command, docker compose, openssl, write permission
   - Command availability checks only — no Docker execution

4. **Secret Generation** (`installer/lib/secrets.sh`) ✓
   - `openssl rand` for JWT (base64, 64+ chars), REST (hex32), PG password (base64)
   - Masked preview only — never plain text after generation

5. **Interactive Wizard** (`installer/lib/wizard.sh`) ✓
   - 9 sections; per-section prompts with defaults; confirmation summary; cancellation

6. **.env File Generation** (`installer/lib/env_gen.sh`) ✓
   - Writes all 22 BETA_* vars; mode 600; calls B3 ConfigValidator via Python

7. **Storage Setup** (`installer/lib/storage.sh`) ✓
   - Creates `{logs,config,plugins,uploads,diagnostics}` + backup path; tracks for rollback

8. **Docker Compose Generation** (`installer/lib/compose_gen.sh`) ✓
   - Template substitution only (envsubst); no Docker execution

9. **Managed TOML Template** (`installer/templates/wooprice-beta.toml.template`) ✓
   - All `${VAR}` placeholders; no secrets; B3-compatible placeholder syntax

10. **Installer Documentation** (`docs/beta/INSTALLER_ARCHITECTURE.md`) ✓
    - B4 implementation note added

11. **Test Suite** (`tests/beta/installer/`) ✓
    - 8 test modules; covers all 16 required test categories from B4 spec

**Tests:** `tests/beta/installer/` — 8 modules, 169 tests passing (1 skipped: chmod on Windows); B3 regression: 146 tests, 0 failures

**TEP impact:** None.

---

### B5 — CLI Foundation

**Status:** READY FOR OWNER REVIEW

**Architecture constraint:** B5 CLI Foundation implements only local, pre-server commands.
Docker stack commands (health db/sources/channels), database migrations, backup/restore,
update, users, scheduler, and AI are explicitly out of scope for B5.
All stub commands exit safely with "Not implemented in this phase."

**Goal:** The `wooprice` CLI provides a usable management entrypoint consuming B3
Configuration Foundation and B4 Installer Foundation. Prepares for first controlled
test installation on a clean Linux server.

**Key implementation concerns:**
- `[BETA ENVIRONMENT]` banner printed on every invocation; cannot be suppressed
- Production profile blocks install and configure write paths; read-only commands always permitted
- CLI orchestrates B3 and B4 — no duplicate config validation or installer logic
- No Docker execution, no network calls, no production service connections anywhere in CLI
- All secrets redacted in output (config show, install dry-run, diagnostics, status)

**Local invocation command (B5):**
```
python -m cli.main <command> [options]
```

**Dry-run install smoke path:**
```
python -m cli.main install dry-run --env-file /path/to/.env --install-dir /opt/wooprice-beta
```

**Deliverables:**

1. **CLI Output Utilities** (`cli/shared/output.py`) ✓
   - Rich console, banner, error, success, warning, section, table helpers
   - Production profile warning block

2. **Environment Safety Guard** (`cli/shared/env_guard.py`) ✓
   - `ProductionResourceError` exception
   - `require_beta_env(profile)` — blocks write ops in PRODUCTION profile

3. **Config Reader Helper** (`cli/shared/config_reader.py`) ✓
   - `load_config(env_file)` — wraps B3 ConfigurationManager
   - `validate_env_file(env_file)` — B3 ConfigValidator direct call
   - `redact_env_dict(env_dict)` — secrets → [REDACTED]
   - `secret_status(env_dict)` — {field: 'set'|'not set'} (never values)

4. **Main Entry Point** (`cli/main.py`) ✓
   - 15 command groups registered
   - `python -m cli.main` invocation working

5. **install dry-run** (`cli/install.py`) ✓
   - Wraps B4 `dry_run_install()`
   - Writes nothing; shows planned files, dirs, masked secrets, validation result
   - PRODUCTION profile blocked

6. **configure show** / **configure verify** (`cli/configure.py`) ✓
   - `show`: displays config with all secrets as [REDACTED]
   - `verify`: runs B3 ConfigValidator, shows field-level errors

7. **status** (`cli/status.py`) ✓
   - Local: profile, config loaded/valid, paths, domain, port
   - No production service calls

8. **health** (`cli/health.py`) ✓
   - Python version, required module imports, config load/validate, storage path
   - No external network calls; no Docker execution

9. **diagnostics** (`cli/diagnostics.py`) ✓
   - Config validation summary, missing fields, secret status (set/not set only)
   - B4 prerequisite summary
   - No secrets in output

10. **Stub commands** (10 groups) ✓
    - migrate, backup, logs, update, adapters, channels, sources, users, scheduler, ai
    - Each prints "Not implemented in this phase." and exits 0

11. **Test Suite** (`tests/beta/cli/`) ✓
    - 9 test modules; covers all required test categories from B5 spec

12. **Documentation** (`docs/beta/CLI_ARCHITECTURE.md`) ✓
    - B5 implementation note added; local invocation documented

**Tests:** `tests/beta/cli/` — 9 modules, tests pending count

**Known limitations (technical debt):**
- Interactive install wizard requires B6 (Docker runtime)
- `health db/sources/channels` require B6 running stack
- `wooprice` command packaging requires B6 Dockerfile; `python -m cli.main` is the B5 path

**TEP impact:** None.

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
