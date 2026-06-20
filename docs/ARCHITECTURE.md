# WooPrice Architecture Reference

---

## System Overview

```text
 Nextcloud / OnlyOffice
 (Excel price list via WebDAV)
        │
        ▼
 ┌──────────────────────────────────┐
 │         React Frontend           │
 │  (Vite + TypeScript + Tailwind)  │
 │                                  │
 │  AppShell                        │
 │  ├── Sidebar (navigation)        │
 │  ├── Topbar (user / status)      │
 │  └── Pages                       │
 │      ├── Workspace  ← primary    │
 │      ├── Analytics               │
 │      ├── Logs                    │
 │      ├── Home                    │
 │      ├── Settings                │
 │      └── Admin                   │
 └──────────────────┬───────────────┘
                    │ HTTP (JSON) + SSE
                    │ /api/*  (proxied in dev)
                    ▼
 ┌──────────────────────────────────┐
 │         FastAPI Backend          │
 │         (Python, port 8000)      │
 │                                  │
 │  Auth layer (JWT + Nextcloud)    │
 │  Product cache (SQLite)          │
 │  Sync engine (preview → apply)   │
 │  Writeback (Excel update)        │
 └──────────────┬───────────────────┘
                │
       ┌────────┴────────┐
       ▼                 ▼
  WooCommerce        Nextcloud
  (REST API)         (WebDAV)
```

---

## Frontend Architecture

### Entry Point

`App.tsx` — mounts providers in order, then routes:

```text
BrowserRouter
  └── DirectionProvider        (document.documentElement.dir)
        └── AuthProvider       (JWT, /api/auth/me)
              └── Routes
                    └── AppShell (sidebar + topbar + <Outlet />)
                          ├── /home          → Home
                          ├── /workspace     → Workspace
                          ├── /analytics     → RequirePermission(can_access_site) → Analytics
                          ├── /logs          → RequirePermission(can_view_logs) → Logs
                          ├── /settings      → Settings
                          └── /admin         → RequirePermission(adminOnly) → Admin
```

### DirectionProvider (`direction.tsx`)

Sets `document.documentElement.dir` to `'ltr'` or `'rtl'` based on user preference. All Tailwind utilities in the project use logical properties (`ms-`, `me-`, `ps-`, `pe-`, `start-`, `end-`) so RTL layout is automatic. No per-component direction logic.

### AuthProvider (`auth.tsx`)

- Reads JWT from `localStorage` key `wp_token`
- Fetches `/api/auth/me` on mount to validate token and load user profile
- Exposes `useAuth()` hook: `{ user, status, authFetch, login, logout }`
- `authFetch` wraps `fetch` with `Authorization: Bearer <token>` header
- `status`: `'loading' | 'authenticated' | 'unauthenticated' | 'error'`
- `RequirePermission` component renders children only when the named permission is present on `user.permissions`, or when `adminOnly` and `user.is_admin === true`

### AppShell (`components/AppShell.tsx`)

Responsive layout: collapsible sidebar on desktop, off-canvas drawer on mobile. Topbar shows connection status and user avatar. `<Outlet />` renders the active page.

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

The generation counter increments on every new URL, unmount, or error. Any callback that sees a different generation is silently dropped. This prevents race conditions when the URL changes rapidly (e.g., multiple cache refresh attempts).

Three independent instances run in Workspace simultaneously — one each for cache SSE, preview SSE, and apply SSE — sharing no state.

---

## Workspace Architecture (WS-A / WS-B / WS-C)

`Workspace.tsx` is a self-contained module with its own state machine, SSE wiring, and all sub-components defined in the same file.

### WS-A — Shell and Cache Refresh

**Components:** page header (action buttons), `SpreadsheetStatus`, `CacheRefreshPanel`

**State managed:**
- `cacheOp`, `cacheRunning`, `cacheSseUrl`, `cacheLog` — cache refresh state
- `sheetLoading`, `sheetMeta`, `sheetError`, `sheetPolling` — spreadsheet freshness check

