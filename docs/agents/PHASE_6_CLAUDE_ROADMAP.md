# Phase 6 — Claude Developer Roadmap

**Phase:** Phase 6 — Legacy Frontend Replacement
**Prerequisites:** Phase 5 approved; Codex audit of proposed changes passed; rollback plan approved
**Scope:** Implement the three code changes documented in `docs/PHASE_5_CUTOVER_PLAN.md`.
**No deployment. No production cutover.**

---

## Mandatory Reading (before starting)

Read these files in order:

1. `README.md`
2. `docs/WORKFLOW.md`
3. `docs/ARCHITECTURE.md`
4. `docs/MIGRATION_STATUS.md`
5. `docs/ROADMAP.md`
6. `docs/PHASE_5_CUTOVER_PLAN.md` — the source of truth for all Phase 6 code changes

---

## Phase 6 Scope

Implement exactly the three changes listed in `docs/PHASE_5_CUTOVER_PLAN.md` under **"Proposed Phase 6 Changes"**:

| # | File | Change |
|---|---|---|
| C1 | `Dockerfile` | Replace single `COPY --from=frontend-build /frontend/dist /app/static-react` with two targeted COPY lines |
| C2 | `app/main.py` | Insert `/assets/` static mount after the `/static` mount (line 365) |
| C3 | `app/main.py` | Append SPA catch-all route at the very end of the file |

An additional required change:

| # | File | Change |
|---|---|---|
| C4 | `static/index.html` | Replace legacy Adminator HTML with React SPA entry point (`frontend/dist/index.html`) |
| C5 | `.gitignore` | Add `static/assets/` so Vite bundles copied into `static/` are not committed to git |

**No other files require changes.** Backend logic is untouched. No new API endpoints. No database changes.

---

## Implementation Steps

### Step 1 — Apply Dockerfile change (C1)

Replace in `Dockerfile`:

```dockerfile
# Before
# Copy React build output alongside the existing static files.
# At Phase 5 cutover this COPY destination changes to /app/static/
# and static/index.html is removed. Until then both coexist.
COPY --from=frontend-build /frontend/dist /app/static-react
```

```dockerfile
# After
COPY --from=frontend-build /frontend/dist/assets /app/static/assets
COPY --from=frontend-build /frontend/dist/index.html /app/static/index.html
```

### Step 2 — Apply `/assets/` static mount (C2)

Insert in `app/main.py` after the `/static` mount:

```python
app.mount("/assets", StaticFiles(directory=str(static_dir / "assets")), name="react-assets")
```

### Step 3 — Apply SPA catch-all route (C3)

Append at the very end of `app/main.py`:

```python
# ── SPA catch-all ─────────────────────────────────────────────────────────────

@app.get("/{full_path:path}", response_class=HTMLResponse)
async def spa_fallback(full_path: str):
    return (static_dir / "index.html").read_text(encoding="utf-8")
```

**Must be the last route in the file.** FastAPI matches routes in order; the catch-all must come after all `/api/*` routes.

### Step 4 — Replace `static/index.html` (C4)

Copy `frontend/dist/index.html` (React SPA entry point) to `static/index.html`.

This replaces the legacy Adminator HTML (186 KB) with the React entry point (~700 bytes).

The existing `root()` route in `main.py` reads `static/index.html` — no route change required.

### Step 5 — Update `.gitignore` (C5)

Add `static/assets/` to `.gitignore` so the Vite-generated bundles copied into `static/assets/` during Docker build are not accidentally committed to git.

---

## Verification Gates

After all changes applied, verify:

| Gate | Required result |
|---|---|
| `npm run build` (in `frontend/`) | PASS — 0 TypeScript errors |
| `pytest` | PASS — 47 passed |

Both gates must pass before the stabilization commit.

---

## Stabilization Commit

Follow `docs/agents/STABILIZATION_COMMIT.md`.

Commit message format:

```
Phase 6: Legacy frontend replacement — React SPA cutover

Changes:
- Dockerfile: COPY targets updated (dist/assets → static/assets; dist/index.html → static/index.html)
- app/main.py: /assets/ static mount added; SPA catch-all route appended
- static/index.html: replaced Adminator legacy HTML with React SPA entry point
- .gitignore: static/assets/ excluded from git

Backend changed: No
New endpoints:   No
Database:        No
```

---

## After Stabilization Commit

Stop. Do not deploy. Do not start Phase 7 or any next step.

Submit the commit hash and the required report (see `docs/agents/CLAUDE_DEVELOPER.md`) for Codex audit.

---

## Required Report (per CLAUDE_DEVELOPER.md)

After stabilization commit, provide:

1. **What changed** — four file changes as listed above
2. **Files changed** — `.gitignore`, `Dockerfile`, `app/main.py`, `static/index.html`
3. **Backend files changed?** — `app/main.py` (serving only — two new route/mount entries; no business logic changed)
4. **New endpoints?** — `/assets/*` static mount (new); `/{full_path:path}` SPA catch-all (new)
5. **Database changes?** — No
6. **Build result** — record actual output
7. **Test result** — record actual output
8. **Known limitations** — see Open Findings in `docs/MIGRATION_STATUS.md`
9. **Recommended next step** — Codex audit of Phase 6 stabilization commit
