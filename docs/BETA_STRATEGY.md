# WooPrice Beta Strategy

## Owner Decision Record

**Decision date:** 2026-06-26
**Decision authority:** Owner

---

## Purpose

WooPrice Beta is a completely isolated application based on the completed A2 Platform
Core. It is the forward-facing environment where all new product work happens.

WooPrice Beta is intended for:

- UI development
- End-to-end testing
- UX validation
- Integration testing
- Demonstrations
- Future customer previews

---

## Critical Policy — Production Freeze

**From this point forward, no new product, UI, or platform capabilities are built on
Production WooPrice.**

| Environment | Policy |
|---|---|
| **Production WooPrice** | Maintenance only · Bug fixes only · Safety fixes only |
| **WooPrice Beta** | All future new work · New UI · CLI · Installer · Plugin architecture · Feature flags · Customer preview · Future Workspace |

This policy is permanent until Beta graduates to a new named production release via
an explicit Owner decision.

---

## Isolation Requirements

WooPrice Beta must have its own isolated instance of every resource. Nothing is shared
with Production except source code.

| Resource | Beta has its own | May share with Production |
|---|---|---|
| GitHub repository | Yes | No |
| Docker Compose configuration | Yes | No |
| Database (SQLite or PostgreSQL) | Yes | No |
| Environment file (`.env`) | Yes | No |
| Secrets | Yes | No |
| Nextcloud spreadsheet | Yes — test spreadsheet only | No |
| WooCommerce store | Yes — test store only | No |
| Logs | Yes | No |
| Cache | Yes | No |
| Domain / port | Yes | No |
| Source code | — | Yes — read-only reference |

---

## Configuration Placeholders

No real values may be committed to source control. All Beta-specific values are entered
interactively during install or configured through the future CLI.

The following placeholders represent Beta configuration values:

| Placeholder | Description |
|---|---|
| `BETA_DOMAIN` | Domain or hostname where Beta is served |
| `BETA_PORT` | Port for Beta application server |
| `BETA_DATABASE_URL` | Full database connection URL for Beta |
| `BETA_POSTGRES_USER` | PostgreSQL username for Beta A2 database |
| `BETA_POSTGRES_PASSWORD` | PostgreSQL password for Beta A2 database |
| `BETA_JWT_SECRET` | JWT signing secret for Beta authentication |
| `BETA_REST_API_SECRET` | REST API secret key for Beta |
| `BETA_NEXTCLOUD_URL` | Nextcloud URL for Beta test spreadsheet source |
| `BETA_NEXTCLOUD_FILE_PATH` | Path to Beta test spreadsheet in Nextcloud |
| `BETA_WOOCOMMERCE_URL` | WooCommerce store URL for Beta test store |
| `BETA_WOOCOMMERCE_KEY` | WooCommerce consumer key for Beta test store |
| `BETA_WOOCOMMERCE_SECRET` | WooCommerce consumer secret for Beta test store |
| `BETA_TIMEZONE` | Timezone for Beta scheduler and logs |
| `BETA_CURRENCY` | Default currency for Beta pricing operations |
| `BETA_ADMIN_EMAIL` | Initial admin account email for Beta |

No installer, CLI, or configuration file may hardcode any of the above values.
All must be supplied at runtime or through interactive setup.

---

## Future Installer Requirements

The Beta installer must support interactive, guided setup for all configuration values.
No manual file editing should be required during normal setup.

The installer must collect:

- Domain and port
- Database engine selection and connection details
- PostgreSQL credentials (for A2 track)
- JWT secret (generated or user-supplied)
- REST API secret (generated or user-supplied)
- Source type selection (Nextcloud, CSV, Excel, etc.)
- Source credentials (URL, path, username, password)
- WooCommerce credentials (URL, consumer key, consumer secret)
- SSL mode
- Timezone
- Default currency
- Admin account (email, initial password)
- Storage paths (logs, backups, cache)
- Backup location

---

## CLI Vision

Future command entry point: `wooprice`

**Planned sub-commands:**

| Command | Responsibility |
|---|---|
| `wooprice install` | Interactive guided installation |
| `wooprice configure` | Reconfigure any setting without reinstalling |
| `wooprice status` | Application health summary |
| `wooprice health` | Deep health check (DB, sources, channels, adapters) |
| `wooprice migrate` | Run pending database migrations |
| `wooprice backup` | Create a backup |
| `wooprice restore` | Restore from a backup |
| `wooprice logs` | Stream or export logs |
| `wooprice update` | Update application version |
| `wooprice adapters` | Manage installed channel adapters |
| `wooprice channels` | Configure destination channels |
| `wooprice sources` | Configure data sources |
| `wooprice users` | Manage user accounts and permissions |
| `wooprice scheduler` | Manage scheduled execution |
| `wooprice ai` | Manage AI Foundation settings |
| `wooprice diagnostics` | Run diagnostic suite |