**Flows:**
- Light / Full / Deep Sync → `CACHE_START` → `cacheSseUrl` set → `useSSEStream` activates → `CACHE_LOG` / `CACHE_DONE` / `CACHE_ERROR`
- Check freshness → `GET /api/spreadsheet/meta` → `SHEET_LOADED`
- Wait for update → polling loop every 2 s, up to 15 ticks, stops on ETag change

### WS-B — Preview Stream and Product Table

**Components:** `PreFetchFilters`, `PreviewSteps`, `FilterStatsBar`, `DuplicateWarningBox`, `PreviewTable`

**State managed:**
- `previewPhase`, `previewSseUrl`, `previewError`, step indicators — stream progress
- `previewRows`, `previewSummary`, `filterStats`, `duplicateWarnings` — result data
- `previewPage`, `previewSelection` — pagination and row selection
- `filterSearch`, `filterCatIds`, `categories` — pre-fetch filters

**Preview SSE event sequence:**
```text
excel.running → excel.done
wc.running    → wc.done
calc.running  → calc.done
preview.done  (carries rows, summary, filter_stats, duplicate_warnings)
```

**Selection model:** `previewSelection` is a `Set<number>` of product IDs. All mutation actions (`PREVIEW_TOGGLE`, `PREVIEW_SELECT_PAGE`, `PREVIEW_DESELECT_PAGE`, `PREVIEW_CLEAR_SELECTION`) call `invalidateDryRun()` which sets `dryRunInvalidated: true` if a dry run is complete.

### WS-C — Dry Run / Apply / Writeback / Cancel / Inline / Rollback

**Components:** `SyncActionBar`, `DryRunPanel`, `ApplyProgress`

**State managed:**
- `dryRunPhase`, `dryRunError`, `dryRunResult`, `dryRunInvalidated`
- `applyPhase`, `applySseUrl`, `applyError`, `applyStalePreview`, `applyTotal`, `applyCompleted`, `applyItems`, `applyDone`
- `writebackPhase`, `writebackMsg`
- `cancelPhase`, `jobCancelled`
- `rollbackAdvisory`

---

## SSE Architecture

### Token Delivery

`EventSource` cannot set HTTP headers. The JWT is appended as a query parameter:

```
/api/preview/stream?token=<jwt>
/api/sync/{job_id}/apply-stream?token=<jwt>&sid=N&sid=N...
/api/fetch/full?token=<jwt>
```

The token is read from `localStorage` at the moment the URL is constructed (not at mount time), ensuring it reflects any token refresh.

### Cache SSE (`/api/fetch/{full|light|deep-variations}`)

```text
CACHE_START  →  cacheSseUrl set  →  EventSource opens
  │
  ├── data: { step, status, msg }  →  CACHE_LOG
  ├── data: { step: 'done' }       →  CACHE_LOG + CACHE_DONE  (cacheRunning → false)
  ├── data: { status: 'error' }    →  CACHE_LOG + CACHE_ERROR (guard: if !cacheRunning → no-op)
  └── onerror                      →  CACHE_ERROR             (guard: if !cacheRunning → no-op)
```

The `!cacheRunning` guard (MD-2 fix) prevents a false "Failed" state after a normal SSE close following `CACHE_DONE`.

### Preview SSE (`/api/preview/stream`)

```text
PREVIEW_START  →  WS_C_RESET applied  →  previewSseUrl set  →  EventSource opens
  │
  ├── excel/wc/calc step events  →  PREVIEW_STEP
  ├── duplicate_warnings event   →  PREVIEW_DUP_WARNING
  ├── preview.done               →  PREVIEW_READY  (phase → 'ready', rows + summary loaded)
  ├── status: 'error'            →  PREVIEW_ERROR
  └── onerror                    →  PREVIEW_ERROR
```

`WS_C_RESET` is a constant partial state object applied atomically at `PREVIEW_START` that clears all WS-C fields (dry run, apply, writeback, cancel, rollback) to their idle defaults.

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
  └── onerror                          →  APPLY_ERROR (connection_lost) ← no-op if already error/done
