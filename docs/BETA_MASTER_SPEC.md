# WooPrice Beta — Master Architecture Specification

**Document:** B1 Master Specification
**Status:** APPROVED
**Date:** 2026-06-26
**Authority:** Owner

---

## 1. Executive Summary

WooPrice Beta is the future product surface built on top of the completed A2 Platform
Core (A2.1 through A2.9, all CLOSED). It is the sole destination for all new product
work from this point forward.

**Production WooPrice is maintenance-only** — bug fixes and safety fixes only. No new
UI, no new features, no new platform capabilities are built on Production WooPrice.

WooPrice Beta is the only place for:

- New UI (Workspace replacement, Product Explorer, A2 viewers, AI Advisory UI)
- CLI (`wooprice` command — install, configure, manage)
- Installer (guided interactive setup for a clean Linux server)
- Plugin system (installable adapters without modifying Platform Core)
- Feature flags (per-capability enable/disable)
- Integration testing (end-to-end, across the full A2 Trusted Execution Path)
- Customer preview (demonstrations, UX validation)
- Future Workspace replacement (after parity verification and Owner approval)

Beta is isolated from Production at every layer: repository, database, secrets,
environment, domain, cache, logs, and backups. Source code is the only shared artifact.

The A2 Platform Core is consumed by Beta as its data and processing foundation. Beta
adds the product surface — installer, CLI, UI, plugin system — on top of the existing
A2 engine.

---

## 2. Isolation Policy

WooPrice Beta must maintain complete isolation from Production WooPrice at every layer.

| Resource | Beta has its own | Shared with Production |
|---|---|---|
| GitHub repository | Yes | No |
| Docker Compose stack | Yes | No |
| PostgreSQL database | Yes | No |
| Environment file (`.env`) | Yes | No |
| Secrets (JWT, API keys) | Yes | No |
| Nextcloud spreadsheet | Yes — test spreadsheet only | No |
| WooCommerce store | Yes — test store only | No |
| Logs | Yes | No |
| Cache | Yes | No |
| Domain / port | Yes | No |
| Backup path | Yes | No |
| SSL certificates | Yes | No |
| Source code | — | Read-only reference |

**Absolute rules:**

- No Beta process may read from, write to, or connect to any Production resource.
- No Beta secret may match any Production secret.
- No Beta database URL may resolve to a Production database.
- No Beta environment file may be committed to source control.
- Any test that touches real data must use Beta-only test fixtures.
- Beta UI and CLI must display a clear environment label at all times
  (e.g., `[BETA]` or `[DEV]`) — never blank, never `[PRODUCTION]`.

---

## 3. Placeholder Configuration

All Beta configuration values are represented as placeholders. No real values are
committed to source control. All values are supplied at install time (interactively)
or through the CLI.

| Placeholder | Description |
|---|---|
| `BETA_DOMAIN` | Hostname where Beta is served (e.g., `beta.example.com`) |
| `BETA_PORT` | Port for the Beta application server |
| `BETA_DATABASE_URL` | Full database connection URL for Beta |
| `BETA_POSTGRES_DB` | PostgreSQL database name for Beta |
| `BETA_POSTGRES_USER` | PostgreSQL username for Beta |
| `BETA_POSTGRES_PASSWORD` | PostgreSQL password for Beta |
| `BETA_JWT_SECRET` | JWT signing secret (generated per install; min 64 chars) |
| `BETA_REST_API_SECRET` | REST API secret key (generated per install) |
| `BETA_NEXTCLOUD_URL` | Nextcloud URL for Beta test spreadsheet source |
| `BETA_NEXTCLOUD_FILE_PATH` | Path to Beta test spreadsheet within Nextcloud |
| `BETA_NEXTCLOUD_USERNAME` | Nextcloud username for Beta source access |
| `BETA_NEXTCLOUD_PASSWORD` | Nextcloud password for Beta source access |
| `BETA_WOOCOMMERCE_URL` | WooCommerce test store URL |
| `BETA_WOOCOMMERCE_KEY` | WooCommerce consumer key for Beta test store |
| `BETA_WOOCOMMERCE_SECRET` | WooCommerce consumer secret for Beta test store |
| `BETA_TIMEZONE` | Timezone for scheduler and log timestamps |
| `BETA_CURRENCY` | Default currency for pricing operations |
| `BETA_ADMIN_EMAIL` | Initial admin account email address |
| `BETA_STORAGE_PATH` | Base path for application storage (logs, uploads, cache) |
| `BETA_BACKUP_PATH` | Destination path for automated backups |
| `BETA_SSL_MODE` | SSL/TLS mode: `off` / `self-signed` / `letsencrypt` / `manual` |

