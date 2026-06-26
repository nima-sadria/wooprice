# WooPrice Beta — Implementation Roadmap

**Document:** IMPLEMENTATION_ROADMAP.md
**Series:** B1 Architecture Blueprint

---

## Overview

This document maps the B1–B16 phase plan from [BETA_MASTER_SPEC.md](../BETA_MASTER_SPEC.md)
to architecture documents, implementation concerns, dependencies, and risk notes.
It is a planning reference — not a schedule.

---

## Phase Summary Table

| Phase | Name | Architecture docs | Key deliverables | Depends on |
|---|---|---|---|---|
| B1 | Master Specification + Architecture Blueprint | All 12 docs in `docs/beta/` | This document series | — |
| B2 | Repository Setup + CI | REPOSITORY_LAYOUT.md, DEPLOYMENT_ARCHITECTURE.md | New repo, CI pipeline, A2 import | B1 |
| B3 | Installer + Configuration Manager | INSTALLER_ARCHITECTURE.md, CONFIGURATION_ARCHITECTURE.md | `install.sh`, `wooprice configure`, `.env` generation | B2 |
| B4 | CLI Framework + Health Commands | CLI_ARCHITECTURE.md, DEVELOPMENT_GUIDE.md | `wooprice` command, 16 command groups scaffolded, `health` working | B3 |
| B5 | Product Inspector + A2 Read Layer | SYSTEM_ARCHITECTURE.md | `/api/v2/products`, sources viewer, rules viewer, TEP read-only API | B4 |
| B6 | Change Set Viewer + Dry Run UI | UI_ARCHITECTURE.md | Change Set list/detail, Dry Run viewer, A2.5 + A2.6 API exposure | B5 |
| B7 | Execution Viewer + Approval Flow | UI_ARCHITECTURE.md | Execution history, Seller Confirmation UI, A2.7 API exposure | B6 |
| B8 | Scheduler Viewer + CLI Scheduler | CLI_ARCHITECTURE.md | Scheduler list/detail, pause/resume, A2.8 API exposure | B7 |
| B9 | AI Insights Viewer | UI_ARCHITECTURE.md, SYSTEM_ARCHITECTURE.md | A2.9 API exposure, advisory insight viewer, AI CLI commands | B8 |
| B10 | Auth + User Management | SECURITY_ARCHITECTURE.md | JWT auth, user CRUD, permissions, session management | B5 |
| B11 | Feature Flag Manager + Admin UI | FEATURE_FLAG_ARCHITECTURE.md, UI_ARCHITECTURE.md | Flag toggle UI, audit log viewer, admin panel | B10 |
| B12 | Plugin System | PLUGIN_ARCHITECTURE.md | Plugin Registry, loader, lifecycle, plugin installer CLI | B11 |
| B13 | Backup + Update System | DEPLOYMENT_ARCHITECTURE.md | `wooprice backup`, `wooprice restore`, `wooprice update` | B12 |
| B14 | Security Hardening | SECURITY_ARCHITECTURE.md | CSP, audit log completeness, secret rotation, dependency scanning | B13 |
| B15 | Integration Testing + Diagnostics | DEVELOPMENT_GUIDE.md | End-to-end test suite, `wooprice diagnostics`, CI gate | B14 |
| B16 | Production Cutover Planning | All docs | Cutover checklist, rollback plan, Owner review | B15 |

---

## Phase Detail

### B1 — Master Specification + Architecture Blueprint

**Goal:** Produce the complete specification and architecture blueprint before any code
is written. All B2–B16 phases derive from B1 documents.

**Deliverables (this session):**
- `docs/BETA_MASTER_SPEC.md` ✓
- `docs/beta/` (12 architecture documents) ✓

**Exit criteria:**
- All 12 architecture documents complete
- No real domains, credentials, or secrets in any document
- Owner approval

---

### B2 — Repository Setup + CI

**Goal:** Create the `wooprice-beta` repository with the frozen A2 Platform Core
included, and a working CI pipeline.

**Key decisions to make in B2:**
- A2 import strategy: direct copy vs. git submodule vs. pip package
- CI platform: GitHub Actions vs. GitLab CI (Owner decision)
- Branch protection rules

**Deliverables:**
- New `wooprice-beta` repository
- `app/a2/` included (A2.1–A2.9, all frozen)
- All existing A2 tests pass in new repo
- CI pipeline: lint, type check, test (all A2 + empty Beta suite)
- `docker-compose.dev.yml` for local dev

