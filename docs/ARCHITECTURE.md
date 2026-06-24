# WooPrice Architecture Reference

---

## System Overview

```text
 External Sources
 ├── Nextcloud / OnlyOffice  (Excel price list via WebDAV — import/change source)
 └── WooCommerce REST API    (system of record for product prices)
        │
        ▼
 ┌──────────────────────────────────────┐
 │         React Frontend               │
 │  (Vite + TypeScript + Tailwind)      │
 │                                      │
 │  AppShell                            │
 │  ├── Sidebar (permission-aware nav)  │
 │  ├── Topbar (user / status)          │
 │  └── Pages                           │
 │      ├── Home (Dashboard)            │
 │      ├── Workspace  ← sync workflow  │
 │      ├── Products  ← product browser │
 │      ├── Analytics                   │
 │      ├── Audit History               │
 │      ├── Logs                        │
 │      ├── Settings                    │
 │      └── Admin                       │
 └──────────────────┬───────────────────┘
                    │ HTTP (JSON) + SSE
                    │ /api/*  (proxied in dev)
                    ▼
 ┌──────────────────────────────────────┐
 │         FastAPI Backend              │
 │         (Python 3.12, port 8000)     │
 │                                      │
 │  Auth layer (JWT + Nextcloud)        │
 │  Product cache (SQLite)              │
 │  Sync engine (preview → apply)       │
 │  Product Browser (filter/sort/page)  │
 │  Analytics engine                    │
 │  Writeback (Excel update)            │
 └──────────────┬───────────────────────┘
                │
       ┌────────┴──────────┐
       ▼                   ▼
  WooCommerce          Nextcloud
  (REST API)           (WebDAV)
  system of record     import source
```

---

## Strategic Direction

The following capabilities are planned but not yet implemented.
They inform architecture decisions made today.

**Change Set Platform:** All changes will eventually flow through a Change Set model
(draft → dry run → seller confirmation → schedule → execute → rollback). The current
sync workflow (source → preview → dry run → apply) will be re-expressed as a Change Set
producer.

A1 status: session-derived design only. No committed design document exists.
A1 is not an auditable artifact — it is background context for the A2 design task.

A2 architecture: committed to `docs/A2_ARCHITECTURE.md`. Covers all 7 layers (source
adapter, transformation rules, safety policy, Change Set engine, scheduling, channel
adapter, AI layer). Owner-approved for implementation.

A2.1 (Phase 1 — Canonical Product Model and PostgreSQL Foundation): **complete, Codex PASS.**
Additive only — existing app/ package untouched. Commits: `7e64e17`, `cfabd7a`.
See `docs/A2_MIGRATION_STRATEGY.md` for migration plan, schema, and cutover rules.

A2.2 (Phase 2 — Source Adapter Framework): next. Spec pending.

**A2 architecture scope** (must be designed before any of the following is implemented):
- Change Set execution engine and state machine
- Change Set scheduling (Now / Deferred / Low-traffic window)
- Scoped permissions (Brand / Category / Channel)
- Source adapter interface (Nextcloud → WooPrice field mapping)
- Channel adapter interface (WooCommerce → future channel abstraction)
- Transformation rules engine (cost+profit, cost×FX+profit, etc.)
- Configurable safety rules architecture (warn/block model)

**Multi-Source:** WooPrice is not locked to one spreadsheet provider. Nextcloud/OnlyOffice
XLSX via WebDAV is the only implemented source adapter. Future: Excel upload, MySQL,
custom DB, native pricing table. Source adapter interface to be designed in A2.

**Multi-Channel:** WooCommerce is the first channel. Future: Digikala, SnapShop, Shopify,
Magento, Amazon, custom CMS. Channel adapter interface to be designed in A2.

**Source Evolution:** The source moves from workflow driver to change event source.
Full source scanning is an anti-pattern to eliminate. Target: delta detection proposes
Change Sets for changed rows only; seller reviews and schedules.

See `docs/OWNER_DECISIONS.md` for authoritative rationale.

---

## Frontend Architecture

### Entry Point

`App.tsx` — mounts providers in order, then routes:

