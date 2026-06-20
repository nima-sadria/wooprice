# WooPrice React Migration Status

**As of:** 2026-06-20
**Stabilization commit:** `5a2eeff` (Phase 5 initial documentation)
**Codex remediation commit:** `377acae` (Phase 5 Codex findings resolved)
**Phase 6 stabilization commit:** pending (see below)
**Branch:** `main` (up to date with `origin/main`)
**Phase 5 status:** Complete
**Phase 6 status:** Implementation complete — pending Codex audit

---

## Completed Phases

| Phase | Label | Description | Audit | Commit |
|---|---|---|---|---|
| 1–3 | Core backend | FastAPI, product cache, sync engine, auth | Pre-React | — |
| Analytics Sprint A | Analytics | Product analytics page | Passed | `f4ab6cb` |
| Auth | Auth layer | `AuthProvider`, `useAuth`, `RequirePermission`, JWT login | Passed | (bundled) |
| Direction Layer | Global RTL/LTR | `DirectionProvider`, `document.documentElement.dir`, all Tailwind logical utilities | Passed | `585373e` |
| Phase 4c | Logs | Audit log + sync history page migration | Passed | `bf1d458` |
| WS-A | Workspace shell | Layout, header buttons, `CacheRefreshPanel`, `SpreadsheetStatus` | Passed | `4b38182` |
| WS-B | Preview stream | SSE progress steps, pre-fetch filters, category hierarchy, product table (read-only) | Passed | `4b38182` |
| WS-C | Workspace write operations | Dry Run, Apply (SSE), Writeback, Cancel, Inline price/stock edit, per-row Rollback | WS-C audit: H1 found and fixed; re-audit passed | `6bb8342` |
| WS-D | Integration audit | Full independent audit of WS-A/B/C; H-D1 and MD-2 found and fixed | Passed after remediation | `6bb8342` |

---

## Phase 5 — Planning (No Code Changes)

Phase 5 scope: build verification, serving architecture analysis, and documentation of proposed Phase 6 changes. No application code has been modified. No deployment has occurred.

| Gate | Result | Date |
|---|---|---|
| `npm run build` | PASS — 0 TS errors | 2026-06-20 |
| `pytest` | PASS — 47 passed | 2026-06-20 |
| Serving architecture analysis | Complete | 2026-06-20 |
| Cutover plan | Written — `docs/PHASE_5_CUTOVER_PLAN.md` | 2026-06-20 |
| Rollback checklist | Written — `docs/PHASE_5_CUTOVER_PLAN.md` | 2026-06-20 |
| Risk list (7 risks) | Written — `docs/PHASE_5_CUTOVER_PLAN.md` | 2026-06-20 |
| Agent path fix (`docs/agents/`) | Complete — `docs/docs/agents/` removed | 2026-06-20 |
| MD5 verification (`static/index.html`) | `55fdb8ccc3e26a9a2ad9b23b0f067791` confirmed | 2026-06-20 |
| Codex audit | Complete | 2026-06-20 |
| Project owner approval | Complete — Phase 6 authorized | 2026-06-20 |

## Phase 6 — Legacy Frontend Replacement

**Status:** Implementation complete — pending Codex audit

| Step | Result | Date |
|---|---|---|
| `.gitignore`: add `static/assets/` | Complete | 2026-06-20 |
| `Dockerfile`: two targeted COPY lines replacing one | Complete | 2026-06-20 |
| `app/main.py`: `/assets/` static mount added | Complete | 2026-06-20 |
| `app/main.py`: SPA catch-all route appended | Complete | 2026-06-20 |
| `static/index.html`: replaced with React SPA entry point | Complete | 2026-06-20 |
| `npm run build` | PASS — 0 TS errors | 2026-06-20 |
| `pytest` | PASS — 47 passed | 2026-06-20 |
| Stabilization commit | Pending | — |
| Codex audit | Pending | — |

### Build Output (Phase 6)

```
dist/index.html                  0.70 kB │ gzip:   0.46 kB
dist/assets/index-ZVdSgp51.css  25.41 kB │ gzip:   5.50 kB
dist/assets/index-Ba_i4MKP.js  452.21 kB │ gzip: 140.86 kB
```

Matches Phase 5 reference build exactly.

## Pending Phases

