# WooPrice Development and Audit Workflow

This document defines the mandatory process for all development, audit, and release work on the WooPrice frontend migration. It applies to human developers and AI agents alike.

The complete 9-step governance workflow (including CHAT2 specification, Independent Review, Phase Completion Report, CHAT2 Architecture/Governance review, and Owner approval) is defined in `.claude/WORKFLOW.md`. That document takes precedence for all WooPrice phases.

---

## Project Lifecycle

Every feature phase follows this sequence without exception:

```text
Claude (Developer)
        │
        ▼
  Implementation
  (code only — no commit)
        │
        ▼
  Build check
  npm run build  →  MUST PASS
        │
        ▼
  Backend tests
  pytest         →  MUST PASS (all tests)
        │
        ▼
  Independent Review
  (Claude reviews own implementation — see .claude/WORKFLOW.md Step 3)
        │
        ▼
  Review result: BLOCKERS / HIGH / MEDIUM / LOW
        │
        ├─ Any BLOCKER or HIGH found?
        │       │
        │       ├─ YES → Stop. No merge. No deploy. No next phase.
        │       │         Produce remediation plan.
        │       │         Fix only the flagged items.
        │       │         Re-run build and tests after fix.
        │       │
        │       └─ NO  → Phase Completion Report → CHAT2 Review → Owner Approval
        │
        ▼
  CHAT2 Architecture and Governance Review
  (CHAT2 returns APPROVE / REVISE / HOLD — see .claude/WORKFLOW.md Step 6)
        │
        ▼
  Owner Approval
  (explicit: "approved", "proceed", or "safe to proceed: YES")
        │
        ▼
  Stabilization Commit
  (single commit, one message, exact file list declared)
        │
        ▼
  Next Phase begins
```

No phase is considered complete until all six gates pass:

1. `npm run build` — PASS
2. `pytest` — PASS (all tests)
3. Independent Review complete (Step 3 of `.claude/WORKFLOW.md`)
4. No BLOCKER or HIGH findings
5. CHAT2 review: APPROVE
6. Stabilization commit created

---

## Risk Classification

### HIGH RISK — Mandatory formal audit before approval

These components touch WooCommerce write operations, scope isolation, or financial data. Any defect here can silently corrupt prices or apply unvalidated changes.

| Component | Risk |
|---|---|
| Workspace / Dry Run | Scope validation, critical error blocking |
| Workspace / Apply | Irreversible WooCommerce price writes |
| Workspace / Rollback | Overwrites live WooCommerce data |
| Apply SSE lifecycle | Disconnect handling, no-retry policy |
| Dry Run invalidation | Must block Apply on any state change |

### MEDIUM RISK — Review required, no standalone audit

| Component | Risk |
|---|---|
| Auth / JWT | Token revocation, permission checks |
| Settings | User configuration changes |
| Permission enforcement | `can_apply`, `can_edit_price`, `can_edit_stock`, `is_admin` |

### LOW RISK — Standard code review only

| Component | Risk |
|---|---|
| Analytics | Read-only display |
| Logs | Read-only audit history |
| Home / Dashboard | Static display |
| Direction Layer | Visual only, no data |

---

## Audit Requirements

Every formal review must be independent (performed after implementation is complete, not during). The review must cover all items in the phase scope, not just changed files.

The mandatory reviewer is CHAT2 (Step 6 of `.claude/WORKFLOW.md`). Codex may optionally be engaged by Owner decision as an additional external auditor on high-risk phases; it is not a required step.

### Required Report Format

```
BLOCKERS
<list or "None">

HIGH
<list or "None">

MEDIUM
<list or "None">

LOW
<list or "None">

Production Readiness: YES / NO
Safe to proceed: YES / NO
```

### Mandatory Audit Sections for Workspace Phases

1. Apply trigger safety — `canRunApply` logic, scope pinning
2. Dry Run invalidation — all paths that set `dryRunInvalidated`
3. SSE no-retry policy — Apply disconnect must not auto-retry
4. Terminal event handling — `stale_preview`, `freshness_unverifiable`, `dry_run_invalidated` must win over `onerror`
5. Selection tracking — all selection change paths invalidate dry run
6. Permission enforcement — all write operations behind `authFetch` with JWT
7. Rollback safety — admin-only, invalidates dry run
8. Reducer correctness — no impossible state transitions
9. Regression check — Analytics / Logs / RTL unaffected; build and tests pass

