# Phase 5 — Production Cutover Plan

**Scope:** Planning and preparation only.
**No code changes are implemented in Phase 5.**
**All proposed code changes below are labelled "Proposed Phase 6 change — not implemented."**

**Status:** Planning complete — ready for Codex audit
**Date:** 2026-06-20
**Closure date:** 2026-06-20
**Prerequisite met:** WS-D audit passed (WS-D stabilization commit `6bb8342`); Phase 5 documentation stabilization commit `5a2eeff`
**Verified `static/index.html` MD5:** `55fdb8ccc3e26a9a2ad9b23b0f067791`

---

## Phase 5 Scope

Phase 5 produces:

1. Build and test verification
2. Serving architecture analysis
3. Proposed Phase 6 code changes (documented, not implemented)
4. Pre-cutover checklist (for Phase 6)
5. Cutover checklist (for Phase 6)
6. Smoke test checklist (for Phase 6)
7. Rollback checklist (for Phase 6)
8. Risk list

Phase 5 does **not** include:
- Any changes to application code
- Any changes to `static/index.html`
- Deployment to production
- Production cutover

---

## Pre-flight Verification

Both gates verified on 2026-06-20:

| Gate | Result |
|---|---|
| `npm run build` | PASS — 0 TypeScript errors |
| `pytest` | PASS — 47 passed, 3 warnings (all pre-existing deprecations) |

### Build Output (recorded for Phase 6 reference)

```
dist/index.html                  0.70 kB │ gzip:   0.46 kB
dist/assets/index-ZVdSgp51.css  25.41 kB │ gzip:   5.50 kB
dist/assets/index-Ba_i4MKP.js  452.21 kB │ gzip: 140.86 kB
```

Build notice (non-blocking): four font file references (`/static/fonts/IRANYekan*`) could not be resolved at build time. This is expected — fonts are served at runtime from FastAPI's `/static/` mount, not bundled into the Vite output.

---

## Current Serving Architecture

These are the **active** routes as of Phase 5. No changes have been made.

### `app/main.py` serving (lines 364–365, 1402–1404)

```python
static_dir = Path(__file__).parent.parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

@app.get("/", response_class=HTMLResponse)
async def root():
    return (static_dir / "index.html").read_text(encoding="utf-8")
```

### Route map (current)

| Path | Handler | Source |
|---|---|---|
| `GET /` | `root()` | `static/index.html` — legacy Adminator HTML (186 KB) |
| `GET /static/fonts/*` | StaticFiles | `static/fonts/` — 4 IRANYekan font files |
| `GET /static/icons/*` | StaticFiles | `static/icons/` — 10 PNG icon files |
| `GET /static/adminator/*` | StaticFiles | `static/adminator/` — legacy JS/CSS framework |
| `GET /api/*` | FastAPI routes | Python handlers |
| Any other path | **404** | No SPA catch-all exists |

---

## Required Phase 6 Serving Architecture

The React SPA uses BrowserRouter. Direct navigation to `/workspace`, `/analytics`, etc. returns 404 today. Phase 6 must deliver:

| Path | Handler | Source |
|---|---|---|
| `GET /` | `root()` — unchanged | React `dist/index.html` (replaces legacy) |
| `GET /home`, `/workspace`, `/analytics`, `/logs`, `/settings`, `/admin` | SPA catch-all | React `dist/index.html` |
| `GET /assets/*.js` | New `/assets/` static mount | `static/assets/` (Vite JS bundle) |
| `GET /assets/*.css` | New `/assets/` static mount | `static/assets/` (Vite CSS bundle) |
| `GET /static/fonts/*` | Existing `/static/` mount | `static/fonts/` — **preserved, required** |
| `GET /static/icons/*` | Existing `/static/` mount | `static/icons/` — **preserved, required** |
| `GET /api/*` | FastAPI routes | Unchanged |

The `/static/fonts/` and `/static/icons/` paths must be preserved. The React app references fonts at `/static/fonts/IRANYekan*.woff*` at runtime (confirmed by build warning).

---

## Proposed Phase 6 Changes — NOT IMPLEMENTED

> These are plans for Phase 6. They have not been written to any file. No application code has been modified in Phase 5.

### Proposed Phase 6 change — Dockerfile

Replace one COPY line with two targeted lines.

**Before:**
```dockerfile
# Copy React build output alongside the existing static files.
# At Phase 5 cutover this COPY destination changes to /app/static/
# and static/index.html is removed. Until then both coexist.
COPY --from=frontend-build /frontend/dist /app/static-react
```

