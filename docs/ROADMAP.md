# WooPrice Roadmap

## Current Status

Current branch: main
Current feature stream: 7.x

---

## Completed

### Migration Era (Phases 1–6)

| Phase | Description | Commit |
|---|---|---|
| Phase 1–3 | Core backend: FastAPI, product cache, sync engine, auth | — |
| Analytics Sprint A | Analytics page | `f4ab6cb` |
| Auth Integration | AuthProvider, JWT, RequirePermission | bundled |
| Direction Layer | RTL/LTR support, Tailwind logical properties | `585373e` |
| Phase 4c | Logs page migration | `bf1d458` |
| WS-A | Workspace shell, cache refresh, spreadsheet status | `4b38182` |
| WS-B | Preview SSE, pre-fetch filters, product table | `4b38182` |
| WS-C | Dry Run, Apply SSE, Writeback, Inline edit, Rollback | `6bb8342` |
| WS-D | Integration audit: H-D1 and MD-2 found and resolved | `6bb8342` |
| Phase 5 | Production cutover preparation, documentation | `377acae` |
| Phase 6 | Legacy frontend replacement, React SPA cutover | shipped |

### 7.x Feature Stream (completed)

| Item | Description | Notes |
|---|---|---|
| 7.4A | Product Browser | Server-side filter, sort, paginate, category multi-select |
| 7.4A R1 | Bug fixes | stock_status=all, enum validation |
| 7.4A R2 | Remediation | Page size persistence, price filter parity, deterministic sort |
| 7.4B | Permission Architecture Review | Analysis only |
| 7.5A | Route Security Hardening | /workspace, /settings guards; permission-aware sidebar |
| 7.5A R1 | Permission Inheritance Remediation | effectiveHasPerm, can_access_site gate, 24 tests |
| 7.5A R2 | /home Route Guard + Component Tests | 50 component tests, PLATFORM_MAP accuracy fixes |
| A1 | Change Set Platform Architecture Design | Session-derived design only — no committed design document exists. A2 will formalize. |
| A2 | WooPrice A2 Architecture Design | Committed: `docs/A2_ARCHITECTURE.md`. Pending Codex re-audit. |
| A2 R1 | A2 Architecture Revision R1 | Owner decisions incorporated: canonical product model, live freshness, intersection scope, PostgreSQL, trusted automation deferred, workspace compatibility. Pending Codex re-audit. |
| A2.1 | Canonical Product Model + PostgreSQL Foundation | app/a2/ package: CanonicalProduct, ChannelListing, ChannelCredential models; repositories; service scaffolding; alembic_a2.ini + a2_migrations/; tests/a2/. Additive only. Commits: `7e64e17` (impl), `cfabd7a` (remediation). **Codex PASS. Complete.** |
| A2.2 | Source Adapter Framework | Planned — spec pending. |

---

## Current Phase: 7.x Feature Stream

The 7.x numbering is an implementation-level feature stream running within the broader product development effort. It is separate from the Phase 1–6 migration era numbering.

See `docs/PLATFORM_MAP.md` Section E for the detailed 7.x roadmap tree.

Near-term items:

| Item | Description | Status |
|---|---|---|
| 7.5B | Permission Model V2 (can_browse_products, can_dry_run splits) | Planned |
| 7.5C | Admin UX Rebuild | Planned |
| 7.6A | Settings Center | Planned |
| 7.6B | Product Browser Advanced Filters | Planned |
| 7.7A | Bulk Edit Framework | Design complete (A1); implementation pending |
| 7.7B | Inline Editing in Product Browser (price/stock edit in rows) | Planned |
| 7.8A | Dashboard Redesign | Planned |
| 7.9A | Saved Views | Planned |

---

## Strategic Direction (Owner Decisions)

The following represents the owner-authorized product direction. These items require
architecture design before implementation. See `docs/OWNER_DECISIONS.md` for rationale.

### Priority order

1. Safe pricing operations (dry run, configurable safety rules, no silent writes)
2. Scheduling (first-class deferred and windowed execution)
3. Scoped permissions (Brand / Category / Channel scope assignments)
4. Multi-source architecture (source adapter layer; WooPrice is not locked to one spreadsheet)
5. Multi-channel foundation (channel adapter layer; WooCommerce + Digikala + SnapShop + Shopify + Magento + Amazon + custom CMS)
6. Transformation rules engine (adjustable per product / brand / category / channel)
7. Lightweight synchronization (delta detection, not full source scanning)
8. AI Pricing (future — not scheduled)

### Change Set Scheduling Stream (S1–S4)

This stream covers **Change Set execution scheduling** — the ability for a seller to
choose when a Change Set executes (now, deferred, or low-traffic window).

This is distinct from multi-channel automation sync schedules (see 8.0 below).

| Item | Description | Status |
|---|---|---|
| S1 | Scheduling architecture (modes: Now / Deferred / Low-traffic window) | Blocked on A2 Phases 1–7 |
| S2 | Scheduler backend (queue executor, heartbeat, abandonment, DST, per-channel concurrency) | Blocked on S1 |
| S3 | Schedule UI (mode selector, time picker, low-traffic recommendation) | Blocked on S2 |
| S4 | Scheduled Change Set history and cancellation | Blocked on S2 |