### Blocking Rule

> **If any BLOCKER or HIGH finding exists: no merge, no deploy, no next phase.**

MEDIUM and LOW findings are documented, tracked in [MIGRATION_STATUS.md](MIGRATION_STATUS.md), and addressed in a future cleanup pass. They do not block the current phase.

---

## Commit Policy

### When to commit

Only after all five completion gates pass (see Project Lifecycle above).

### What to stage

Stage only the files that were intentionally changed. Never use `git add -A` or `git add .`. Verify with `git diff --cached --stat` before committing.

**Preferred workflow:**

```bash
git add frontend/src/pages/Workspace.tsx docs/WORKFLOW.md README.md
git diff --cached --stat
git commit -m "..."
```

Files that must never be committed:
- `.env` or any file containing secrets
- `frontend/dist/` (build output)
- Screenshot or temp directories

### Commit message format

```
<Phase label>: <short description>

<bullet list of changes — what changed and why>

No backend changes.           ← include if true
No new endpoints.             ← include if true
No database changes.          ← include if true
static/index.html unchanged.  ← include if true

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

### Stabilization commits

A stabilization commit preserves a known-good audited state. It is created after audit approval and before any new phase begins. The commit message must name the audit result (e.g., "WS-D stabilization audit fixes") and list the exact defects resolved.

---

## SSE Safety Rules

These rules apply to all SSE streams in the Workspace and must not be weakened:

1. **Apply SSE never auto-retries.** `handleApplyError` dispatches `APPLY_ERROR` only. No reconnect logic.
2. **Terminal server events win over `onerror`.** `APPLY_ERROR` is a no-op when `applyPhase` is already `'error'` or `'done'`. The first error that lands is the one shown.
3. **Cache SSE `onerror` is a no-op after success.** `CACHE_ERROR` returns early when `cacheRunning` is already `false`.
4. **On Apply disconnect, show:** `"Connection lost — check Sync History for actual outcome."`
5. **Generation guard in `useSSEStream`.** Stale callbacks from superseded or closed `EventSource` instances are silently dropped via `genRef`.

---

## Dry Run Safety Rules

These rules apply to the Dry Run / Apply flow and must not be weakened:

1. Apply never runs unless `dryRunPhase === 'done'` and `dryRunResult !== null` and `dry_run_status !== 'blocked'` and `!dryRunInvalidated`.
2. Any selection change after a completed dry run sets `dryRunInvalidated: true`.
3. Any inline price or stock edit after a completed dry run sets `dryRunInvalidated: true`.
4. Any rollback after a completed dry run sets `dryRunInvalidated: true`.
5. A `dry_run_invalidated` server event clears local dry run state entirely (`dryRunPhase → 'idle'`, `dryRunResult → null`).
6. Apply sends `dryRunResult.dry_run_scope` (server-computed normalized IDs), not the raw UI selection.

---

## Release Policy

### Phase 5 — Production Cutover Preparation

Before any production cutover is attempted:

- All prior phases (WS-A through WS-D) must be committed and audited
- The React build (`npm run build`) must produce a clean output
- The built assets must be manually verified in a staging environment
- The `static/index.html` replacement plan must be reviewed and approved
- A rollback plan to the legacy frontend must exist

### Phase 6 — Legacy Frontend Replacement

- Phase 5 must be fully complete and signed off
- The legacy `static/index.html` and associated assets are replaced by the React build output
- Backend serving configuration is updated to serve the new frontend
- Post-cutover smoke test required before the legacy files are archived

**Never skip directly from any WS phase to Phase 6.**

---

## Backend Stability Rule

The backend (`app/main.py` and all files under `app/`) must not be modified during frontend migration phases unless a verified defect in the backend is found and documented. All 47 backend tests must pass before and after any change. No new endpoints may be added without explicit approval.

---

## WooPrice Beta

All future new product, UI, and platform work targets WooPrice Beta — not Production WooPrice.
Production WooPrice is maintenance-only from this point forward (bug fixes and safety fixes only).

Reference: [docs/BETA_STRATEGY.md](BETA_STRATEGY.md)
Master specification: [docs/BETA_MASTER_SPEC.md](BETA_MASTER_SPEC.md)
