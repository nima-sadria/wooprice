# WooPrice Owner Agent Workflow

This document defines how the project owner authorizes AI agents to act,
what approval means in each context, and which operations require explicit
human sign-off before an AI agent proceeds.

AI agents must read this document at the start of every session that involves
implementation, deployment, or changes to safety-critical paths.

---

## Agent Roles at a Glance

| Agent | Authorized to | Not authorized to |
|---|---|---|
| **Claude Code** | Implement, refactor, test, document | Approve own work, deploy, start new phases unilaterally |
| **Codex** | Audit, review, report findings | Implement, approve based on reports alone |
| **Human Owner** | Approve, reject, direct, deploy, decide risk | — |

Full role definitions: `docs/AI_OPERATING_MANUAL.md`

---

## What "Approval" Means

An AI agent may proceed past a gate only when the human owner has sent a message
in the current session containing one of the following phrases (case-insensitive):

- `approved`
- `proceed`
- `safe to proceed: YES`
- `deploy` (for production deployment gates only)
- An explicit instruction that names the gated operation (e.g., "push to production",
  "apply this to WooCommerce", "enable maintenance mode")

**Approval does not carry across sessions.** A gate approved in session A is not
approved in session B. Each session starts with all gates closed.

**Approval does not carry across scope.** Approving "run dry run" does not approve
"run apply". Approving one endpoint change does not approve a second endpoint change
in the same category.

---

## Standard Agent Session Workflow

Every implementation session follows this sequence:

```
1. Read mandatory docs
   README.md, docs/OWNER_DECISIONS.md, docs/WORKFLOW.md,
   docs/ARCHITECTURE.md, docs/PLATFORM_MAP.md, docs/ROADMAP.md,
   docs/OWNER_AGENT_WORKFLOW.md (this file)

2. Understand the task scope
   Identify which Human Approval Gates apply to this task (see below).
   If a gate applies: confirm with owner before beginning implementation.

3. Implement
   Code only — no commits yet.

4. Validate
   npm run build → MUST PASS
   pytest → MUST PASS (339 backend tests)
   vitest run → MUST PASS (74 frontend tests)

5. Audit
   Formal audit before commit. Report BLOCKERS / HIGH / MEDIUM / LOW.
   Any BLOCKER or HIGH: stop. No commit. No next step.

6. Wait for human approval
   "Safe to proceed: YES" from owner — or an equivalent approval phrase.

7. Commit
   Stage only intentionally changed files. Never git add -A.
   Verify with git diff --cached --stat.

8. Push only if owner explicitly requests it
   Never push without an explicit instruction in the current session.
```

---

## Human Approval Gates

Each gate below defines:
- **Trigger** — what event requires the gate
- **Required approval text** — minimum phrasing from the owner
- **AI must not** — what the agent must not do before approval
- **After approval** — what the agent may do

---

### Gate 1 — Production Deployment

**Trigger:** Any action that updates the running production system:
- `docker compose up --build`
- Pushing to a branch that auto-deploys
- Updating the Docker image tag in production
- Updating Nginx Proxy Manager config
- Any `git push` intended to update a live environment

**Required approval text:** Owner must explicitly say "deploy", "push to production",
or name the deployment action in the current session.

**AI must not:**
- Auto-deploy based on a passing test suite
- Deploy as part of a commit sequence without separate explicit instruction
- Infer deployment intent from "we're done" or "commit and push"

**After approval:** Execute the deployment command, report the result.

---

### Gate 2 — Apply Workflow Changes

**Trigger:** Any change to code or configuration that affects the Apply path:
- `POST /api/sync/{id}/confirm` endpoint
- `GET /api/sync/{id}/apply-stream` endpoint or its SSE event handling
- `canRunApply` logic in the frontend
- `dryRunResult.dry_run_scope` usage (scope pinning)
- Any new code that triggers a WooCommerce write during an Apply operation

**Required approval text:** `approved` or `safe to proceed: YES` after a formal audit.

**AI must not:**
- Change Apply path code without a completed formal audit
- Weaken any of the four Apply pre-conditions (dry run done, result not null, status not blocked, not invalidated)
- Change scope pinning behavior

**After approval:** Implement the change, validate, audit again if scope expands.

---

### Gate 3 — Dry Run Workflow Changes

**Trigger:** Any change to dry run logic:
- `POST /api/sync/{id}/dry-run` endpoint
- Dry run invalidation triggers (any action that calls `invalidateDryRun`)
- `dry_run_status` values or how they are set
- Frontend `dryRunPhase` state machine transitions
- Any new action that should (or should not) invalidate a dry run

**Required approval text:** `approved` or `safe to proceed: YES` after formal audit.

**AI must not:**
- Add invalidation triggers without approval
- Remove invalidation triggers without approval
- Change what dry_run_status values are possible