**After:**
```dockerfile
# React SPA assets (JS/CSS bundles) — served by the /assets/ mount added to main.py.
# Docker layer ordering: COPY . . already placed fonts/ and icons/ in /app/static/;
# these two COPY instructions overlay only the new React files without disturbing them.
COPY --from=frontend-build /frontend/dist/assets /app/static/assets
COPY --from=frontend-build /frontend/dist/index.html /app/static/index.html
```

**Why this approach:**
- `COPY . .` (earlier in the Dockerfile) already copies `static/fonts/` and `static/icons/` into the image
- `dist/assets/` → `static/assets/` adds Vite bundles as a new subdirectory (no conflicts)
- `dist/index.html` → `static/index.html` replaces the legacy Adminator HTML with the React entry
- The existing `root()` route in `main.py` already reads `static/index.html` — no change required there
- `static/adminator/` remains in the image but is no longer reachable once the new `/assets/` mount is active; it can be removed in a follow-up cleanup

### Proposed Phase 6 change — `app/main.py`: `/assets/` mount

Insert after line 365 (the `/static` mount):

```python
# React SPA assets (Vite build output — JS and CSS bundles)
app.mount("/assets", StaticFiles(directory=str(static_dir / "assets")), name="react-assets")
```

### Proposed Phase 6 change — `app/main.py`: SPA catch-all route

Append at the very end of the file, after all other route definitions:

```python
# SPA catch-all: serve React index.html for all client-side routes.
# Must be defined LAST — FastAPI's explicit /api/* routes always take precedence.
# StaticFiles mounts (/static, /assets) also take precedence over @app.get() routes.
@app.get("/{full_path:path}", response_class=HTMLResponse)
async def spa_fallback(full_path: str):
    return (static_dir / "index.html").read_text(encoding="utf-8")
```

**No other files require changes for Phase 6.** Backend logic is untouched. No new API endpoints. No database changes.

---

## Risk List

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | `/assets/` mount missing or misconfigured — React JS/CSS bundles return 404 | Medium | HIGH — app blank-screens | Smoke test S5 catches this immediately |
| R2 | SPA catch-all omitted or not at end of file — direct URL navigation returns 404 | Medium | HIGH — workspace/analytics unreachable | Smoke tests S3, S4 catch this |
| R3 | Font files not preserved — IRANYekan fails to load, RTL text breaks | Low | MEDIUM — visible text rendering issue | Docker layer ordering preserves fonts; smoke test S6 catches it |
| R4 | Stale browser cache — user sees mix of old Adminator HTML and new React assets | Low | MEDIUM — broken layout | Vite fingerprints asset filenames; full-page reload after cutover |
| R5 | Upstream Nginx `try_files` intercepts SPA routes before FastAPI catch-all | Low | HIGH — all SPA routes 404 | Review Nginx config before cutover; test SPA routing on staging |
| R6 | Docker build fails (Node unavailable or npm error) | Low | LOW — deploy blocked, rollback trivial | Dockerfile already tested in CI-equivalent (local build passes) |
| R7 | Legacy `static/index.html` MD5 drifts from known value before cutover | Low | LOW — detection only | Verify MD5 as pre-cutover checklist step P3 |

---

## Pre-Cutover Checklist

> To be executed by the operator at the start of Phase 6. Phase 5 does not execute these steps.

- [ ] **P1** — This Phase 5 plan reviewed and approved by project owner
- [ ] **P2** — Codex audit of proposed Phase 6 code changes passed (no BLOCKER or HIGH)
- [ ] **P3** — Verify `static/index.html` MD5 = `55fdb8ccc3e26a9a2ad9b23b0f067791` (confirms legacy file unchanged; verified 2026-06-20)
- [ ] **P4** — Git status is clean on `main`; no uncommitted changes
- [ ] **P5** — `npm run build` produces clean output (0 TS errors) immediately before deploy
- [ ] **P6** — `pytest` reports 47 passed immediately before deploy
- [ ] **P7** — Docker daemon is running; `docker compose ps` shows app healthy
- [ ] **P8** — Rollback procedure reviewed and understood by operator
- [ ] **P9** — Maintenance window communicated to all active users (if any)
- [ ] **P10** — If an Nginx reverse proxy sits upstream: verify it does not intercept SPA routes (Risk R5)

---

## Cutover Checklist

> Phase 6 steps. Execute in order. Stop and roll back on any failure.