| Phase | Label | Description | Prerequisite |
|---|---|---|---|
| Phase 6 deployment | Production Cutover | `docker compose up -d --build` on production server | Codex audit passed; owner approval |

---

## Latest Audits

### WS-C Safety Audit (completed before `6bb8342`)

**Result:** Production Readiness — initially NO (H1 found); resolved to YES after fix.

| Severity | Finding | Status |
|---|---|---|
| HIGH | H1: `dry_run_invalidated` did not clear local dry run state — only set `dryRunInvalidated: true` | **RESOLVED** — `DRY_RUN_CLEARED_BY_SERVER` action added; `dryRunPhase → 'idle'`, `dryRunResult → null` |
| MEDIUM | M1: `CANCEL_ERROR` stores error in `writebackMsg` — field collision, cancel error detail never surfaced | Open |
| MEDIUM | M2: Apply button appears enabled after `applyPhase === 'error'` but `startApply` silently no-ops | Open |
| MEDIUM | M3: Header checkbox has no `indeterminate` state for partial page selection | Open |
| LOW | L1: `applyRunning` constant in `SyncActionBar` is dead code (always `false`) | Open |
| LOW | L2: Inline edit icon buttons use `group-hover` but parent `<tr>` lacks `group` Tailwind class | Open |
| LOW | L3: `rollbackAdvisory` banner has no dismiss button; persists until next `PREVIEW_START` | Open |
| LOW | L4: `applyItems` array accumulates with no cap; potential memory concern for very large catalogs | Open |

### WS-D Integration Audit (completed before `6bb8342`)

**Result:** Production Readiness — initially NO (H-D1 and MD-2 found); resolved to YES after fixes.

| Severity | Finding | Status |
|---|---|---|
| HIGH | H-D1: Terminal Apply SSE events (`stale_preview`, `freshness_unverifiable`, `dry_run_invalidated`) were overwritten by the subsequent `EventSource` `onerror` callback | **RESOLVED** — `APPLY_ERROR` now no-ops when `applyPhase === 'error'` (first-write-wins) |
| MEDIUM | MD-2: `CACHE_ERROR` fired after successful cache completion (normal SSE close triggers `onerror`), flipping panel to "Failed" | **RESOLVED** — `CACHE_ERROR` returns early when `!cacheRunning` |

**Final WS-D audit result:** No BLOCKERS. No HIGH. No MEDIUM. LOW items from WS-C unchanged.

---

### Phase 5 Documentation Audit

**Scope:** Documentation and governance only. No application code changed.

#### Round 1 findings (all resolved in commit `5a2eeff`)

| Severity | Finding | Status |
|---|---|---|
| MEDIUM | MD5 in `MIGRATION_STATUS.md` was stale (`893788...`) | **RESOLVED** — updated to `55fdb8ccc3e26a9a2ad9b23b0f067791` |
| MEDIUM | MD5 in `PHASE_5_CUTOVER_PLAN.md` used wrong audit value (`3d616d...`) | **RESOLVED** — updated to `55fdb8ccc3e26a9a2ad9b23b0f067791` |
| MEDIUM | Phase boundary contradiction — plan described cutover steps as Phase 5 actions | **RESOLVED** — all code changes clearly labelled "Proposed Phase 6 change — not implemented" |
| LOW | Agent files at wrong path `docs/docs/agents/` | **RESOLVED** — moved to `docs/agents/`; old directory deleted |
| LOW | `ROADMAP.md` listed Phase 5 goals as future in Upcoming Phases after goals were complete | **RESOLVED** — Phase 5 goals shown as achieved; only Phase 6 remains upcoming |
| LOW | `MIGRATION_STATUS.md` showed "audit remediation pending" after remediation complete | **RESOLVED** — status updated |
| LOW | `README.md` listed Phase 5 as simply "Pending" while planning was in progress | **RESOLVED** — updated to "Planning complete — awaiting Codex audit" |

#### Round 2 findings (resolved in commit `377acae`)

