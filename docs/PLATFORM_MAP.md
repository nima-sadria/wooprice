# WooPrice Platform Map

## Platform Map Metadata

| Field | Value |
|---|---|
| Last verified commit | 1257e29 |
| Last verified date | 2026-06-23 |
| Verified against code | Yes |
| Source of truth priority | Code > Database schema > Migrations > ROADMAP > PLATFORM_MAP |

Verified against: `frontend/src/App.tsx`, `frontend/src/auth.tsx`, `frontend/src/components/Sidebar.tsx`, `app/main.py`, `app/config.py`, `Dockerfile`. Unverifiable items are marked UNKNOWN.

---

Living architecture reference. Must be kept current when architecture, routing, permissions, API contracts, workflow behavior, deployment, or major UI modules change.

---

## A. Current Architecture

```
WooPrice
├── Frontend  (React 18 + TypeScript + Tailwind)
│   ├── Auth layer
│   │   ├── JWT token storage (localStorage, keys: wp_token / wp_user)
│   │   ├── AuthProvider  — on-mount /api/auth/me fetch; storage-event refresh (no polling, no frontend token decode)
│   │   ├── RequirePermission  — route + inline action guards
│   │   └── AuthGuard  — redirect to /login if unauthenticated
│   ├── Routes
│   │   ├── /home          → Dashboard        [can_access_site]
│   │   ├── /workspace     → Workspace        [can_fetch]
│   │   ├── /products      → Product Browser  [can_fetch]
│   │   ├── /analytics     → Analytics        [can_access_site]
│   │   ├── /audit         → Audit History    [can_view_logs]
│   │   ├── /logs          → Audit Log        [can_view_logs]
│   │   ├── /settings      → Settings         [can_view_settings]
│   │   └── /admin         → Admin            [is_admin]
│   ├── Sidebar  — permission-aware nav (hides items user lacks)
│   └── Pages
│       ├── Dashboard       — stat cards, sync chart, currency, recent logs
│       ├── Workspace       — preview, dry run, apply, inline edit
│       ├── Product Browser — server-side filter/sort/paginate, category picker
│       ├── Analytics       — seller views + admin overview (role-split)
│       ├── Audit History   — change history, undo action (admin only)
│       ├── Logs            — audit log, job history
│       ├── Settings        — placeholder (Phase 7.6A)
│       └── Admin           — user CRUD, permission toggles, maintenance mode
│
├── Backend  (FastAPI + Python 3.12)
│   ├── Auth
│   │   ├── POST /api/auth/login    — Nextcloud credential verify → JWT issue
│   │   ├── GET  /api/auth/me       — token decode + permission snapshot
│   │   ├── JWT  — HS256, permission_version invalidation
│   │   └── Rate limiting  — per-IP + per-identifier, sliding window
│   ├── Sync Engine
│   │   ├── POST /api/preview               — parse sheet → SyncJob(preview)
│   │   ├── GET  /api/preview/stream        — SSE: fetch prices + classify rows
│   │   ├── POST /api/sync/{id}/dry-run     — analyze job, no WC write
│   │   ├── POST /api/sync/{id}/confirm     — guard-check → confirm apply
│   │   └── GET  /api/sync/{id}/apply-stream — SSE: WC writes, audit, cache patch
│   ├── Fetch Engine
│   │   ├── GET /api/fetch/full             — full WC catalog sync (SSE)
│   │   ├── GET /api/fetch/light            — incremental sync by modified_after (SSE)
│   │   └── GET /api/fetch/deep-variations  — all variation pages sync (SSE, admin)
│   ├── Product Cache  (SQLite via SQLAlchemy)
│   │   ├── products_cache  — wc_id, name, sku, price, stock, image, brand, category
│   │   ├── GET /api/products               — paginated, filtered, sorted
│   │   ├── GET /api/products/categories    — distinct categories from cache
│   │   ├── GET /api/products/{id}/lookup   — cache-first, WC fallback
│   │   └── GET /api/products/{id}/thumb    — JPEG thumbnail (public, disk-cached)
│   ├── Direct Edit
│   │   ├── PUT /api/products/{id}/price    — WC write + cache patch + writeback
│   │   └── PUT /api/products/{id}/stock    — WC write + cache patch
│   ├── Emergency Engine
│   │   ├── POST /api/emergency/preview          — batch price calculation, no WC write
│   │   ├── GET  /api/emergency/pending          — list pending batches
│   │   ├── GET  /api/emergency/{id}             — batch detail
│   │   ├── POST /api/emergency/{id}/apply       — atomic claim → WC write
│   │   └── DELETE /api/emergency/{id}           — cancel pending batch
│   ├── Rollback Engine
│   │   ├── POST /api/rollback/product/{id} — restore last change_history entry
│   │   └── POST /api/rollback/job/{id}     — restore all entries for a job (≤500)
│   ├── Audit
│   │   ├── AuditLog table  — every action, IP, job_id, detail JSON
│   │   ├── ChangeHistory   — old/new price+stock per product per change
│   │   ├── GET  /api/audit-logs            — action log [can_view_logs]
│   │   ├── GET  /api/audit/history         — change history [can_view_logs]
│   │   └── POST /api/audit/undo            — restore from change_history (admin)
│   ├── Analytics
│   │   ├── GET /api/dashboard              — stat cards, coverage, chart
│   │   ├── GET /api/analytics              — seller issue lists (stale/no-price)
│   │   ├── GET /api/analytics/brands       — brand coverage
│   │   ├── GET /api/analytics/seller/*     — category/brand/staleness drill-down
│   │   ├── GET /api/analytics/admin/*      — overview/trend/top-movements (admin)
│   │   ├── GET /api/analytics/daily-changes — 4-color bar chart data
│   │   └── GET /api/analytics/change-log   — filterable apply history [can_view_logs]
│   ├── Admin
│   │   ├── GET/POST/PATCH/DELETE /api/admin/app-users* — user CRUD
│   │   ├── POST /api/admin/app-users/{u}/revoke-tokens
│   │   ├── GET/POST /api/admin/maintenance  — maintenance mode (super admin)
│   │   └── GET /api/system/diagnostics      — system info (super admin)
│   ├── Settings + Alarms
│   │   ├── GET /api/settings               — masked config [can_view_settings]
│   │   ├── GET /api/alarm-settings         — thresholds [can_view_settings]
│   │   └── PUT /api/alarm-settings         — write thresholds (admin)
│   ├── Utilities
│   │   ├── GET /api/health                 — service health (public)
│   │   ├── GET /api/currency               — IRR rates proxy (public, 5-min cache)
│   │   ├── GET /api/categories             — WC category list [can_access_site]
│   │   ├── GET /api/cache/status           — cache info [can_fetch]
│   │   ├── POST /api/cache/clear           — flush memory cache (admin)
│   │   ├── POST /api/products/cache-clear  — flush DB cache (admin)
│   │   ├── GET /api/jobs                   — job list [can_view_logs]
│   │   ├── GET /api/jobs/{id}              — job detail [can_view_logs]
│   │   ├── GET /api/spreadsheet/meta       — sheet HEAD metadata [can_fetch]
│   │   └── POST /api/jobs/{id}/writeback   — write results to sheet [can_apply]
│   └── Database  (SQLite, single file)
│       ├── app_users           — username, permissions, is_admin, is_active, pv
│       ├── products_cache      — WC product snapshot
│       ├── sync_jobs           — job state machine
│       ├── sync_items          — per-product row within a job
│       ├── change_history      — before/after for every WC write
│       ├── change_tracking     — field-level drift detection
│       ├── audit_logs          — every user action
│       ├── daily_metrics       — aggregated daily counters
│       ├── emergency_batches   — emergency batch header
│       ├── emergency_items     — per-product emergency rows
│       └── app_settings        — key/value store (maintenance_mode, etc.)
│
├── External Services
│   ├── WooCommerce REST API  — product read/write, stock sync
│   ├── Nextcloud / OnlyOffice — XLSX price sheet source + writeback target
│   └── alanchand.com API     — IRR currency rates (USD/EUR/AED/TRY)
│
└── Deployment  (Docker)
    ├── Container: wooprice  — FastAPI app + React static build
    ├── Port: 8000 (internal)
    ├── Nginx Proxy Manager  — TLS termination, reverse proxy
    ├── Production URL: woo.softpple.business
    ├── Database: /app/data/wooprice.db (volume-mounted)
    └── A2 PostgreSQL  — NOT included in default stack; requires override file
        ├── Default stack:  docker compose up -d
        └── A2 stack:       docker compose -f docker-compose.yml -f docker-compose.a2.yml up -d
```