**Rules:**

- No installer, CLI, Docker Compose file, or documentation may contain a real value
  for any of the above placeholders.
- Secrets (`BETA_JWT_SECRET`, `BETA_REST_API_SECRET`, `BETA_POSTGRES_PASSWORD`) must be
  generated fresh per installation — never re-used across installations.
- Passwords and secrets must not appear in process arguments or log output.

---

## 4. Repository Strategy

### Target state

| Repository | Purpose | State |
|---|---|---|
| WooPrice Production | Maintenance only: bug fixes, safety fixes | Existing — maintenance-only |
| WooPrice Beta | Active development: new UI, installer, CLI, plugins | To be created — Owner decision |

### Production repository policy (permanent)

- No new feature branches targeting Production.
- No new UI code in Production.
- No new A2 phase development in Production repository.
- Patches to Production must be minimal, targeted, and independently reviewed.
- Patches must not introduce new dependencies without Owner approval.

### Beta repository policy

- All new product work is committed to the Beta repository.
- Beta repository tracks the A2 Platform Core by version — not by live file copy.
- Beta never merges into Production repository.
- Beta may backport critical safety fixes to Production via cherry-pick (Owner decision only).

### Repository creation

Exact GitHub repository creation (name, visibility, branch policy, CI configuration,
secrets configuration) is a later Owner-controlled task. No repository is created
during B1. This specification defines what the repository must contain and enforce,
not the mechanics of creating it.

---

## 5. Installation Strategy

WooPrice Beta must be installable on a clean Linux server with a single guided process.

### Requirements

- No manual file editing required during normal setup.
- Installer is script-driven (shell script or compiled binary — to be determined in B3).
- Installer detects missing prerequisites and reports them clearly.
- Installer generates all required configuration artifacts.

### Interactive setup — required questions

| Topic | Collected values |
|---|---|
| Network | `BETA_DOMAIN`, `BETA_PORT` |
| Database | `BETA_POSTGRES_DB`, `BETA_POSTGRES_USER`, `BETA_POSTGRES_PASSWORD`, `BETA_DATABASE_URL` |
| Secrets | `BETA_JWT_SECRET` (offer to generate), `BETA_REST_API_SECRET` (offer to generate) |
| Source type | Source adapter selection (Nextcloud / CSV / Excel / Direct DB / API) |
| Source credentials | `BETA_NEXTCLOUD_URL`, `BETA_NEXTCLOUD_FILE_PATH`, `BETA_NEXTCLOUD_USERNAME`, `BETA_NEXTCLOUD_PASSWORD` (if Nextcloud selected) |
| WooCommerce | `BETA_WOOCOMMERCE_URL`, `BETA_WOOCOMMERCE_KEY`, `BETA_WOOCOMMERCE_SECRET` |
| Environment | `BETA_SSL_MODE`, `BETA_TIMEZONE`, `BETA_CURRENCY` |
| Admin account | `BETA_ADMIN_EMAIL`, initial password |
| Storage | `BETA_STORAGE_PATH`, `BETA_BACKUP_PATH` |

### Artifacts generated by installer