The CLI is not implemented in this phase. This section documents the intended vision
for planning and governance purposes.

---

## Feature Flags

Every major feature must be independently enableable or disableable via configuration.
No feature flag bypasses the safety invariants of the A2 Platform Core.

| Feature Flag | Controls |
|---|---|
| `FEATURE_RULE_ENGINE` | Transformation Rule Engine (A2.3) |
| `FEATURE_SAFETY_ENGINE` | Safety Policy Engine (A2.4) |
| `FEATURE_CHANGE_SETS` | Change Set Engine (A2.5) |
| `FEATURE_DRY_RUN` | Dry Run Engine (A2.6) |
| `FEATURE_SCHEDULER` | Scheduling Engine (A2.8) |
| `FEATURE_AI` | AI Foundation (A2.9) |
| `FEATURE_MULTI_CHANNEL` | Multi-channel destination support |
| `FEATURE_COMPETITOR` | Competitor pricing features |

Feature flags are configuration values only. No feature flag may bypass A2 safety
invariants or the Trusted Execution Path validation sequence.

---

## Plugin Architecture

Future channel adapters and source adapters must be installable without modifying
Platform Core. Plugin discovery and registration will be defined in a future phase.

**Planned plugin types:**

Channel adapters (destination writes):

- WooCommerce Adapter
- Shopify Adapter
- Magento Adapter
- ERP Adapter

Source adapters (data ingestion):

- CSV Adapter
- Excel Adapter
- WooCommerce Source Adapter
- Direct DB Adapter

Plugin installation must not modify any A2 Platform Core file. Plugins register
themselves at startup via the adapter registry (A2.2 pattern).

---

## What WooPrice Beta Is NOT

- Beta is **not a production environment**.
- Beta is **not a staging environment for Production WooPrice**.
- Beta is **not connected to any real customer data**.
- Beta is **not deployed to any production-facing domain**.
- Beta will **not graduate to production without explicit Owner decision**.

---

## Governance Rules for Beta

1. No real domain, URL, credential, or secret may be committed to source control.
2. All Beta configuration must flow through the installer or CLI — never through
   manually edited files in source control.
3. Production WooPrice source code must not be modified for Beta-only concerns.
4. A2 Platform Core invariants (TEP isolation, advisory-only AI, no destructive
   migrations) apply in Beta identically to Production.
5. Beta has no deployment authority. Deployment requires explicit Owner approval.
6. Any change that would affect Production WooPrice behavior requires the same
   governance gate as a production change.

---

## Relationship to A2 Platform

WooPrice Beta builds on the completed A2 Platform Core:

| A2 Phase | Status | Beta Relevance |
|---|---|---|
| A2.1 — Canonical Product Model | CLOSED | Foundation — Beta uses this |
| A2.2 — Source Adapter Framework | CLOSED | Beta uses adapter pattern |
| A2.3 — Transformation Rule Engine | CLOSED | Beta uses Rule Engine |
| A2.4 — Safety Policy Engine | READY FOR OWNER APPROVAL | Beta will use when approved |
| A2.5 — Change Set Engine | CLOSED | Beta uses Change Sets |
| A2.6 — Dry Run Engine | CLOSED | Beta uses Dry Run |
| A2.7 — Execution Engine | CLOSED | Beta uses Execution Engine |
| A2.8 — Scheduling Engine | CLOSED | Beta uses Scheduler |
| A2.9 — AI Foundation | READY FOR OWNER REVIEW | Beta will use when approved |

Beta does not introduce new A2 platform capabilities. New capabilities continue through
the A2 phase governance workflow.

---

## Cross-References

- A2 Architecture: [docs/A2_ARCHITECTURE.md](A2_ARCHITECTURE.md)
- Roadmap: [docs/ROADMAP.md](ROADMAP.md)
- Platform Map: [docs/PLATFORM_MAP.md](PLATFORM_MAP.md)
- Workflow: [docs/WORKFLOW.md](WORKFLOW.md)
- Governance: [.claude/GOVERNANCE.md](../.claude/GOVERNANCE.md)
- A2.9 (latest phase): [docs/phases/A2.9.md](phases/A2.9.md)
- Beta master specification: [docs/BETA_MASTER_SPEC.md](BETA_MASTER_SPEC.md)