---

## B. Workflow Tree

```
User workflows
├── Login
│   ├── POST /api/auth/login  (Nextcloud credential verify)
│   ├── JWT issued with permission_version
│   ├── GET /api/auth/me  → permission snapshot stored in React context
│   └── Session valid until token expires or permission_version bumped
│
├── Fetch / Cache Sync
│   ├── Full Sync   → GET /api/fetch/full (SSE)  [can_fetch]
│   │   └── Fetches all top-level products + images from WooCommerce
│   ├── Light Sync  → GET /api/fetch/light (SSE)  [can_fetch]
│   │   └── Fetches only products modified since last sync watermark
│   └── Deep Sync   → GET /api/fetch/deep-variations (SSE)  [admin]
│       └── Fetches all variation sub-pages (slow, admin only)
│
├── Sheet Preview  [can_fetch]
│   ├── POST /api/preview  — download XLSX, parse rows, create SyncJob(preview)
│   └── GET /api/preview/stream (SSE)  — classify rows vs WC cache, stream results
│
├── Dry Run  [can_apply]
│   ├── POST /api/sync/{id}/dry-run
│   ├── Computes: invalid rows, large price changes, alarm thresholds, validation
│   ├── Sets dry_run_status: passed | warnings | blocked
│   └── No WooCommerce writes
│
├── Apply  [can_apply]
│   ├── POST /api/sync/{id}/confirm  — dry-run guards + sheet freshness check
│   ├── GET  /api/sync/{id}/apply-stream (SSE)  — streams WC writes
│   ├── Each successful write: cache patch + ChangeHistory + dry-run invalidation
│   └── POST /api/jobs/{id}/writeback  — write results back to XLSX
│
├── Emergency Apply  [admin]
│   ├── POST /api/emergency/preview  — compute batch (no WC write)
│   ├── POST /api/emergency/{id}/apply  — atomic claim → WC write per item
│   │   ├── Checkpoint A: status=applying (committed before WC call)
│   │   ├── Checkpoint B: status=wc_succeeded (committed after WC call)
│   │   └── Checkpoint C: status=applied (committed after cache + ChangeHistory)
│   └── DELETE /api/emergency/{id}  — cancel pending batch
│
├── Product Browser  [can_fetch]
│   ├── GET /api/products  — server-side filter + sort + paginate
│   ├── Filters: search, type, stock, price, category (multi), quality flags
│   ├── Sort: newest | oldest | name_asc | name_desc (deterministic, secondary wc_id)
│   └── Thumbnails: GET /api/products/{id}/thumb (public)
│
├── Inline Edit  [can_edit_price / can_edit_stock]  (current)
│   ├── PUT /api/products/{id}/price  — WC write + cache patch + writeback + ChangeHistory
│   └── PUT /api/products/{id}/stock  — WC write + cache patch + ChangeHistory
│
├── Bulk Edit  (future — Phase 7.7A)
│   ├── Selection → staged batch → dry run → apply
│   └── Requires can_bulk_edit (planned) or admin
│
└── Rollback / Undo  [admin]
    ├── POST /api/rollback/product/{id}  — restore last ChangeHistory entry
    ├── POST /api/rollback/job/{id}      — restore all entries for job (≤500)
    └── POST /api/audit/undo             — restore from audit history (confirm=true)
```