```

**First-write-wins rule (H-D1 fix):** `APPLY_ERROR` is a no-op when `applyPhase` is already `'error'` or `'done'`. The first terminal server event always wins over a subsequent `onerror`.

**No auto-retry:** `handleApplyError` dispatches `APPLY_ERROR` only. `useSSEStream` does not reconnect after `onerror`.

### Scope Pinning

Apply always sends `dryRunResult.dry_run_scope` (the server-computed and stored IDs from the dry run), not the raw `previewSelection`. This ensures the exact scope validated during dry run is the scope applied — even when selection was empty at dry-run time (server normalizes to all changed items).

---

## State Machine Overview

```text
Workspace state machine (simplified)

previewPhase:  idle → streaming → ready | error
dryRunPhase:   idle → running → done | failed   (reset to idle by DRY_RUN_CLEARED_BY_SERVER)
applyPhase:    idle → streaming → done | error

Transitions that reset all WS-C state:
  PREVIEW_START → applies WS_C_RESET (dry run, apply, writeback, cancel all → idle)

Transitions that invalidate dry run (set dryRunInvalidated: true):
  PREVIEW_TOGGLE, PREVIEW_SELECT_PAGE, PREVIEW_DESELECT_PAGE, PREVIEW_CLEAR_SELECTION
  DRY_RUN_INVALIDATE  (from inline price edit, inline stock edit, rollback)

Transitions that clear dry run state entirely:
  DRY_RUN_CLEARED_BY_SERVER  (from server dry_run_invalidated event during apply)
    → dryRunPhase: 'idle', dryRunResult: null, dryRunInvalidated: false

Apply is blocked when:
  dryRunPhase !== 'done'     OR
  dryRunResult === null      OR
  dry_run_status === 'blocked' OR
  dryRunInvalidated === true

SyncActionBar renders only when:
  previewPhase === 'ready' AND canApply AND applyPhase !== 'streaming'
```

---

## Critical Safety Invariants

These invariants must be maintained by all future changes. Any change that weakens them is a HIGH or BLOCKER finding.

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

---

## Permission Model

Permissions are carried in the JWT and verified at `/api/auth/me`. Frontend checks are convenience gates; backend enforces all permissions independently.

| Field | Controls |
|---|---|
| `is_admin` | Deep Sync button, rollback buttons, Admin page, overrides all `can_*` checks |
| `can_fetch` | Light Refresh, Full Refresh, Fetch Preview button, Pre-Fetch Filters |
| `can_apply` | SyncActionBar (Dry Run, Apply, Cancel, Writeback) |
| `can_edit_price` | Inline price edit (P button and pencil icon) |
| `can_edit_stock` | Inline stock edit (S button and pencil icon) |
| `can_access_site` | Analytics page access |
| `can_view_logs` | Logs page access |

---

## Backend API Surface (WS-C Relevant)

| Method | Path | Permission | Description |
|---|---|---|---|
| `POST` | `/api/sync/{job_id}/dry-run` | `can_apply` | Run validation; returns `dry_run_scope`, `dry_run_status`, `critical_errors`, `warnings` |
| `GET` | `/api/sync/{job_id}/apply-stream` | `can_apply` + `token=` | SSE apply stream; events: `start`, `item`, `done`, `error`, `stale_preview`, `freshness_unverifiable`, `dry_run_invalidated` |
| `POST` | `/api/jobs/{job_id}/writeback` | `can_apply` | Write confirmed prices back to spreadsheet |
| `DELETE` | `/api/sync/{job_id}` | `can_apply` | Cancel a preview-status job |
| `POST` | `/api/rollback/product/{pid}` | `is_admin` | Rollback product to last known price/stock |
| `PUT` | `/api/products/{pid}/price` | `can_edit_price` | Inline price override; invalidates dry runs server-side |
| `PUT` | `/api/products/{pid}/stock` | `can_edit_stock` | Inline stock override; invalidates dry runs server-side |