```text
BrowserRouter
  └── DirectionProvider        (document.documentElement.dir)
        └── AuthProvider       (JWT, /api/auth/me)
              └── Routes
                    └── AuthGuard (auth check + maintenance overlay)
                          └── AppShell (sidebar + topbar + <Outlet />)
                                ├── /home      → RequirePermission(can_access_site) → Home
                                ├── /workspace → RequirePermission(can_fetch) → Workspace
                                ├── /products  → RequirePermission(can_fetch) → Products
                                ├── /analytics → RequirePermission(can_access_site) → Analytics
                                ├── /audit     → RequirePermission(can_view_logs) → Audit
                                ├── /logs      → RequirePermission(can_view_logs) → Logs
                                ├── /settings  → RequirePermission(can_view_settings) → Settings
                                └── /admin     → RequirePermission(adminOnly) → Admin
```

### DirectionProvider (`direction.tsx`)

Sets `document.documentElement.dir` to `'ltr'` or `'rtl'` based on user preference.
All Tailwind utilities use logical properties (`ms-`, `me-`, `ps-`, `pe-`, `start-`, `end-`)
so RTL layout is automatic. No per-component direction logic.

### AuthProvider (`auth.tsx`)

- Reads JWT from `localStorage` key `wp_token`
- Fetches `/api/auth/me` on mount to validate token and load user profile
- Refreshes on `storage` events (cross-tab login/logout sync)
- Exposes `useAuth()` hook: `{ user, status, refreshUser, clearAuth, authFetch }`
- `authFetch` wraps `fetch` with `Authorization: Bearer <token>` header
- `status`: `'loading' | 'authenticated' | 'login_required' | 'permission_denied'`
- `RequirePermission` component: calls `effectiveHasPerm()` which mirrors backend
  `_enforce_permission` gate order (admin bypass → can_access_site gate → specific perm)
- `AuthContext` and `AuthContextValue` are exported for testing

### effectiveHasPerm (`utils/permissions.ts`)

The shared permission gate function. Must be used everywhere permission checks appear.

```text
effectiveHasPerm(user, perm)
  │
  ├── user is null → false
  ├── user.is_admin || user.is_super_admin → true (bypass all)
  ├── !user.permissions.can_access_site → false (global gate for regular users)
  └── user.permissions[perm] === true → true / false
```

This mirrors the backend `_enforce_permission` function exactly.
Any change to either side must be kept in sync.

### AppShell (`components/AppShell.tsx`)

Responsive layout: collapsible sidebar on desktop, off-canvas drawer on mobile.
Topbar shows connection status and user avatar. `<Outlet />` renders the active page.

### `useSSEStream` hook (`hooks/useSSEStream.ts`)

```text
useSSEStream(url, onMessage, onError)
  │
  ├── url === null → no-op (stream stopped)
  │
  └── url changes → new EventSource(url)
        │
        ├── generation guard (genRef) — stale callbacks dropped
        ├── onmessage → JSON.parse → onMessage(data)
        ├── parse error → close source → onError('parse_error')
        └── onerror → close source → onError('connection_lost')
```

Three independent instances run in Workspace simultaneously — cache SSE,
preview SSE, and apply SSE — sharing no state.

---

## Workspace Architecture (WS-A / WS-B / WS-C)

`Workspace.tsx` is a self-contained module with its own state machine, SSE wiring,
and all sub-components defined in the same file.

### WS-A — Shell and Cache Refresh

**Flows:**
- Light / Full / Deep Sync → `CACHE_START` → `cacheSseUrl` set → `useSSEStream` activates
- Check freshness → `GET /api/spreadsheet/meta` → `SHEET_LOADED`

### WS-B — Preview Stream and Product Table

**Preview SSE event sequence:**
```text
excel.running → excel.done
wc.running    → wc.done
calc.running  → calc.done
preview.done  (carries rows, summary, filter_stats, duplicate_warnings)
```

**Selection model:** `previewSelection` is a `Set<number>` of product IDs.
All selection mutations call `invalidateDryRun()`.

### WS-C — Dry Run / Apply / Writeback / Cancel / Inline / Rollback

**Apply is blocked when:**
- `dryRunPhase !== 'done'`
- `dryRunResult === null`
- `dry_run_status === 'blocked'`
- `dryRunInvalidated === true`

**Apply scope:** Always sends `dryRunResult.dry_run_scope` (server-computed normalized IDs),
not the raw UI selection. This is an invariant — never weaken it.

---

## Product Browser Architecture

`Products.tsx` — server-side filter/sort/paginate with the following features:

- Search, category multi-select, type filter, stock filter, price range filter
- Quality flag filters (no-price, stale, no-image)
- Sort: newest / oldest / name_asc / name_desc (all deterministic via secondary wc_id key)
- Page sizes: 10, 20, 50 (persisted in sessionStorage)
- Thumbnail lazy loading via `/api/products/{id}/thumb`
- Read-only view — no inline editing in Product Browser rows (planned: 7.7B)

Note: Inline price and stock editing via PUT /api/products/{id}/price and
PUT /api/products/{id}/stock exists in the **Workspace** (Workspace.tsx), not in Product Browser.

---

## SSE Architecture

### Token Delivery

`EventSource` cannot set HTTP headers. The JWT is appended as a query parameter:

```
/api/preview/stream?token=<jwt>
/api/sync/{job_id}/apply-stream?token=<jwt>&sid=N&sid=N...
/api/fetch/full?token=<jwt>
```

### Apply SSE (`/api/sync/{job_id}/apply-stream`)

```text
APPLY_START  →  applySseUrl set  →  EventSource opens
  │
  ├── type: 'start'                    →  APPLY_META (total count)
  ├── type: 'item'                     →  APPLY_ITEM (progress row)
  ├── type: 'done'                     →  APPLY_DONE (phase → 'done')
  │
  ├── type: 'stale_preview'            →  APPLY_ERROR (stalePreview: true) ← terminal
  ├── type: 'freshness_unverifiable'   →  APPLY_ERROR (stalePreview: true) ← terminal
  ├── type: 'dry_run_invalidated'      →  APPLY_ERROR + DRY_RUN_CLEARED_BY_SERVER ← terminal
  ├── type: 'error'                    →  APPLY_ERROR ← terminal
  │
  └── onerror                          →  APPLY_ERROR (connection_lost) ← no-op if already done
```

**First-write-wins rule:** `APPLY_ERROR` is a no-op when `applyPhase` is already `'error'` or `'done'`.
**No auto-retry:** `handleApplyError` dispatches `APPLY_ERROR` only. `useSSEStream` never reconnects after `onerror`.

---

## Critical Safety Invariants

These invariants must be maintained by all future changes.
Any change that weakens them is a HIGH or BLOCKER finding.

| # | Invariant | Implementation |
|---|---|---|
| 1 | Apply never runs on an invalidated dry run | `canRunApply` checks all four conditions |
| 2 | Selection change after dry run blocks apply | All selection actions call `invalidateDryRun()` |
| 3 | Inline edit after dry run blocks apply | `DRY_RUN_INVALIDATE` dispatched after successful save |
| 4 | Rollback after dry run blocks apply | `DRY_RUN_INVALIDATE` dispatched after rollback |
| 5 | Apply scope cannot differ from dry run scope | `startApply` uses `dryRunResult.dry_run_scope` |
| 6 | Server terminal events win over `onerror` | `APPLY_ERROR` no-op when `applyPhase === 'error'` or `'done'` |
| 7 | Apply SSE never auto-retries | `handleApplyError` dispatches error only, no reconnect |
| 8 | `dry_run_invalidated` clears dry run state | `DRY_RUN_CLEARED_BY_SERVER` resets phase to idle |
| 9 | Cache success never flips to failed | `CACHE_ERROR` no-op when `!cacheRunning` |
| 10 | Rollback is admin-only | `canRollback = isAdmin`, all rollback calls use `authFetch` |
| 11 | All write operations use JWT | `authFetch` adds `Authorization: Bearer` to every request |
| 12 | Per-component SSE isolation | Three independent `useSSEStream` instances; generation guard prevents cross-stream interference |
| 13 | can_access_site is global gate | `effectiveHasPerm` checks `can_access_site` before any specific permission for non-admin users |

---

## Permission Model

Backend enforces permissions on every authenticated request. Frontend checks are
convenience gates that mirror backend logic via `effectiveHasPerm`. Both sides must
be kept in sync.

| Field | Controls |
|---|---|
| `is_super_admin` | Determined by `SUPER_ADMIN_USERS` env var (not DB). Bypasses all permission checks. Access to maintenance mode, diagnostics. |
| `is_admin` | DB flag. Bypasses all `can_*` checks. Access to Admin page, rollback, emergency apply, deep sync, user management. |
| `can_access_site` | Global gate. All non-admin routes require this before any other check. Dashboard, Analytics pages. |
| `can_fetch` | Workspace, Product Browser, all fetch and preview endpoints. |
| `can_apply` | Dry Run, Apply, Writeback, Cancel sync job. |
| `can_edit_price` | Inline price edit (PUT /api/products/{id}/price). |
| `can_edit_stock` | Inline stock edit (PUT /api/products/{id}/stock). |
| `can_view_logs` | Audit History, Logs pages, audit log and job history endpoints. |
| `can_view_settings` | Settings page, alarm settings read. |
| `can_bulk_edit` | Planned (7.7A): bulk edit staging and apply. |