- `.env` file (written to a path outside source control; not committed)
- `docker-compose.beta.yml` (generated from template with placeholder substitution)
- Database schema initialization (Alembic migrations run automatically)
- Initial admin account creation
- Storage directories (`BETA_STORAGE_PATH`, `BETA_BACKUP_PATH`)
- Installer completion report (written to `BETA_STORAGE_PATH/install.log`)

### Prerequisites checked by installer

- Docker and Docker Compose availability
- Required ports free (`BETA_PORT`, PostgreSQL port)
- Disk space above minimum threshold
- Linux OS version compatibility
- Python availability (if installer is Python-based)

---

## 6. CLI Strategy

The `wooprice` command is the first-class management tool for WooPrice Beta.
No manual configuration file editing is required for normal operation.

### Design rules

- CLI always displays the active environment (`[BETA]` / `[PRODUCTION]` / `[DEV]`).
- CLI must never write to Production WooPrice configuration.
- CLI commands are idempotent where possible.
- CLI uses managed configuration files; it does not parse raw `.env` files directly.
- CLI output is human-readable by default; structured (`--json`) output available for scripting.
- CLI provides `--dry-run` for all destructive operations.

### Command groups

| Command | Responsibility |
|---|---|
| `wooprice install` | Guided interactive installation |
| `wooprice configure` | Reconfigure any setting without reinstalling |
| `wooprice status` | Summary: services up/down, DB connected, migrations, version |
| `wooprice health` | Deep health check: DB, sources, channels, adapters, scheduler |
| `wooprice migrate` | Run pending Alembic migrations; show migration history |
| `wooprice backup` | Create timestamped backup (DB dump + storage) |
| `wooprice restore` | Restore from a backup file (with confirmation prompt) |
| `wooprice logs` | Stream or export logs by service and date range |
| `wooprice update` | Pull new version, run migrations, restart services |
| `wooprice adapters` | List, install, enable, disable, configure adapters |
| `wooprice channels` | Configure destination channels (WooCommerce, Shopify, etc.) |
| `wooprice sources` | Configure data source connections |
| `wooprice users` | List, create, modify, deactivate user accounts |
| `wooprice scheduler` | View, pause, resume, cancel scheduled executions |
| `wooprice ai` | View AI Foundation status; toggle AI features; view insight history |
| `wooprice diagnostics` | Run full diagnostic suite; output report for support |

### CLI non-functional requirements

- Every command must have `--help` output.
- Every destructive command must require explicit confirmation or `--yes` flag.
- `wooprice restore` must display a clear warning that data will be overwritten.
- `wooprice update` must create an automatic backup before applying the update.
- CLI must exit with non-zero code on any failure.

---

## 7. Configuration Management

### Sources of truth (priority order)

1. Environment variables (highest priority — override everything)
2. Managed configuration files (written by installer and CLI; not manually edited)
3. Database-backed settings (for runtime-configurable behavior: feature flags, adapter config)
4. Default values compiled into the application (lowest priority)

### Rules

- Secrets are never stored in database-backed settings.
- Secrets are environment variables only.
- Configuration changes are possible through: installer, CLI, admin UI (future).
- Manual editing of managed config files is emergency-only and must be followed by
  `wooprice configure --verify` to detect drift.
- Every secret is unique per installation — generated at install time.
- Secret rotation is a CLI operation: `wooprice configure --rotate-secret <name>`.

### Configuration drift detection

- `wooprice status` reports if running configuration diverges from last-known-good state.
- `wooprice diagnostics` includes a configuration consistency check.

---

## 8. Docker / Deployment Model

### Beta Docker Compose stack

Beta runs in its own isolated Docker Compose stack. No service, volume, network,
or environment variable is shared with Production.

| Service | Purpose |
|---|---|
| `app` | FastAPI backend (Python) |
| `frontend` | Nginx serving built React SPA |
| `postgres` | PostgreSQL for A2 Platform Core |
| `cache` | Redis or equivalent (if required by B-phase features) |
| `worker` | Background job worker (if required — not in early B phases) |