**Risk:** A2 packaging strategy affects all future phases. Submodule complexity vs.
copy simplicity — Owner decides.

---

### B3 — Installer + Configuration Manager

**Goal:** A working `install.sh` that produces a running stack on a clean server.

**Key implementation concerns:**
- Secret generation must use `openssl rand` (not Python `secrets` or random)
- `.env` file mode must be 600 on creation
- Managed config TOML must never contain secrets
- Startup validation must be strict — no partial-configured boots
- Rollback on failure must be clean

**Deliverables:**
- `installer/install.sh` with all `lib/` modules
- `app/beta/config/` (ConfigurationManager, schema, defaults)
- `tests/beta/config/` (unit tests for ConfigurationManager)
- Working `wooprice configure show/set/verify/rotate`

**TEP impact:** None — B3 is infrastructure only.

---

### B4 — CLI Framework + Health Commands

**Goal:** The `wooprice` CLI is installable and all 16 command groups are scaffolded
(even if most subcommands return "not yet implemented"). Health and status commands
are fully working.

**Key implementation concerns:**
- Environment banner is non-suppressible from day one
- `env_guard.py` production resource check implemented before any write commands
- `wooprice health all` must work (requires B3 stack to be running)

**Deliverables:**
- `cli/main.py` with all 16 groups registered
- `wooprice status` working
- `wooprice health all` working
- `wooprice configure` commands working (from B3)
- `tests/beta/cli/` (unit tests for CLI modules)

---

### B5 — Product Inspector + A2 Read Layer

**Goal:** The UI shows products, sources, rules, safety policies in read-only views.
The A2 Platform Core is fully exposed through the read API.

**Key implementation concerns:**
- All `/api/v2/` read endpoints (products, sources, rules, safety) implemented
- Feature flag gates wired up for all flagged endpoints
- Frontend: Dashboard, Products, Sources, Rules, Safety pages working
- JWT auth working end-to-end (requires B10 to be complete, or B5 may use a stub auth)

**Note:** B5 and B10 may run in parallel or B10 may precede B5. Auth dependency
must be resolved in phase planning before B5 starts.

**Deliverables:**
- `/api/v2/products/`, `/api/v2/sources/`, `/api/v2/rules/`, `/api/v2/safety/`
- React pages: Dashboard, Products, Sources, Rules, Safety
- `tests/beta/api/v2/test_products.py` etc.
- OpenAPI schema generated and TypeScript types regenerated

---

### B6 — Change Set Viewer + Dry Run UI

**Goal:** Change Sets and Dry Run results are visible in the UI. The approval
flow (approve/reject) is wired up.

**Key implementation concerns:**
- Change Set approval must require explicit user confirmation dialog
- Safety override form must include a reason field (auditable)
- Dry Run results must show the full per-product diff

**Deliverables:**
- `/api/v2/changesets/`, `/api/v2/dryrun/`
- React pages: Change Sets, Dry Run Viewer
- Approve/Reject actions with confirmation dialogs

---

### B7 — Execution Viewer + Approval Flow

**Goal:** Execution history is visible. The Seller Confirmation step is exposed in
the UI. Execution can be triggered (via confirmed action) by an authorized user.

**Key implementation concerns:**
- No execution without prior Dry Run (enforced server-side)
- Seller Confirmation step is not skippable (TEP constraint)
- Execution log detail must be queryable per-product

**Deliverables:**
- `/api/v2/execution/`
- React page: Execution Viewer
- Seller Confirmation UI

---

### B8 — Scheduler Viewer + CLI Scheduler

**Goal:** Schedules are visible and manageable. The scheduler worker is running
as a separate container. Pause/Resume/Cancel work from UI and CLI.

**Deliverables:**
- `worker` container in Docker Compose with scheduler polling
- `/api/v2/scheduler/`
- React page: Scheduler Viewer
- `wooprice scheduler list/pause/resume/cancel`

---

### B9 — AI Insights Viewer

**Goal:** A2.9 advisory insights are surfaced in the UI and CLI. AI is gated behind
`FEATURE_AI`. `TD-A2.9-001` remains open (still rule-based).

**Deliverables:**
- `/api/v2/ai/insights/`
- React page: AI Insights Viewer
- `wooprice ai insights` CLI command
- `wooprice ai toggle` CLI command
- Integration with Product detail page (insight panel)

---

