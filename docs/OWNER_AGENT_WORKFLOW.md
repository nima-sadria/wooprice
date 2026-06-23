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

Approval is operation-specific. Generic phrases like "approved" or "proceed" are not
sufficient — the owner's instruction must name the operation or scope being authorized.

| Approval type | Required phrasing (examples) | Applies to |
|---|---|---|
| **Owner approval to implement** | "implement X", "add Y", "fix Z", "do this task" | Implementation gates (2–6, 8) — granted when the owner assigns the task |
| **Owner approval to modify safety-critical workflow** | "change the dry run logic", "modify apply", "update Emergency Apply", "change auth" | Gates 2, 3, 4, 6 when scope is safety-critical |
| **Owner approval to deploy** | "deploy", "push to production", "build and deploy", "run docker compose up" | Gate 1 — Production Deployment |
| **Owner approval to run production action** | "enable maintenance mode", "disable maintenance mode", "run this on production" | Gate 7 — Maintenance Mode |
| **Owner approval to change safety policy** | "change the alarm threshold", "update block_enabled", "change this safety rule" | Gate 8 — Safety-Policy Changes |

**Approval does not carry across sessions.** A gate approved in session A is not
approved in session B. Each session starts with all gates closed.

**Approval does not carry across scope.** Approving "implement the dry run fix" does
not approve "also modify the apply path". Approving one operation does not implicitly
approve related operations — each must be named explicitly.

---

## Standard Agent Session Workflow

Every implementation session follows this sequence:

```
1. Read mandatory docs
   README.md, docs/OWNER_DECISIONS.md, docs/WORKFLOW.md,
   docs/ARCHITECTURE.md, docs/PLATFORM_MAP.md, docs/ROADMAP.md,
   docs/OWNER_AGENT_WORKFLOW.md (this file)

2. Identify applicable Human Approval Gates
   Review the gate list below. Determine which gates (if any) apply to this task.

   Gate behavior depends on gate type:
   - Implementation gates (Gates 2–6, 8): owner must approve the implementation scope
     before coding begins. The owner approving the task at the start of a session
     ("do X", "implement Y") is sufficient. No additional mid-session approval needed
     unless scope changes.
   - Production/run-action gates (Gates 1, 7): owner must give explicit approval
     AFTER audit has passed, immediately before the production action executes.

3. Implement
   Proceed once task scope is owner-approved.
   Code only — no commits yet.

4. Validate
   npm run build → MUST PASS
   pytest → MUST PASS (339 backend tests)
   vitest run → MUST PASS (74 frontend tests)

5. Audit
   Formal audit after implementation, before commit.
   Report BLOCKERS / HIGH / MEDIUM / LOW.
   Any BLOCKER or HIGH: stop. Fix, re-validate, re-audit before proceeding.

6. For production/run-action gates only — await explicit owner approval
   If the task touches Gate 1 (deployment) or Gate 7 (maintenance mode):
   stop after audit PASS and await "Owner approval to deploy" or
   "Owner approval to run production action" before executing.
   For all other gates: proceed to commit after audit PASS.

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

**Required approval:** "Owner approval to deploy" — owner must explicitly name the
deployment action (e.g., "deploy", "push to production", "run docker compose up")
in the current session, after audit has passed.

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

**Required approval:** "Owner approval to modify safety-critical workflow" — owner must
name the Apply path change in the task assignment. Audit runs after implementation;
commit requires audit PASS with no BLOCKER or HIGH findings.

**AI must not:**
- Change Apply path code without explicit task assignment from owner
- Weaken any of the four Apply pre-conditions (dry run done, result not null, status not blocked, not invalidated)
- Change scope pinning behavior

**After approval:** Implement, validate, audit. Audit PASS required before commit.

---

### Gate 3 — Dry Run Workflow Changes

**Trigger:** Any change to dry run logic:
- `POST /api/sync/{id}/dry-run` endpoint
- Dry run invalidation triggers (any action that calls `invalidateDryRun`)
- `dry_run_status` values or how they are set
- Frontend `dryRunPhase` state machine transitions
- Any new action that should (or should not) invalidate a dry run

**Required approval:** "Owner approval to modify safety-critical workflow" — owner must
name the dry run change in the task assignment. Audit runs after implementation;
commit requires audit PASS with no BLOCKER or HIGH findings.

**AI must not:**
- Add or remove invalidation triggers without explicit task assignment from owner
- Change what dry_run_status values are possible without explicit task assignment

**After approval:** Implement, validate, audit. Audit PASS required before commit.

---

### Gate 4 — Emergency Apply

**Trigger:** Any change to the Emergency Apply path:
- `POST /api/emergency/preview`
- `POST /api/emergency/{id}/apply` (atomic claim + checkpoints)
- `DELETE /api/emergency/{id}`
- The three-checkpoint commit sequence (applying → wc_succeeded → applied)
- The per-item freshness check before WC write

**Required approval:** "Owner approval to modify safety-critical workflow" — owner must
name the Emergency Apply change in the task assignment.

**AI must not:**
- Remove or reorder the three checkpoint commits
- Weaken the atomic SQL claim (single UPDATE WHERE status='pending')
- Remove or weaken the per-item freshness check

**After approval:** Implement, validate, full audit of atomic claim + checkpoint sequence. Audit PASS required before commit.

---

### Gate 5 — WooCommerce Write Paths

**Trigger:** Any code change that results in a write to the WooCommerce REST API:
- New endpoint that calls `woocommerce.update_product()`
- New bulk write operation
- Changes to the WC batch API call logic
- Changes to how failed WC writes are handled

**Required approval:** "Owner approval to implement" — owner must explicitly name the
new write operation in the task assignment.

**AI must not:**
- Add any new WC write path without explicit task assignment from owner
- Change error handling on WC writes without explicit task assignment (HTTP 502 behavior must be preserved)
- Change retry logic on WC writes without explicit task assignment

**After approval:** Implement, validate, formal audit focused on write-path safety invariants. Audit PASS required before commit.

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

**Required approval:** "Owner approval to implement" — owner must explicitly name the
auth component change in the task assignment.

**AI must not:**
- Change JWT structure without explicit task assignment (token format changes break all active sessions)
- Change pv validation without explicit task assignment (could allow stale tokens)
- Weaken super-admin detection

**After approval:** Implement, validate all 339 backend tests pass, audit auth paths. Audit PASS required before commit.

---

### Gate 7 — Maintenance Mode

**Trigger:** Any change to maintenance mode behavior:
- Enabling or disabling maintenance mode on the running production system
- `POST /api/admin/maintenance` calls
- Changes to the maintenance mode middleware (which endpoints bypass it)
- Any change to who can enable/disable maintenance mode

**Required approval:** "Owner approval to run production action" — owner must explicitly
instruct the agent to enable or disable maintenance mode in the current session.
This approval is given immediately before execution, not at task assignment time.

**AI must not:**
- Enable maintenance mode without "Owner approval to run production action" in the current session
- Disable maintenance mode without "Owner approval to run production action" in the current session
- Change which endpoints bypass maintenance mode without explicit task assignment from owner

**After approval:** Execute the maintenance mode change, report the result immediately.

---

### Gate 8 — Safety-Policy Changes

**Trigger:** Any change that affects what constitutes a dangerous price change:
- Alarm threshold values (warning %, critical %)
- `block_enabled` flag (default false — never change default without approval)
- Future configurable safety rule implementation (warn/block model)
- Changes to which rule types exist or their default behavior
- Any change to `dry_run_status` resolution logic

**Required approval:** "Owner approval to change safety policy" — owner must explicitly
name the safety rule or threshold change in the task assignment.

**AI must not:**
- Change default safety rule behavior from warn to block without explicit task assignment
- Add new block rules that could freeze the Apply path without explicit task assignment
- Remove or weaken existing alarm threshold enforcement

**After approval:** Implement, validate, audit with focus on dry run outcome correctness. Audit PASS required before commit.

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