---

## C. Permission Tree

```
Permissions  (current)
├── can_access_site
│   ├── Gate: checked before every other specific permission for regular users
│   ├── Routes: /home (Dashboard), /analytics
│   └── APIs: /api/dashboard, /api/analytics, /api/analytics/brands,
│             /api/analytics/seller/*, /api/analytics/daily-changes,
│             /api/categories
│
├── can_fetch
│   ├── Routes: /workspace, /products
│   └── APIs: /api/products, /api/products/cache-status, /api/products/{id}/lookup,
│             /api/cache/status, /api/fetch/full, /api/fetch/light,
│             /api/preview, /api/preview/stream, /api/spreadsheet/meta
│
├── can_apply
│   ├── Route: /workspace (apply actions)
│   └── APIs: /api/sync/{id}/confirm, /api/sync/{id}/dry-run,
│             DELETE /api/sync/{id}, /api/sync/{id}/apply-stream,
│             /api/jobs/{id}/writeback
│
├── can_edit_price
│   └── API: PUT /api/products/{id}/price
│
├── can_edit_stock
│   └── API: PUT /api/products/{id}/stock
│
├── can_view_logs
│   ├── Routes: /audit, /logs
│   └── APIs: /api/audit-logs, /api/jobs, /api/jobs/{id},
│             /api/analytics/change-log, /api/audit/history
│
├── can_view_settings
│   ├── Route: /settings
│   └── APIs: /api/settings (read), /api/alarm-settings (read)
│
├── is_admin  (DB flag — bypasses all permission checks above)
│   ├── Route: /admin
│   └── APIs: /api/admin/app-users*, /api/alarm-settings (write),
│             /api/analytics/admin/*, /api/rollback/*, /api/emergency/*,
│             /api/audit/undo, /api/cache/clear, /api/products/cache-clear,
│             /api/debug/sheet, /api/fetch/deep-variations
│
└── super_admin  (SUPER_ADMIN_USERS env var — not stored in DB)
    └── APIs: /api/admin/maintenance, /api/system/diagnostics

Default new user: can_access_site + can_fetch + can_apply + can_edit_price + can_edit_stock
                  (can_view_logs=false, can_view_settings=false)
Admin user:       all 7 flags = true

Permissions  (planned — Phase 7.5B)
├── can_browse_products  (split from can_fetch)
│   └── Product Browser read-only path only
├── can_dry_run  (split from can_apply)
│   └── Dry Run analysis only, no WC writes
├── can_rollback  (split from is_admin)
│   └── Product + job rollback without full admin
├── can_emergency_edit  (split from is_admin)
│   └── Emergency price batches without full admin
└── can_bulk_edit  (new — Phase 7.7A)
    └── Bulk edit staging + apply
```