### Deployment rules

- Stack uses `docker-compose.beta.yml` (distinct from `docker-compose.yml`).
- No shared volumes with Production.
- No shared networks with Production.
- All service names are prefixed to prevent collision (e.g., `wooprice_beta_app`).
- Reverse proxy integration (Nginx/Caddy/Traefik) is addressed in a later B phase.
- SSL termination is configured through the installer and CLI — not hardcoded.
- Persistent volumes use `BETA_STORAGE_PATH` as base — never Production paths.

### Image strategy

- Beta builds its own Docker image from the Beta repository.
- Production image is never used in Beta.
- Image tags include Beta version and build date.

---

## 9. UI Strategy

### Guiding principle

The new UI is built **only** in WooPrice Beta. The Production Workspace is not modified
for any Beta-only concern.

### Beta UI sections (planned)

| Section | Purpose |
|---|---|
| Dashboard | System health, sync status, recent activity, quick stats |
| Product Explorer | Browse, filter, and inspect canonical product catalog (A2.1/A2.2) |
| Source Explorer | View source snapshots, provenance records, adapter status |
| Rule Engine | Browse rule definitions, versions; view proposal history |
| Safety Viewer | Browse safety results, blocked items, policy configuration |
| Change Set Viewer | Inspect Change Sets, revisions, item-level detail |
| Dry Run Viewer | Review Dry Run reports before confirmation |
| Execution Viewer | Track execution status, batch results, item outcomes |
| Scheduler Viewer | Manage scheduled executions, runs, lease status |
| AI Advisory Viewer | Browse advisory insights, anomaly alerts, review priorities |
| Admin Settings | Users, permissions, feature flags, plugin management |
| Plugin Manager | Install, configure, enable/disable adapters and extensions |

### UI promotion to Production

Beta UI replaces Production Workspace only after:

1. All integration tests pass in Beta environment
2. Owner grants explicit promotion approval
3. Parity verification — all Production Workspace capabilities confirmed present in Beta UI
4. Rollback plan documented and tested
5. Production backup completed
6. Support window scheduled
7. Final acceptance review

No UI code from Beta is merged into Production without this sequence.

---

## 10. Feature Flags

Every major capability must be independently enableable or disableable through
configuration. Feature flags are stored in database-backed settings and manageable
via CLI and admin UI.

### Required flags

| Flag | Controls |
|---|---|
| `FEATURE_RULE_ENGINE` | Transformation Rule Engine (A2.3) |
| `FEATURE_SAFETY_ENGINE` | Safety Policy Engine (A2.4) |
| `FEATURE_CHANGE_SETS` | Change Set Engine (A2.5) |
| `FEATURE_DRY_RUN` | Dry Run Engine (A2.6) |
| `FEATURE_EXECUTION` | Execution Engine (A2.7) |
| `FEATURE_SCHEDULER` | Scheduling Engine (A2.8) |
| `FEATURE_AI` | AI Foundation (A2.9) |
| `FEATURE_MULTI_CHANNEL` | Multi-channel destination support |
| `FEATURE_COMPETITOR_FEATURES` | Competitor pricing feature set |
| `FEATURE_PLUGIN_SYSTEM` | Plugin discovery and adapter registration |

### Flag states

| State | Meaning |
|---|---|
| `enabled` | Feature available to all authorized users |
| `disabled` | Feature entirely absent from UI and API |
| `admin-only` | Feature visible only to admin users |
| `dev-only` | Feature available only when `BETA_ENV=development` |

### Safety invariants — non-negotiable

Feature flags must never:

- Disable Safety Policy evaluation for active Change Sets
- Bypass Seller Confirmation
- Remove Dry Run digest verification
- Remove Execution Engine prerequisite checks
- Allow AI to authorize execution