- [ ] **C1** — Apply proposed Dockerfile change (two COPY lines replacing one)
- [ ] **C2** — Apply proposed `/assets/` static mount to `app/main.py`
- [ ] **C3** — Apply proposed SPA catch-all route to `app/main.py` (end of file only)
- [ ] **C4** — `npm run build` — must pass with 0 errors
- [ ] **C5** — `pytest` — must report 47 passed
- [ ] **C6** — Create Phase 6 stabilization commit (per `docs/agents/STABILIZATION_COMMIT.md`)
- [ ] **C7** — `docker compose up -d --build` on production server
- [ ] **C8** — Confirm Docker build log shows React build step completing without error
- [ ] **C9** — `docker compose ps` — confirm container is running

---

## Smoke Test Checklist

> Verify after C9 completes. Fail any item → begin rollback immediately.

- [ ] **S1** — `GET /` — React login page loads (not Adminator HTML; check page title = "WooPrice" with blue `W` favicon)
- [ ] **S2** — Login with valid credentials — JWT issued, app navigates to `/home`
- [ ] **S3** — Navigate directly to `https://woo.softpple.business/workspace` — Workspace page loads (SPA routing works)
- [ ] **S4** — Navigate directly to `https://woo.softpple.business/analytics` — Analytics page loads
- [ ] **S5** — DevTools Network: `GET /assets/index-*.js` → 200 OK (React bundle served)
- [ ] **S6** — DevTools Network: `GET /static/fonts/IRANYekanXVF.woff2` → 200 OK (fonts preserved)
- [ ] **S7** — DevTools Network: no 404 errors on initial page load
- [ ] **S8** — Workspace: trigger a Light Refresh — SSE stream runs and completes without error
- [ ] **S9** — Workspace: Fetch Preview — product table populates
- [ ] **S10** — `GET https://woo.softpple.business/api/health` → `{"status": "ok"}`
- [ ] **S11** — `docker compose logs -f` — no ERROR-level entries from startup

---

## Rollback Checklist

> Execute if any smoke test fails or errors appear in logs after C9.

**Preferred rollback — revert the entire Phase 6 commit atomically:**

```bash
git revert 1969a1c
# commit message will be pre-filled; save and close editor
docker compose up -d --build
```

This single command restores `.gitignore`, `Dockerfile`, `app/main.py`, and `static/index.html` to their pre-Phase-6 state in one operation.

**Manual rollback — if git revert is not available:**

- [ ] **RB1** — Restore `static/index.html` from git history:
  ```bash
  git checkout 377acae -- static/index.html
  ```
  This step is **mandatory** — without it the legacy Adminator UI will not be served.
- [ ] **RB2** — Revert the Dockerfile change (restore single COPY line to `/app/static-react`)
- [ ] **RB3** — Remove the `/assets/` static mount from `app/main.py`
- [ ] **RB4** — Remove the SPA catch-all route from `app/main.py`
- [ ] **RB5** — Update `.gitignore` to remove `static/assets/` entry
- [ ] **RB6** — `docker compose up -d --build`
- [ ] **RB7** — Verify: `GET /` returns Adminator HTML (legacy styling, legacy page title)
- [ ] **RB8** — Verify: `docker compose logs -f` — no errors
- [ ] **RB9** — Document what failed and open a remediation task

**Estimated rollback time:** ~3 minutes (git revert + one Docker rebuild).

**Git safety:** The legacy `static/index.html` is preserved at commit `377acae`. Both rollback paths above explicitly restore it. The React build output (`frontend/dist/`) is never committed (`.gitignore` confirmed).

---

## Deployment Strategy

| Item | Value |
|---|---|
| Production URL | `https://woo.softpple.business` |
| Docker host port | `8000` |
| Build method | Multi-stage Dockerfile (Stage 1: Node 20-alpine; Stage 2: Python 3.12-slim) |
| Deploy command | `docker compose up -d --build` |
| Expected downtime | ~5 seconds (Uvicorn restart) |

Strategy: **in-place Docker image rebuild + container restart.** No blue-green deployment. Acceptable because the backend is unchanged and rollback takes < 3 minutes.

---

## Open Items Before Phase 6 May Begin

| Item | Owner | Status |
|---|---|---|
| Codex audit of Phase 6 proposed code changes | Codex | Pending |
| Nginx upstream config review (Risk R5) | Project owner | Pending |
| Maintenance window scheduling | Project owner | Pending |
| Project owner approval of this Phase 5 plan | Project owner | Pending |