---

## D. Safety Tree

```
Safety mechanisms
├── Dry Run protection
│   ├── Apply is blocked unless dry_run_status ∈ {passed, warnings}
│   ├── blocked status → Apply rejected until re-run
│   └── invalidated status → Apply rejected until re-run
│
├── Apply invalidation
│   ├── Any direct edit (price/stock) invalidates all active dry runs for that product
│   ├── Invalidation is unconditional — no job_id required
│   └── Emergency Apply also invalidates related dry runs
│
├── Sheet freshness (stale preview protection)
│   ├── MD5 hash of XLSX stored at preview creation
│   ├── Apply rechecks hash against current Nextcloud file
│   └── Hash mismatch → Apply blocked (HTTP 409)
│
├── Dry-run scope guard
│   ├── Selection at Apply must exactly match selection at Dry Run
│   └── Scope mismatch → Apply blocked (HTTP 409)
│
├── Emergency Apply — atomic claim
│   ├── Single SQL UPDATE WHERE status='pending' before any WC write
│   ├── rowcount=0 → concurrent request already claimed; reject
│   └── Three checkpoints (applying → wc_succeeded → applied) survive crashes
│
├── Emergency Apply — freshness
│   └── Items whose cached price changed since preview are skipped (stale)
│
├── JWT validation
│   ├── HS256 signature checked on every authenticated request
│   ├── permission_version in token checked against DB on every request
│   └── Stale pv → HTTP 401 (forces re-login to pick up new permissions)
│
├── Maintenance mode
│   ├── Enabled/disabled by super admin only
│   ├── Blocks all API calls for non-super-admin users (middleware)
│   └── /api/health and /api/auth/* always bypass maintenance mode
│
├── Audit logging
│   ├── State-mutating and access-sensitive actions written to AuditLog before response is returned
│   ├── Read-only API calls (/api/products, /api/dashboard, etc.) are NOT audited
│   ├── Uses dedicated DB session — audit failure never breaks the response
│   └── Covers: login, fetch, apply, direct_edit, emergency, rollback, undo,
│               permission_denied, user_access_*, maintenance_*
│
├── WooCommerce write path protection
│   ├── All WC writes gated behind JWT + permission check
│   ├── Apply path — additionally requires dry-run guards (status ∈ {passed, warnings}),
│   │   sheet freshness hash match, and scope match between dry run and apply
│   ├── Direct Edit path — no dry-run gate; invalidates dry runs for the affected product
│   ├── Emergency Apply path — no dry-run gate; uses atomic SQL claim + per-item
│   │   freshness check (skips items whose cached price changed since preview)
│   ├── Rollback / Undo path — admin-only; no dry-run gate; writes ChangeHistory
│   └── WC write failures surface as HTTP 502 without corrupting DB state
│
└── Alarm thresholds
    ├── Warning threshold: surfaced as dry_run_status=warnings (non-blocking by default)
    ├── Critical threshold + block_enabled=true → dry_run_status=blocked
    └── block_enabled=false (default) — no accidental Apply freeze without opt-in
```