Disabling a feature flag suppresses the UI surface and API endpoints for that feature.
It does not remove the underlying validation logic for already-created objects.

---

## 11. Plugin Architecture

Future adapters and extensions must be installable without modifying Platform Core.

### Plugin categories

| Category | Purpose |
|---|---|
| Source adapters | Ingest product data from external systems |
| Channel adapters | Write approved prices to destination channels |
| Rule extensions | Add new rule types to the Transformation Rule Engine |
| Safety policy extensions | Add new safety conditions to the Safety Policy Engine |
| UI modules | Add new UI sections or dashboard widgets |
| Report modules | Add new report types to the advisory or analytics layer |

### Planned plugins

**Channel adapters:**

- WooCommerce Adapter (reference implementation)
- Shopify Adapter
- Magento Adapter
- ERP Adapter
- Marketplace Adapter

**Source adapters:**

- Nextcloud Spreadsheet Adapter (reference implementation — A2.2 existing)
- CSV File Adapter
- Excel File Adapter
- Direct Database Adapter
- REST API Source Adapter

### Plugin rules — mandatory

- Plugins must declare their capabilities in a plugin manifest.
- Plugins must declare the permissions they require (read source, write channel, etc.).
- Plugins must be versioned (semantic versioning).
- Plugins must be independently disableable without restarting Platform Core.
- Plugins must not bypass the Safety Policy Engine on any execution path.
- Plugins must not bypass Seller Confirmation.
- Plugins must not modify Platform Core files (app/a2/ is read-only to plugins).
- Plugins are registered at startup via the adapter registry (A2.2 pattern extension).
- Plugin installation is a CLI operation: `wooprice adapters install <plugin-name>`.

### Plugin isolation

Channel adapter plugins execute within the A2.7 Execution Engine contract:
`ChannelExecutionAdapter.apply_item()` and `ChannelExecutionAdapter.verify_freshness()`.
No channel adapter can bypass the five A2.7 execution prerequisites.

---

## 12. A2 Platform Core Integration

WooPrice Beta consumes the A2 Platform Core without modification.

### Trusted Execution Path — immutable

```
Source Data
    ↓
Transformation Rule Engine (A2.3)
    ↓
Safety Policy Engine (A2.4)
    ↓
Change Set Engine (A2.5)
    ↓
Dry Run Engine (A2.6)
    ↓
Seller Confirmation
    ↓
Execution Engine (A2.7)
    ↓
Scheduling Engine (A2.8)
```

### AI Foundation — advisory only

The AI Foundation (A2.9) sits alongside the Trusted Execution Path. It reads
prior-phase outputs and produces AdvisoryInsight objects. It does not participate
in the execution sequence.

### Beta must not

- Modify any file under `app/a2/` directly for Beta-only concerns.
- Add Beta-specific logic to the Trusted Execution Path.
- Allow UI or CLI to bypass any step in the TEP.
- Use AI output as executable input to any TEP component.
- Add foreign keys from Beta tables to A2 Platform Core tables (phase independence).

### Versioning

Beta tracks the A2 Platform Core at a declared version. When a Platform Core fix
is needed, it is applied via the normal A2 governance workflow, then the fix version
is updated in Beta.

---

## 13. Beta Development Phases

### B-series phase plan