| Severity | Finding | Status |
|---|---|---|
| HIGH | H1: Working tree had uncommitted changes vs HEAD `5a2eeff` | **RESOLVED** — commit `377acae` created with all 5 modified files |
| MEDIUM | M1: `6bb8342` reference in PHASE_5_CUTOVER_PLAN.md line 10 not labelled as WS-D commit | **RESOLVED** — labelled "(WS-D stabilization commit)" |
| MEDIUM | M2: Git status not clean (same root as H1) | **RESOLVED** — same commit `377acae` |
| LOW | L1: `5a2eeff` missing from ROADMAP.md Stable Checkpoints | **RESOLVED** — added |
| LOW | L2: README.md structure tree missing `docs/PHASE_5_CUTOVER_PLAN.md` and `docs/agents/` | **RESOLVED** — both added |
| LOW | L3: AI_OPERATING_MANUAL.md "from docs/agents" reference ambiguous | **RESOLVED** — changed to "from the docs/agents/ directory" |

**Codex re-audit:** Pending
**Safe to proceed:** Pending

---

## Latest Stabilization Commits

```
commit 377acae
message: Phase 5: Codex audit remediation — close Phase 5

Fixes: H1/M2 (uncommitted state), M1 (WS-D label), L1 (stable checkpoints),
       L2 (README tree), L3 (agents path wording)
Backend changed: No
New endpoints:   No
Database:        No
static/index.html: Unchanged
Application code: Unchanged
```

```
commit 5a2eeff
message: Phase 5: stabilize cutover preparation documentation

Covers: Phase 5 documentation — cutover plan, rollback plan, risk list,
        agent path fix (docs/agents/), Phase boundary corrections.
Backend changed: No
New endpoints:   No
Database:        No
static/index.html: Unchanged
Application code: Unchanged
```

### Previous Stabilization Commit (WS-D)

```
commit 6bb8342
message: React Workspace WS-D stabilization audit fixes

Covers: WS-A + WS-B + WS-C + WS-D stable state
Fixes:  H-D1 (APPLY_ERROR first-write-wins guard)
        MD-2 (CACHE_ERROR no-op after successful completion)
        H1   (DRY_RUN_CLEARED_BY_SERVER clears dry run state)
Backend changed: No
New endpoints:   No
Database:        No
static/index.html: Unchanged
```

---

## Known Open Findings

These items are tracked here and will be addressed in a future cleanup pass. None block the current production readiness determination.

| ID | Component | Description |
|---|---|---|
| WS-C L1 | `SyncActionBar` | `applyRunning` constant is always `false` (dead code) — `SyncActionBar` only renders when `applyPhase !== 'streaming'` |
| WS-C L2 | `PreviewTable` | Inline edit icon buttons use `group-hover:opacity-100` but parent `<tr>` lacks the `group` Tailwind class; direct `hover:opacity-100` still works; "P"/"S" action buttons provide visible fallback |
| WS-C L3 | `PreviewTable` | `rollbackAdvisory` banner has no dismiss button; persists until next `PREVIEW_START` |
| WS-C L4 | `ApplyProgress` | `applyItems` array accumulates with no cap; for very large catalogs (1000+ products) this could consume significant memory during a long apply run |
| WS-C M1 | Reducer | `CANCEL_ERROR` stores error message in `writebackMsg` field instead of a dedicated `cancelError` field — cancel error detail is never shown in the UI |
| WS-C M2 | `SyncActionBar` | Apply button renders as enabled after `applyPhase === 'error'` but `startApply` silently no-ops; user sees a clickable button that does nothing |
| WS-C M3 | `PreviewTable` | Header checkbox has no `indeterminate` state for partial page selection; shows as unchecked when some-but-not-all page rows are selected |

---

## Build and Test Snapshot

```
npm run build  →  PASS  (0 TypeScript errors)
               →  dist/index.html 0.70 kB
               →  dist/assets/index-ZVdSgp51.css 25.41 kB
               →  dist/assets/index-Ba_i4MKP.js 452.21 kB
pytest         →  47 passed, 3 warnings
static/index.html MD5:  55fdb8ccc3e26a9a2ad9b23b0f067791  (verified 2026-06-20)
```

---

## State of the Two Frontends

| Frontend | Location | Status |
|---|---|---|
| Legacy | `static/index.html` | **Active in production** — served by FastAPI |
| React SPA | `frontend/src/` → `frontend/dist/` | **Development only** — not yet deployed; `dist/` is not committed |

The React build output (`frontend/dist/`) is excluded from git. It will be built and deployed as part of Phase 6 after Phase 5 is approved. The legacy `static/index.html` serves production until Phase 6 is complete.