**Planned additions (future):**
- `can_browse_products` — split from `can_fetch` (read-only Product Browser)
- `can_dry_run` — split from `can_apply` (propose changes without applying)
- `can_schedule_changes` — deferred and windowed execution
- `can_approve_changes` — approval workflow (optional, non-default)
- `can_rollback` — split from `is_admin` (rollback without full admin)
- Scope dimension: `(permission, scope)` pairs replacing flat global flags

---

## Backend API Surface

### Auth

| Method | Path | Permission | Description |
|---|---|---|---|
| POST | /api/auth/login | public | Nextcloud verify → JWT issue |
| GET | /api/auth/me | JWT | Token validate + permission snapshot |

### Sync Engine

| Method | Path | Permission | Description |
|---|---|---|---|
| POST | /api/preview | can_fetch | Download XLSX, parse, create SyncJob |
| GET | /api/preview/stream | can_fetch + token= | SSE: classify rows vs cache |
| POST | /api/sync/{id}/dry-run | can_apply | Validate; set dry_run_status |
| POST | /api/sync/{id}/confirm | can_apply | Guard-check → confirm apply |
| GET | /api/sync/{id}/apply-stream | can_apply + token= | SSE: WC writes |
| DELETE | /api/sync/{id} | can_apply | Cancel preview-status job |

### Product Cache

| Method | Path | Permission | Description |
|---|---|---|---|
| GET | /api/products | can_fetch | Paginated, filtered, sorted |
| GET | /api/products/categories | can_fetch | Category list |
| GET | /api/products/{id}/lookup | can_fetch | Cache-first, WC fallback |
| GET | /api/products/{id}/thumb | public | JPEG thumbnail |
| PUT | /api/products/{id}/price | can_edit_price | Inline price override |
| PUT | /api/products/{id}/stock | can_edit_stock | Inline stock override |

### Fetch Engine

| Method | Path | Permission | Description |
|---|---|---|---|
| GET | /api/fetch/full | can_fetch | Full WC catalog sync (SSE) |
| GET | /api/fetch/light | can_fetch | Incremental sync (SSE) |
| GET | /api/fetch/deep-variations | is_admin | All variation pages (SSE) |

### Analytics and Audit

| Method | Path | Permission | Description |
|---|---|---|---|
| GET | /api/dashboard | can_access_site | Stat cards, chart |
| GET | /api/analytics | can_access_site | Seller issue lists |
| GET | /api/analytics/admin/* | is_admin | Admin overview/trends |
| GET | /api/audit-logs | can_view_logs | Action log |
| GET | /api/audit/history | can_view_logs | Change history |
| POST | /api/audit/undo | is_admin | Restore from history |
| GET | /api/jobs | can_view_logs | Job list |
| GET | /api/jobs/{id} | can_view_logs | Job detail |

### Admin

| Method | Path | Permission | Description |
|---|---|---|---|
| GET/POST/PATCH/DELETE | /api/admin/app-users* | is_admin | User CRUD |
| GET/POST | /api/admin/maintenance | is_super_admin | Maintenance mode |
| GET | /api/system/diagnostics | is_super_admin | System info |
| POST | /api/rollback/product/{id} | is_admin | Restore last change |
| POST | /api/rollback/job/{id} | is_admin | Restore all changes for job |

### Utilities

| Method | Path | Permission | Description |
|---|---|---|---|
| GET | /api/health | public | Service health |
| GET | /api/currency | public | IRR rates proxy (5-min cache) |
| GET | /api/categories | can_access_site | WC category list |
| GET | /api/settings | can_view_settings | Masked config |
| GET | /api/alarm-settings | can_view_settings | Thresholds |
| PUT | /api/alarm-settings | is_admin | Write thresholds |
| POST | /api/cache/clear | is_admin | Flush memory cache |
| POST | /api/products/cache-clear | is_admin | Flush DB cache |
| GET | /api/spreadsheet/meta | can_fetch | Sheet HEAD metadata |
| POST | /api/jobs/{id}/writeback | can_apply | Write results to sheet |