Per owner decision (A2 R1): S1–S4 may not begin until ALL of the following are in production:
Channel abstraction (Phase 2), Scoped permissions (Phase 3), Safety engine (Phase 4),
Rule engine (Phase 5), Canonical product model (Phase 1), Change Set engine (Phase 6),
Source adapter layer (Phase 7).

### Change Set Platform

A1 architecture design: complete (session history — no committed design doc).
A2 architecture: committed to `docs/A2_ARCHITECTURE.md`. Pending owner approval.

**A2 R1 covers (see `docs/A2_ARCHITECTURE.md` for full design):**
- Canonical Product Model: products + channel_listings; WC IDs demoted to channel-specific
- Source adapter layer: capability flags, streaming, stable row identity, snapshots
- Transformation rule engine: 5 rule types, 6-level precedence, versioned
- Safety policy engine: 12 rule types, warn/block, versioned, AI cannot override
- Change Set engine: immutable DryRunDigest, full state machine, durable execution
- Scheduling engine: hardened (cancellation, retry/backoff, DST, per-channel concurrency)
- Channel adapter: live freshness verification (mandatory, blocks if unverifiable), batch model
- AI layer: error detection, freshness monitor, anomaly explainer; trusted automation DEFERRED
- Database: PostgreSQL strategic target; full schema with constraints, FKs, concurrency model
- Implementation sequence: scheduling blocked on 7 prior phases

Implementation sequence (owner-mandated):
  Phase 1: Canonical Product Model
  Phase 2: Channel Adapter Layer
  Phase 3: Scoped Permissions
  Phase 4: Safety Policy Engine
  Phase 5: Transformation Rule Engine
  Phase 6: Change Set Engine + Immutable Dry Run
  Phase 7: Source Adapter Layer
  Phase 8: Scheduling Engine  ← first unlock; requires all above in production
  Phase 9: PostgreSQL Migration (can run in parallel)

Zero implementation before A2 R1 clears Codex re-audit and owner approves.

### Scoped Permissions

Users will be assigned scope (Brand, Category, or Channel) by admin.
Change Sets may only contain products within the user's assigned scope.
This is a new permission dimension, not a replacement for existing flags.

### Multi-Source Architecture

WooPrice supports multiple price source types. The spreadsheet is one source, not the identity.

| Item | Description | Status |
|---|---|---|
| P1 | Source adapter interface design | Blocked on A2 |
| P2 | Field mapping UI (source columns → WooPrice fields) | Blocked on P1 |
| P3 | Source stability validation (schema, IDs, currency, duplicates) | Blocked on P1 |
| P4 | Native pricing table (built-in source for users with no external source) | Blocked on P1 |
| P5 | MySQL / custom DB adapter | Blocked on P1 |

No P1–P5 implementation begins before A2 architecture is approved.

### Multi-Channel

Target channels (in priority order): WooCommerce (implemented), Digikala, SnapShop,
Shopify, Magento, Amazon, custom CMS.

Channel adapter interface to be designed in A2. No second channel implementation
until interface is approved.

### Transformation Rules Engine

| Item | Description | Status |
|---|---|---|
| T1 | Rule engine architecture (rule types, precedence model) | Blocked on A2 |
| T2 | Manual price / cost+profit / cost×FX+profit rules | Blocked on T1 |
| T3 | Channel-specific rule overrides | Blocked on T1 |
| T4 | Competitor-based pricing (requires external data source) | Future |

### PostgreSQL Migration

| Item | Description | Status |
|---|---|---|
| DB1 | Deploy A2 tables to PostgreSQL on staging | Blocked on A2 approval |
| DB2 | pg_migrate.py: SQLite → PostgreSQL data migration | Blocked on DB1 |
| DB3 | Reconciliation: row counts + spot-check | Blocked on DB2 |
| DB4 | Production PostgreSQL cutover (maintenance window) | Blocked on DB3 + owner approval |

SQLite acceptable for local dev and transition. Production target: PostgreSQL from A2.

### Source Evolution

Source moves from workflow driver to change event source.
Delta detection: detect changed rows vs. products_cache; propose Change Set.
Full source scanning is an anti-pattern to eliminate.

---

## Open Findings

### Medium (from WS-C audit — tracked, non-blocking)

- WS-C M1: CANCEL_ERROR stores error in writebackMsg (field collision)
- WS-C M2: Apply button enabled after applyPhase=error but startApply no-ops
- WS-C M3: Header checkbox has no indeterminate state

### Low (from WS-C audit)

- WS-C L1: applyRunning constant dead code
- WS-C L2: inline edit icon buttons missing group class
- WS-C L3: rollbackAdvisory banner has no dismiss button
- WS-C L4: applyItems array accumulates without cap

---

## Stable Checkpoints

- `react-wsd-stable`
- `75c4be2`
- `6fdd894`
- `6bb8342`
- `4ef73a8`
- `5a2eeff` (Phase 5 documentation stabilization)
- `377acae` (Phase 5 Codex remediation — all findings resolved)
- `5ead5b1` (7.5A R2: /home route guard, component tests, PLATFORM_MAP accuracy)
- `e1c3b94` (Governance R2: audit claims, scheduling terminology, domain authority matrix)
- `63b6a2e` (Governance R5: final audit line findings resolved)
- A2 R1 committed — pending Codex re-audit (architecture document)
- `cfabd7a` (A2.1 Codex PASS — canonical product model, PostgreSQL foundation, isolation verified)