---

## E. Roadmap Tree

Note: This section uses 7.x/8.x feature numbering within the implementation stream.
The repository-level roadmap (`docs/ROADMAP.md`) tracks higher-level phases (Phase 5,
Phase 6, etc.). These are independent naming schemes — 7.x here does not mean Phase 7.
Current repository roadmap status: Phase 6 is the next planned phase. Current work
is the 7.x feature stream within Phase 5 (Production Cutover Preparation).

```
Roadmap
├── ✅ 7.4A  Product Browser
│   └── Server-side filters, pagination, sort, category multi-select
│
├── ✅ 7.4A R1  Bug fixes
│   └── stock_status=all, enum validation
│
├── ✅ 7.4A R2  Remediation
│   ├── Page size persistence (sessionStorage)
│   ├── Price filter parity (final_price OR regular_price)
│   └── Deterministic sort (secondary wc_id key)
│
├── ✅ 7.4B  Permission Architecture Review
│   └── Full analysis, no implementation
│
├── ✅ 7.5A  Route Security Hardening
│   ├── /workspace route guard (can_fetch)
│   ├── /settings route guard (can_view_settings)
│   └── Permission-aware sidebar
│
├── 🔲 7.5B  Permission Model V2
│   ├── Add can_browse_products (split from can_fetch)
│   ├── Add can_dry_run (split from can_apply)
│   ├── DB migration + defaults
│   └── Update Admin.tsx labels, auth types, endpoints
│
├── 🔲 7.5C  Admin UX Rebuild
│   └── Grouped permissions, role presets, cleaner user management
│
├── 🔲 7.6A  Settings Center
│   └── Implement /settings page with alarm thresholds, URL config
│
├── 🔲 7.6B  Product Browser Advanced Filters
│   └── Price range, brand filter, saved filter state
│
├── 🔲 7.7A  Bulk Edit Framework
│   ├── Multi-select in Product Browser
│   ├── Staged batch → dry run → apply
│   └── Requires can_bulk_edit permission
│
├── 🔲 7.7B  Inline Editing
│   └── Edit price/stock directly in Product Browser rows
│
├── 🔲 7.8A  Dashboard Redesign
│   └── Improved stat cards, metric clarity, data freshness signals
│
├── 🔲 7.9A  Saved Views
│   └── Persistent filter/sort presets in Product Browser
│
└── 🔲 8.0   Business Operations Suite
    └── Multi-store support, reporting exports, scheduled syncs
```

---

## F. Known Gaps Tree