### B10 — Auth + User Management

**Goal:** JWT authentication is production-grade. User management is complete.
All existing endpoints are protected.

**Key implementation concerns:**
- httpOnly cookie for refresh token (requires HTTPS in non-dev environments)
- Silent refresh flow working in React
- Password reset flow (email not required in Beta — admin resets via CLI are acceptable)
- Session invalidation on secret rotation

**Deliverables:**
- `app/beta/users/` (models, repository, service)
- `/api/auth/login`, `/api/auth/refresh`, `/api/auth/logout`
- `/api/v2/users/` CRUD
- `wooprice users list/create/set-role/deactivate/reset-pw`
- React: Login page, Admin → User Management

---

### B11 — Feature Flag Manager + Admin UI

**Goal:** Feature flags can be toggled at runtime. The Admin panel is complete.
Audit log is viewable in the UI.

**Deliverables:**
- `app/beta/feature_flags/` complete with evaluator and dependency chain enforcement
- `/api/v2/flags/` (snapshot, toggle)
- React pages: Admin → Feature Flags, Admin → Audit Log
- All existing feature gates verified to use the evaluator

---

### B12 — Plugin System

**Goal:** Plugins can be installed, enabled, disabled, and removed. The example
Dummy Channel Adapter plugin works.

**Key implementation concerns:**
- Plugin isolation must be enforced (no direct DB access, no inter-plugin imports)
- Version compatibility check on install
- Admin permission required for all plugin operations

**Deliverables:**
- `app/beta/plugins/` (registry, loader, manifest validator)
- `/api/v2/plugins/` CRUD
- `wooprice adapters install/enable/disable/remove`
- React page: Plugin Manager
- `plugins/examples/dummy_channel/` reference implementation
- `tests/beta/plugins/` test suite

---

### B13 — Backup + Update System

**Goal:** Backup and restore work reliably. The update system auto-backs-up before
applying updates.

**Key implementation concerns:**
- Pre-update backup is mandatory — not skippable
- Rollback on update failure is automatic
- Backup archives include `pg_dump`, SQLite dump, and storage files
- Restore requires explicit confirmation (backup ID typed by operator)

**Deliverables:**
- `app/beta/backup/` and `app/beta/update/`
- `wooprice backup create/list/restore`
- `wooprice update check/apply`

---

### B14 — Security Hardening

**Goal:** All security architecture requirements are implemented and verified.

**Key implementation concerns:**
- CSP header verified to block XSS
- All audit log events complete (no gaps vs. SECURITY_ARCHITECTURE.md table)
- Dependency scanning in CI (`pip-audit`, `npm audit`)
- JWT secret rotation tested end-to-end (all sessions invalidated)
- Environment guard production resource check tested

**Deliverables:**
- CSP and security headers on Nginx
- Audit log completeness verified
- `pip-audit` and `npm audit` in CI
- `wooprice configure rotate --all-secrets` tested

---

### B15 — Integration Testing + Diagnostics

**Goal:** End-to-end test suite validates the complete TEP flow. Diagnostics command
is complete. CI gate blocks any PR that breaks A2 tests or integration tests.

**Deliverables:**
- `tests/beta/integration/` — end-to-end test suite (source → TEP → execution)
- `wooprice diagnostics run` complete (all 10 diagnostic checks)
- CI pipeline with full test gate
- All 911 A2 tests still passing

---

### B16 — Production Cutover Planning

**Goal:** Prepare the cutover plan for when WooPrice Beta is ready to replace
Production WooPrice. No actual cutover in B16 — only planning and Owner review.

**Note:** This is an Owner decision point. Beta may run alongside Production
indefinitely before any cutover. B16 just ensures the path is documented.

**Deliverables:**
- Cutover checklist document
- Rollback plan document
- Data migration plan (Production WooPrice data → Beta)
- Owner review session

---

## Risk Register

| ID | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R-B1 | A2 packaging strategy causes integration pain | Medium | High | Decide early in B2; prefer direct copy for simplicity |
| R-B2 | Auth dependency blocks B5 UI work | Medium | Medium | Stub auth for B5 dev; replace with real auth in B10 |
| R-B3 | Plugin isolation is hard to enforce at runtime | Low | High | Start with interface-based isolation; add AST scanning in B12 |
| R-B4 | TEP flag disabling causes production-like bugs in Beta | Low | High | Dependency chain enforced in evaluator; UI shows consequences |
| R-B5 | Secret rotation invalidates all sessions unexpectedly | Low | Medium | Document rotation procedure; warn operator before rotation |
| R-B6 | Docker resource limits insufficient for target server | Medium | Medium | Document minimum server requirements; make limits configurable |