| Phase | Name | Scope |
|---|---|---|
| **B1** | Master Specification + Architecture Blueprint | Architecture documentation (this document + 12 `docs/beta/` docs) |
| **B2** | Repository Skeleton | Directory structure, package stubs, placeholder modules — **CLOSED** |
| **B3** | Configuration Foundation | `ConfigurationManager`; env loader; validation; secret abstraction; profiles — **NEXT** |
| **B4** | Installer Foundation | Interactive install script; env file generation; Docker Compose generation |
| **B5** | CLI Foundation | `wooprice` entry point; 16 command groups; `health` working |
| **B6** | Docker Runtime Foundation | Full service stack (nginx, app, worker, postgres, redis); health checks |
| **B7** | Authentication Foundation | JWT auth; user management; permission model |
| **B8** | Read-only A2 Inspector UI | Dashboard; Product Explorer; Source Explorer (read-only) |
| **B9** | Change Set Viewer + Dry Run UI | Change Set viewer; Dry Run viewer; confirmation flow |
| **B10** | Execution Viewer + Approval Flow | Execution history; Seller Confirmation UI |
| **B11** | Scheduler Viewer + CLI Scheduler | Scheduler viewer; pause/resume; worker container |
| **B12** | AI Insights Viewer | A2.9 advisory insight viewer; anomaly alerts |
| **B13** | Feature Flag Manager + Admin UI | Flag toggle UI; audit log viewer; admin panel |
| **B14** | Plugin System | Plugin Registry; loader; lifecycle; Plugin Manager UI |
| **B15** | Backup + Update System | `wooprice backup`; `wooprice restore`; `wooprice update` |
| **B16** | Security Hardening | CSP; audit log completeness; dependency scanning; secret rotation |
| **B17** | Integration Testing + Diagnostics | End-to-end test suite; `wooprice diagnostics`; CI gate |
| **B18** | Production Cutover Planning | Cutover checklist; rollback plan; Owner review |

### Phase governance

Each B phase follows the same governance workflow as A phases:
CHAT2 specification → Implementation → Independent Review → Phase Completion Report
→ CHAT2 Architecture Review → Owner approval → Commit.

No B phase begins without Owner approval of the previous phase's exit.

---

## 14. Production Cutover Boundary

No production cutover occurs during Beta development.

### Cutover preconditions — all must be met

1. Owner explicit approval for cutover
2. Parity verification — all Production WooPrice capabilities present and tested in Beta
3. End-to-end integration tests pass in Beta environment (B15 complete)
4. Rollback plan documented, reviewed, and tested
5. Automated backup of Production completed and verified
6. Monitoring and alerting configured for Beta environment
7. Support window scheduled (cutover within a maintenance window)
8. Staged migration plan approved (if data migration required)
9. Final acceptance review completed by Owner
10. Production audit completed (all open TDs reviewed; no BLOCKER findings)

### What Production cutover means

- Beta becomes the primary application serving real traffic.
- Production WooPrice is archived (read-only) or decommissioned.
- Beta domain becomes the canonical domain.
- Production database migrations (if any) are applied under Owner supervision.
- Rollback window is defined and staffed before cutover begins.

---

## 15. Control Plane Resilience

**Owner decision — 2026-06-27**

WooPrice Beta separates the system into two distinct operational planes:

**Control Plane** — the administrative and configuration surface that must remain
accessible at all times:
- Login / admin access
- Settings management
- Integration credentials configuration
- Diagnostics and health checks
- Environment status
- Feature flags
- Plugin manager
- Logs viewer
- Backup and update controls

**Integration Plane** — external service connections that may be unavailable:
- Nextcloud source connection
- WooCommerce channel connection
- External adapters
- Scheduler execution targets
- AI provider connections
- External APIs

**Critical rule:** The Control Plane must remain accessible even if one or more
Integration Plane services are down.

**Failure scenarios that must not block the Control Plane:**
- Nextcloud unreachable (DNS failure, TLS failure, timeout, wrong credentials,
  expired app password, connection refused)
- WooCommerce unreachable
- Adapter failure
- Plugin failure

**Required behavior:**
- Admin panel and settings must open and remain usable during integration failure.
- Integration credentials must be editable regardless of integration status.
- Integration health checks must show the exact failure class:
  - `dns_failure` — DNS resolution failed
  - `tls_failure` — TLS / certificate error
  - `timeout` — connection timed out
  - `unauthorized` — HTTP 401 (wrong credentials)
  - `forbidden` — HTTP 403
  - `unreachable` — connection refused / no route to host
  - `invalid_response` — server replied but response was unexpected