```
Known gaps  (as of 7.5A + Audit Remediation 2026-06-23)
├── ✅ Frontend permission inheritance mismatch (fixed — Audit Remediation 2026-06-23)
│   └── hasPerm and RequirePermission now use effectiveHasPerm, mirroring backend
│       _enforce_permission: can_access_site is the global gate for regular users
│
├── ✅ /home had no route guard (fixed — 7.5A R2 2026-06-23)
│   └── /home now wrapped with RequirePermission(can_access_site); component tests added
│
├── Permission model
│   ├── can_fetch overloaded: browse-products and trigger-sync same permission
│   ├── can_apply overloaded: dry-run analysis and WC writes same permission
│   └── is_admin bundles user-management with rollback + emergency power
│       → Planned fix: 7.5B
│
├── UI consistency
│   └── Product Browser card spacing/density differs from Dashboard/Workspace
│       → Partially addressed in 7.4A R2 UI correction
│
├── Settings
│   └── /settings page is a placeholder; no configuration UI yet
│       → Planned: 7.6A
│
├── Admin UX
│   └── Permission toggles are flat; no grouping or role presets
│       → Planned: 7.5C
│
├── Dashboard metrics
│   └── Some stat cards source from SyncJob snapshots, not live ProductCache
│       → Partially improved in analytics overhaul
│
├── Bulk Edit
│   └── No multi-product selection or batch staging workflow
│       → Planned: 7.7A
│
├── Inline Editing
│   └── Price/stock edit in Product Browser rows not yet implemented
│       → Planned: 7.7B
│
└── Saved Views
    └── No persistent filter presets in Product Browser
        → Planned: 7.9A
```

---

## H. A2 Track

Architecture reference: `docs/A2_ARCHITECTURE.md`

### H1. A2 Governance

| Area | Status |
|---|---|
| Governance | PASS |
| A2 Architecture | APPROVED |
| A2.1 — Canonical Product Model + PostgreSQL Foundation | CLOSED |
| A2.2 — Source Adapter Framework | CLOSED |
| A2.3 — Transformation Rule Engine | CLOSED |

### H2. A2 Phase Sequence

| Phase | Name | Status |
|---|---|---|
| A2.1 | Canonical Product Model + PostgreSQL Foundation | CLOSED |
| A2.2 | Source Adapter Framework | CLOSED |
| A2.3 | Transformation Rule Engine | CLOSED |
| A2.4 | Safety Policy Engine | READY FOR OWNER APPROVAL |
| A2.5 | Change Set Engine | CLOSED |
| A2.6 | Dry Run Engine | READY FOR OWNER REVIEW |
| A2.7 | Execution Engine | NOT STARTED |
| A2.8 | Scheduling Engine | NOT STARTED |
| A2.9 | AI Foundation | NOT STARTED |

### H3. A2 PostgreSQL Compose Path

The default production stack (`docker compose up -d`) does **not** include A2 PostgreSQL
services. PostgreSQL is introduced via an override file:

```
# Default production stack (no PostgreSQL)
docker compose up -d

# A2 stack (includes PostgreSQL)
docker compose -f docker-compose.yml -f docker-compose.a2.yml up -d
```

---

## G. Codex Review Protocol

Codex must re-verify PLATFORM_MAP against current code when any change affects:
- Architecture, routing, permissions, API contracts, workflow behavior, deployment, or major UI modules

### Drift detection checklist

| Section | Verify against |
|---|---|
| A — Auth layer (storage, flow) | `frontend/src/auth.tsx` |
| A — Routes + guards | `frontend/src/App.tsx` |
| A — Sidebar visibility | `frontend/src/components/Sidebar.tsx` |
| A — Python version | `Dockerfile` `FROM` line |
| A — Database path | `app/config.py` `_default_database_url` |
| B — Workflow tree | `app/main.py` endpoint list + permission deps |
| C — Permission tree | `app/main.py` `_enforce_permission`, `require_permission`, `require_admin` |
| C — API permission list | `app/main.py` each `@app.get`/`@app.post` decorator |
| D — Safety tree | Dry-run guards + apply guards in `app/main.py` |
| E — Roadmap | `docs/ROADMAP.md` |

### Rules
- If information cannot be verified from code, mark it UNKNOWN or remove it.
- Do not trust the map itself as a source of truth — code wins.
- After verifying, update the metadata header with the new commit hash and date.