---

## Open B2 Decisions (Owner must resolve before B2 starts)

The following decisions are required before B2 implementation begins. Each has
architecture implications. Owner decides.

### Decision 1 — A2 Packaging Strategy

How is `app/a2/` (A2 Platform Core) included in the `wooprice-beta` repository?

| Option | Pros | Cons |
|---|---|---|
| **Direct copy** | Simple; no submodule complexity; easy for devs to read | Drift risk if A2 is ever patched; no automatic sync |
| **Git submodule** | Changes to A2 are trackable; clear separation | Submodule UX is painful; CI setup is more complex |
| **Pip package** | Cleanest import story; enforces interface boundary | Requires A2 to be packaged and versioned; more setup work |

**Recommendation:** Direct copy for B2–B4 (simplest); revisit as pip package after B5 if A2 patch scenario arises.

**Owner decision required:** Select one option before B2 work begins.

---

### Decision 2 — CI Platform

Which CI system hosts the WooPrice Beta pipeline?

| Option | Notes |
|---|---|
| **GitHub Actions** | Standard choice if repo is on GitHub; YAML workflows; free tier available |
| **GitLab CI** | If repo is on GitLab; `.gitlab-ci.yml` |

**Owner decision required:** Confirm repository host (GitHub or GitLab) before B2 CI setup.

---

### Decision 3 — Auth Sequencing (B5 vs B10)

B5 (Product Inspector UI) requires authenticated API calls. B10 (Auth + User Management)
is the phase that implements production-grade JWT auth.

| Option | Implication |
|---|---|
| **B10 before B5** | B5 works with real auth from day one; delays UI work |
| **Stub auth for B5, real auth in B10** | B5 can proceed immediately; stub must be replaced before B10 |
| **B10 parallel with B5** | Requires two concurrent workstreams |

**Constraint:** Stub auth in B5 must use the same JWT structure as B10 to avoid refactoring API calls.

**Owner decision required:** Select sequencing approach before B5 starts.

---

### Decision 4 — A2.4 Status Dependency

`A2.4 — Safety Policy Engine` currently shows status `READY FOR OWNER APPROVAL` in some
documentation. The B5 Safety Policy viewer (and B6 Change Set Viewer) depend on A2.4
being functional.

**Rule:** B5 Safety UI and B6 Change Set Viewer must not be built or shipped until A2.4 is
formally CLOSED or explicitly approved by Owner as ready for Beta consumption.

**Action required:** Owner must formally close A2.4 (or approve its use in Beta) before
B5 Safety and B6 work begins. If A2.4 remains open, B5 can proceed for Products, Sources,
and Rules only — the Safety section is held.

---

## Architecture Document Index

| # | Document | Phase(s) |
|---|---|---|
| 1 | [SYSTEM_ARCHITECTURE.md](SYSTEM_ARCHITECTURE.md) | B1, B5 |
| 2 | [REPOSITORY_LAYOUT.md](REPOSITORY_LAYOUT.md) | B1, B2 |
| 3 | [CONFIGURATION_ARCHITECTURE.md](CONFIGURATION_ARCHITECTURE.md) | B1, B3 |
| 4 | [CLI_ARCHITECTURE.md](CLI_ARCHITECTURE.md) | B1, B4 |
| 5 | [INSTALLER_ARCHITECTURE.md](INSTALLER_ARCHITECTURE.md) | B1, B3 |
| 6 | [PLUGIN_ARCHITECTURE.md](PLUGIN_ARCHITECTURE.md) | B1, B12 |
| 7 | [FEATURE_FLAG_ARCHITECTURE.md](FEATURE_FLAG_ARCHITECTURE.md) | B1, B11 |
| 8 | [UI_ARCHITECTURE.md](UI_ARCHITECTURE.md) | B1, B5, B6, B7 |
| 9 | [SECURITY_ARCHITECTURE.md](SECURITY_ARCHITECTURE.md) | B1, B10, B14 |
| 10 | [DEPLOYMENT_ARCHITECTURE.md](DEPLOYMENT_ARCHITECTURE.md) | B1, B3, B13 |
| 11 | [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) | B1, B2 |
| 12 | [IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md) (this document) | B1 |
