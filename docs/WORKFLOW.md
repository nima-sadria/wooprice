# WooPrice Development and Audit Workflow

This document defines the mandatory process for all development, audit, and release work
on the WooPrice platform. It applies to human developers and AI agents.

---

## Project Lifecycle

Every feature phase follows this sequence without exception:

```text
Developer / AI Agent
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
  pytest         →  MUST PASS (339 tests as of 2026-06-23)
        │
        ▼
  Frontend tests
  vitest run     →  MUST PASS (74 tests as of 2026-06-23)
        │
        ▼
  Formal Audit
  (independent review — see Audit Requirements)
        │
        ▼
  Audit result: BLOCKERS / HIGH / MEDIUM / LOW
        │
        ├─ Any BLOCKER or HIGH found?
        │       │
        │       ├─ YES → Stop. No merge. No deploy. No next phase.
        │       │         Produce remediation plan.
        │       │         Fix only the flagged items.
        │       │         Re-audit after fix.
        │       │
        │       └─ NO  → Proceed to approval
        │
        ▼
  Approval
  (explicit: "approved", "proceed", or "safe to proceed: YES")
        │
        ▼
  Commit
  (single commit, one message, exact file list declared)
        │
        ▼
  Next phase begins
```

No phase is considered complete until all gates pass:

1. `npm run build` — PASS
2. `pytest` — PASS (all backend tests)
3. `vitest run` — PASS (all frontend tests)
4. Audit report delivered
5. No BLOCKER or HIGH findings
6. Commit created

---

## Risk Classification

### HIGH RISK — Mandatory formal audit before approval

These components touch WooCommerce write operations, scope isolation, or financial data.
Any defect here can silently corrupt prices or apply unvalidated changes.

| Component | Risk |
|---|---|
| Workspace / Dry Run | Scope validation, critical error blocking |
| Workspace / Apply | Irreversible WooCommerce price writes |
| Workspace / Rollback | Overwrites live WooCommerce data |
| Apply SSE lifecycle | Disconnect handling, no-retry policy |
| Dry Run invalidation | Must block Apply on any state change |
| Change Set execution | Any bulk apply to WooCommerce |
| Permission enforcement | Scope isolation, can_access_site gate |

### MEDIUM RISK — Review required, no standalone audit

| Component | Risk |
|---|---|
| Auth / JWT | Token revocation, permission checks |
| Settings | User configuration changes |
| Bulk Edit staging | Dry run gate, stale detection |
| Scheduling Engine | Deferred apply timing, abandonment detection |

### LOW RISK — Standard code review only

| Component | Risk |
|---|---|
| Analytics | Read-only display |
| Logs | Read-only audit history |
| Home / Dashboard | Static display |
| Direction Layer | Visual only, no data |
| Product Browser (read) | No write operations |

---

## Audit Requirements

Every formal audit must be independent (performed after implementation is complete).
The audit must cover all items in the phase scope, not just changed files.

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

### Mandatory Audit Sections for Workspace / Apply Phases

1. Apply trigger safety — `canRunApply` logic, scope pinning
2. Dry Run invalidation — all paths that set `dryRunInvalidated`
3. SSE no-retry policy — Apply disconnect must not auto-retry
4. Terminal event handling — `stale_preview`, `freshness_unverifiable`, `dry_run_invalidated` must win over `onerror`
5. Selection tracking — all selection change paths invalidate dry run
6. Permission enforcement — all write operations behind `authFetch` with JWT
7. Rollback safety — admin-only, invalidates dry run
8. Reducer correctness — no impossible state transitions
9. Regression check — Analytics / Logs / RTL unaffected; build and all tests pass

### Mandatory Audit Sections for Change Set / Bulk Edit Phases

1. Scope enforcement — items outside user scope must be rejected at creation
2. Dry-run gate — Apply must be blocked unless dry_run_status ∈ {passed, warnings}
3. Stale detection — old_value vs. current cache checked before each WC write
4. Concurrency safety — no double-claim of the same product by two concurrent jobs
5. Partial failure handling — one item failure must not abort the entire batch
6. Resume correctness — completed ExecutionBatches never re-executed after crash
7. Audit logging — every state transition recorded with actor and timestamp
8. Permission enforcement — all Change Set endpoints check effectiveHasPerm

### Blocking Rule

> **If any BLOCKER or HIGH finding exists: no merge, no deploy, no next phase.**

MEDIUM and LOW findings are documented in `docs/MIGRATION_STATUS.md` and addressed
in a future cleanup pass. They do not block the current phase.

---

## Commit Policy

### When to commit

Only after all completion gates pass.

### What to stage

Stage only the files that were intentionally changed. Never use `git add -A` or `git add .`.
Verify with `git diff --cached --stat` before committing.

Files that must never be committed:
- `.env` or any file containing secrets
- `frontend/dist/` (build output)
- Screenshot or temp directories

### Commit message format

```
<Phase label>: <short description>

<bullet list of changes — what changed and why>

Validation: N backend tests passed · M frontend tests passed · build OK

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

---

## SSE Safety Rules

These rules apply to all SSE streams and must not be weakened:

1. **Apply SSE never auto-retries.** `handleApplyError` dispatches `APPLY_ERROR` only. No reconnect logic.
2. **Terminal server events win over `onerror`.** `APPLY_ERROR` is a no-op when `applyPhase` is already `'error'` or `'done'`. The first terminal event wins.
3. **Cache SSE `onerror` is a no-op after success.** `CACHE_ERROR` returns early when `cacheRunning` is already `false`.
4. **On Apply disconnect, show:** `"Connection lost — check Sync History for actual outcome."`
5. **Generation guard in `useSSEStream`.** Stale callbacks from superseded `EventSource` instances are silently dropped via `genRef`.

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

## Change Set Safety Rules

These rules apply when the Change Set model is implemented. They extend (not replace) the Dry Run rules above.

1. A Change Set with scope violations must be rejected at creation. No partial acceptance.
2. Every Change Set item must store `old_value` at preview/draft time.
3. At execution time, if `current_cache_value != item.old_value`, the item must be skipped as stale (not failed — it is still a valid product; the cached value just changed).
4. Completed ExecutionBatches must never be re-executed. Check status before claiming.
5. Rollback must read `old_value` from the Change Set item, not from any live system.
6. Approval, when active, must enforce that `decided_by != changeset.created_by`. This is enforced at API and DB level.

---

## Platform Map Rule

Any implementation that changes architecture, routing, permissions, API contracts,
workflow behavior, deployment behavior, or major UI modules must also update
`docs/PLATFORM_MAP.md` in the same commit.

## Owner Decisions Rule

Any implementation that touches workflow, permissions, channel behavior, scheduling,
or spreadsheet integration must be reviewed against `docs/OWNER_DECISIONS.md` before
implementation begins. If the implementation would contradict an owner decision, stop
and escalate before writing code.

---

## Backend Stability Rule

Backend tests must pass before and after every change.
As of 2026-06-23: 339 backend tests, 74 frontend tests.
These counts may increase but must never decrease without explicit removal justification.