- Dependent feature menus may be disabled or hidden when integration health is failing.
- Integration failure must never be reported only as a generic "Invalid credentials" message.

**Auth rule:** Beta must not depend on Nextcloud availability for admin login.
Local admin credential login is always available. External identity providers
(Nextcloud, OAuth, LDAP) are optional integrations; their failure must not block
owner or admin access.

**CLI rule:** The following CLI commands must work without any external integration
being online, unless explicitly testing that integration:
- `configure show`, `configure verify`, `configure set`
- `diagnostics`, `health`
- `integrations test <name>` (tests only the named integration; others unaffected)
- `adapters list`

**Production lesson:** WooPrice 7.5A demonstrated that DNS and TLS failures to
Nextcloud were silently collapsed to "Invalid Nextcloud credentials", making it
impossible to distinguish a network problem from a wrong password. Beta must expose
the true failure class in diagnostics and all error surfaces.

---

## 16. Security Requirements

### Secrets management

- Every Beta installation generates its own unique secrets.
- Secrets are never stored in source control, logs, or process arguments.
- Secret rotation is a CLI operation.
- JWT tokens expire; refresh token rotation is enforced.

### Environment isolation

- Beta environment is labeled `[BETA]` in all UI surfaces and CLI output.
- Beta application must reject connections using Production credentials.
- Beta must not connect to Production database, cache, or message broker.
- Beta SSL configuration is managed by the installer — not by manual file editing.

### No production data in Beta

- Beta uses test spreadsheets only (never a real Nextcloud spreadsheet with real prices).
- Beta uses test WooCommerce stores only (never a real store with live inventory).
- Beta database is seeded from test fixtures only — never a Production database dump.

### Plugin security

- Plugin code is reviewed before installation.
- Plugins run within the Platform Core adapter contract — no arbitrary process execution.
- Plugin permissions must be explicitly declared and granted.
- Disabling a plugin must not leave residual state that affects Platform Core behavior.

### Audit trail

- All CLI operations that modify configuration are logged to `BETA_STORAGE_PATH/audit.log`.
- All admin UI actions that modify users or permissions are logged.
- Log files are append-only and not exposed to the application process as writable.

---

## 17. Acceptance Criteria for B1

B1 (this phase) is complete when all of the following are true:

- [x] `docs/BETA_MASTER_SPEC.md` exists and contains all 17 required sections (16 original + Control Plane Resilience added 2026-06-27)
- [x] All sections contain architecture and policy content — no placeholder section bodies
- [x] No real domain names committed
- [x] No real URLs committed
- [x] No real credentials committed
- [x] No real spreadsheet paths committed
- [x] No implementation code added or modified
- [x] Cross-references added to `docs/BETA_STRATEGY.md`, `docs/ROADMAP.md`,
      `docs/PLATFORM_MAP.md`, `docs/WORKFLOW.md`
- [x] Production WooPrice source code is unchanged
- [x] Beta is documented as the future development surface — not as a production environment
- [x] No production cutover is implied or scheduled

---

## Cross-References

| Document | Relationship |
|---|---|
| [docs/BETA_STRATEGY.md](BETA_STRATEGY.md) | Owner decision record — Beta isolation policy and CLI vision |
| [docs/A2_ARCHITECTURE.md](A2_ARCHITECTURE.md) | A2 Platform Core — consumed by Beta |
| [docs/ROADMAP.md](ROADMAP.md) | A2 Track and Beta section |
| [docs/PLATFORM_MAP.md](PLATFORM_MAP.md) | Platform architecture |
| [docs/WORKFLOW.md](WORKFLOW.md) | Governance workflow — applies to all B phases |
| [.claude/GOVERNANCE.md](../.claude/GOVERNANCE.md) | Protected systems — unchanged by Beta |
| [docs/phases/A2.9.md](phases/A2.9.md) | Final A2 phase — baseline for Beta |