**After approval:** Implement, validate, audit. Any BLOCKER or HIGH blocks the commit.

---

### Gate 4 — Emergency Apply

**Trigger:** Any change to the Emergency Apply path:
- `POST /api/emergency/preview`
- `POST /api/emergency/{id}/apply` (atomic claim + checkpoints)
- `DELETE /api/emergency/{id}`
- The three-checkpoint commit sequence (applying → wc_succeeded → applied)
- The per-item freshness check before WC write

**Required approval text:** Explicit owner instruction naming Emergency Apply.

**AI must not:**
- Remove or reorder the three checkpoint commits
- Weaken the atomic SQL claim (single UPDATE WHERE status='pending')
- Remove or weaken the per-item freshness check

**After approval:** Implement, validate, full audit of atomic claim + checkpoint sequence.

---

### Gate 5 — WooCommerce Write Paths

**Trigger:** Any code change that results in a write to the WooCommerce REST API:
- New endpoint that calls `woocommerce.update_product()`
- New bulk write operation
- Changes to the WC batch API call logic
- Changes to how failed WC writes are handled

**Required approval text:** Explicit owner instruction naming the write operation.

**AI must not:**
- Add any new WC write path without a gate approval
- Change error handling on WC writes without approval (HTTP 502 behavior must be preserved)
- Change retry logic on WC writes

**After approval:** Implement, validate, formal audit focused on write-path safety invariants.

---

### Gate 6 — Authentication and JWT

**Trigger:** Any change to the authentication system:
- JWT signing key, algorithm, or token structure
- `permission_version` logic (pv validation)
- `SUPER_ADMIN_USERS` env var handling
- `POST /api/auth/login` logic
- `GET /api/auth/me` token decode + permission snapshot
- `AuthProvider` on-mount fetch or storage event handling
- Any change to `is_admin` or `is_super_admin` resolution

**Required approval text:** Explicit owner instruction naming the auth component.

**AI must not:**
- Change JWT structure without approval (token format changes break all active sessions)
- Change pv validation without approval (could allow stale tokens)
- Weaken super-admin detection

**After approval:** Implement, validate all 339 backend tests pass, audit auth paths.

---

### Gate 7 — Maintenance Mode

**Trigger:** Any change to maintenance mode behavior:
- Enabling or disabling maintenance mode on the running production system
- `POST /api/admin/maintenance` calls
- Changes to the maintenance mode middleware (which endpoints bypass it)
- Any change to who can enable/disable maintenance mode

**Required approval text:** Explicit owner instruction naming maintenance mode.

**AI must not:**
- Enable maintenance mode without explicit owner instruction
- Disable maintenance mode without explicit owner instruction
- Change which endpoints bypass maintenance mode without approval

**After approval:** Execute the maintenance mode change, report the result immediately.

---

### Gate 8 — Safety-Policy Changes

**Trigger:** Any change that affects what constitutes a dangerous price change:
- Alarm threshold values (warning %, critical %)
- `block_enabled` flag (default false — never change default without approval)
- Future configurable safety rule implementation (warn/block model)
- Changes to which rule types exist or their default behavior
- Any change to `dry_run_status` resolution logic

**Required approval text:** Explicit owner instruction naming the safety rule or threshold.

**AI must not:**
- Change default safety rule behavior from warn to block without approval
- Add new block rules that could freeze the Apply path without approval
- Remove or weaken existing alarm threshold enforcement

**After approval:** Implement, validate, audit with focus on dry run outcome correctness.

---

## Escalation Procedure

When an AI agent encounters any of the following, it must stop and report to the owner
before proceeding:

1. A task that touches a gated operation and no approval has been given in the current session
2. A finding during implementation that suggests a gate applies (even if the original task description did not mention it)
3. A BLOCKER or HIGH audit finding
4. A contradiction between the task and an owner decision in `docs/OWNER_DECISIONS.md`
5. An unexpected production state (e.g., uncommitted changes, unexpected branch, unexpected files)

**Escalation format:**

```
GATE: [gate name]
STATUS: Awaiting approval
REASON: [one sentence explaining what was found]
REQUIRED: [what the owner needs to say to proceed]
```

Do not implement a workaround. Do not continue with a lower-risk subset of the task
without disclosing the escalation. Report and wait.

---

## Session Checklist

Before starting any implementation task, the agent should verify:

- [ ] Mandatory docs read (README, OWNER_DECISIONS, WORKFLOW, ARCHITECTURE, PLATFORM_MAP, ROADMAP, this file)
- [ ] Task scope identified
- [ ] Which Human Approval Gates (if any) apply to this task
- [ ] Gate approvals obtained (or task confirmed to not require a gate)
- [ ] Contract Index in OWNER_DECISIONS.md checked for relevant constraints
