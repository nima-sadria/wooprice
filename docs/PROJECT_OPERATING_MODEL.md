# WooPrice Project Operating Model

This document defines how WooPrice development is governed after:
- Governance PASS (all governance audits resolved through R5)
- A2 Architecture Approval (owner approval granted on `docs/A2_ARCHITECTURE.md`)

It is the operational companion to the governance documents. Where those documents
define *what* is allowed, this document defines *how the project actually runs*.

**Effective from:** A2 Architecture Approval
**Supersedes:** Ad-hoc session-by-session operating agreements

---

## Document Authority

This document governs operating process. It does not override:

| Document | Overrides this document on |
|---|---|
| `docs/OWNER_DECISIONS.md` | Policy, strategy, owner intent |
| `docs/OWNER_AGENT_WORKFLOW.md` | Human Approval Gate definitions |
| `docs/A2_ARCHITECTURE.md` | Architecture specification |
| `docs/WORKFLOW.md` | Delivery lifecycle and test gates |

In any conflict between this document and the above, the above wins. Update this
document to resolve the conflict — do not work around it.

---

## 1. Project Roles

### Owner

**Who:** Nima Sadria

**Authority:** Ultimate. All decisions about direction, risk, approval, and
deployment rest with the owner. No other role may override the owner.

**Responsibilities:**
- Approve or reject architecture revisions
- Grant phase entry and exit approval
- Authorize deployments (Gate 1)
- Accept or reject Codex audit findings
- Issue owner decisions that bind all other roles
- Direct Claude Developer task scope per session
- Perform Command Center duties (see below)

**Constraints:** None — the owner is the final arbiter.

---

### Claude Developer

**Who:** Claude (this AI system, current session)

**Authority:** Implementation only, within owner-approved scope.

**Responsibilities:**
- Implement features, bug fixes, and refactors per owner task assignment
- Write and maintain tests (backend pytest, frontend vitest)
- Maintain documentation in the same commit as the code change it describes
- Follow all Human Approval Gates (`docs/OWNER_AGENT_WORKFLOW.md`)
- Read mandatory docs at the start of every session
- Escalate when a gate is triggered or a contradiction is found

**Constraints:**
- May not approve own work
- May not start a new phase without owner authorization
- May not deploy without Gate 1 approval in the current session
- May not proceed past any open gate
- May not implement anything that contradicts `docs/OWNER_DECISIONS.md`
- May not skip validation (build, backend tests, frontend tests)
- May not weaken safety invariants (`docs/ARCHITECTURE.md` Section: Critical Safety Invariants)

**Session start requirement:** Read all mandatory docs before any implementation:
`README.md`, `docs/OWNER_DECISIONS.md`, `docs/OWNER_AGENT_WORKFLOW.md`,
`docs/WORKFLOW.md`, `docs/ARCHITECTURE.md`, `docs/PLATFORM_MAP.md`,
`docs/ROADMAP.md`, `docs/A2_ARCHITECTURE.md`, this document.

---

### Codex Auditor

**Who:** Codex (independent audit AI)

**Authority:** Audit findings only. A Codex PASS is required for phase exit.
A Codex HOLD or REVISE blocks phase exit.

**Responsibilities:**
- Perform formal audits on committed code at a specified origin/main commit
- Produce a BLOCKERS / HIGH / MEDIUM / LOW findings report
- Issue one of: PASS, HOLD, or REVISE
- Verify PLATFORM_MAP accuracy against current code
- Verify that A2 architecture compliance rules are respected (after each A2 phase)
- Verify governance document consistency

**Constraints:**
- May not implement code
- May not approve a phase based solely on a report summary
- May not issue PASS when unresolved BLOCKERS or HIGHs exist
- Audit must target the current `origin/main` commit — uncommitted work is not auditable

**Audit trigger:** Owner requests a Codex audit. Claude Developer does not trigger
Codex audits independently; the owner directs this.

---

### Command Center

**Who:** The owner acting in their coordination capacity.

**What it is:** Command Center is the coordination function the owner performs when
orchestrating work between Claude Developer and Codex Auditor. It is the owner wearing
an operational hat rather than a decision-making hat.

**Responsibilities:**
- Direct Claude Developer task assignments for each session
- Route Codex audit findings to Claude Developer for remediation
- Manage phase gate state (open / closed per phase)
- Make go/no-go decisions at phase exit
- Maintain the phase schedule and priority order
- Identify and escalate unplanned work (bugs, security issues, urgent fixes)
- Decide when to run a Codex audit vs. continue implementation

**Command Center authority is limited to the boundary of owner decisions already made.**
If the Command Center encounters a situation requiring a new owner decision (not covered
by existing governance), it escalates to the Owner role before proceeding.

---

## 2. Phase Control Rules

### Entry

A phase may not begin until:
1. All prior phases in the A2 implementation sequence are complete and in production
   (or the owner explicitly approves out-of-order work with documented rationale)
2. Owner grants phase entry in the current session
3. Phase entry is logged as a Command Center decision

**Phase entry is not implicit.** Completing Phase N does not automatically open Phase N+1.

### Scope

Work within a phase is limited to what the A2 Architecture document defines for that phase.
Out-of-scope work requires owner authorization before it is added to the phase.

### Ordering

The A2 phase sequence is mandatory (owner decision R1):

```
Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5 → Phase 6 → Phase 7
                                                               ↓
Phase 8 (Scheduling) — not before all of Phase 1–7 in production
Phase 9 (PostgreSQL) — can run in parallel with Phases 1–8
```

Scheduling (Phase 8) may not begin before all of the following are deployed to production:
channel abstraction (Phase 2), scoped permissions (Phase 3), safety engine (Phase 4),
rule engine (Phase 5), canonical product model (Phase 1), Change Set engine (Phase 6),
source adapter layer (Phase 7).

### Phase Modification

Changes to phase scope or sequence require owner approval and an update to:
- `docs/ROADMAP.md` (phase list)
- `docs/A2_ARCHITECTURE.md` (if architectural scope changes)
- This document (if control rules change)

All three must be updated in the same commit.

---

## 3. Architecture Compliance Rules

All implementation must comply with `docs/A2_ARCHITECTURE.md` after each applicable phase.

### Always enforced (from A2 approval forward)

| Rule | Source | Violation severity |
|---|---|---|
| Seller confirmation is mandatory for every execution | Owner decision R1 §1 | BLOCKER |
| AI layer may not override Safety Policy Engine | A2 §5 | BLOCKER |
| No auto-schedule or auto-apply without seller confirmation | Owner decision R1 §1 | BLOCKER |
| `scope = null` (all dimensions) is admin/super-admin only | A2 §6.4 | HIGH |
| Scope enforcement uses INTERSECTION semantics | A2 §6.4 | HIGH |
| Live freshness verification must be implemented before any channel write path | A2 §8.2 | HIGH |
| `unverifiable` freshness = hard block; no degraded mode | A2 §8.2 | BLOCKER |
| Credentials never appear in logs, SSE streams, or API responses | A2 §13.5 | BLOCKER |
| Change Set item_count must be enforced ≤ 1,000 at API layer | OWNER_DECISIONS §Capacity | HIGH |

### Enforced after Phase 1 (Canonical Product Model)

| Rule | Violation severity |
|---|---|
| New code must not use wc_id as a primary product identifier | HIGH |
| Product identity must be traceable to `products.id` (UUID + SKU) | HIGH |
| Channel-specific identifiers must live in `channel_listings` | HIGH |

### Enforced after Phase 2 (Channel Adapter)

| Rule | Violation severity |
|---|---|
| No direct WooCommerce API calls outside ChannelAdapter implementation | HIGH |
| Live freshness verification must be called before every execution | BLOCKER |
| All channel writes must produce an `execution_attempts` record | HIGH |

### Enforced after Phase 6 (Change Set Engine)

| Rule | Violation severity |
|---|---|
| DryRunDigest must be computed before any Change Set is confirmed | BLOCKER |
| Execution-time revalidation must run before any QueueWorker executes | BLOCKER |
| Digest mismatch must reset Change Set to `validated` and block execution | BLOCKER |
| Per-item idempotency key must be used on every execution attempt | HIGH |

### Enforced after Phase 7 (Source Adapter)

| Rule | Violation severity |
|---|---|
| No direct Nextcloud/WebDAV calls outside SourceAdapter implementation | HIGH |
| Source checkpoint must not advance if Change Set execution fails | HIGH |
| Duplicate product IDs in a snapshot must block the entire import | HIGH |

### Architecture Compliance Review

Codex must review architecture compliance as part of every phase-exit audit.
A BLOCKER finding for architecture compliance blocks phase exit.

---

## 4. Governance Compliance Rules

### Authority Matrix

When a contradiction exists between documents, the domain-based authority matrix applies:

| Domain | Authority |
|---|---|
| Policy and strategy | `docs/OWNER_DECISIONS.md` |
| Delivery process | `docs/WORKFLOW.md` |
| Phase sequencing | `docs/ROADMAP.md` |
| Agent control and gates | `docs/OWNER_AGENT_WORKFLOW.md` |
| Architecture specification | `docs/A2_ARCHITECTURE.md` |
| Current implementation truth | Code + DB schema |
| Derived references | `docs/PLATFORM_MAP.md`, `docs/ARCHITECTURE.md` |

### Contradiction Handling

1. Claude Developer identifies a contradiction between a task and a governance document
2. Claude Developer stops and escalates to the owner (does not implement a workaround)
3. Owner resolves the contradiction by either:
   - Updating the governing document, OR
   - Explicitly overriding it with a new owner decision (documented in `docs/OWNER_DECISIONS.md`)
4. Contradiction resolution is committed before implementation continues

Claude Developer must never resolve a governance contradiction by choosing one document
over another without explicit owner direction.

### Owner Decision Binding

Owner decisions in `docs/OWNER_DECISIONS.md` bind all future implementation.
An owner decision may only be changed by the owner, documented in `docs/OWNER_DECISIONS.md`,
committed to origin/main, and reflected in all affected governance documents.

---

## 5. Audit Requirements

### When a Codex Audit Is Required

| Trigger | Audit type |
|---|---|
| Phase exit | Phase-exit audit covering all deliverables for that phase |
| Production deployment | Pre-deploy audit of the commit being deployed |
| Architecture revision | Architecture-only audit (no code required) |
| Governance document update | Governance-only audit |
| Safety-critical change (Gates 2–4, 8) | Focused audit on the changed path |
| Owner request | Full or focused at owner's direction |

### Audit Commit Requirement

Codex must audit a specific `origin/main` commit.
Uncommitted or locally-staged work is not auditable.
Codex must be given the exact commit hash, not just "the current code."

### Audit Findings Classification

| Severity | Definition | Effect |
|---|---|---|
| BLOCKER | Safety invariant violated, data corruption risk, or security vulnerability | Phase exit blocked; deployment blocked; must fix before any further work |
| HIGH | Significant correctness, architecture, or compliance issue | Phase exit blocked; must fix before exit; may continue other implementation in parallel |
| MEDIUM | Non-critical but meaningful issue | Tracked in ROADMAP.md open findings; does not block exit; must be addressed before next phase exit |
| LOW | Minor issue, style, or improvement | Tracked in ROADMAP.md open findings; does not block any gate |

### Audit Outcome

| Outcome | Meaning | Effect |
|---|---|---|
| PASS | No BLOCKERS, no unresolved HIGHs | Phase exit permitted; deployment permitted |
| HOLD | BLOCKERS or HIGHs present; remediation committed but not yet re-audited | All gates blocked until re-audit PASS |
| REVISE | Architecture or governance document revision required (not code) | No implementation until revision committed and re-audited |

### Remediation Sequence

```
Codex issues HOLD or REVISE
  ↓
Owner reviews findings and prioritizes remediation
  ↓
Claude Developer implements fixes (BLOCKER and HIGH only; MEDIUM/LOW to open findings)
  ↓
Fixes committed and pushed to origin/main
  ↓
Owner requests Codex re-audit of the new commit
  ↓
Codex issues PASS or new HOLD/REVISE
  ↓
Repeat until PASS
```

---

## 6. Technical Debt Tracking

### What Counts as Technical Debt

- Open MEDIUM and LOW findings from Codex audits
- Known gaps documented in PLATFORM_MAP.md Section F
- Planned-but-deferred items in ROADMAP.md open findings
- Known limitations documented in README.md

### Tracking Location

All open findings are tracked in `docs/ROADMAP.md` under "Open Findings."

Each entry must include:
- Finding ID (e.g., WS-C M1) or descriptive label
- Severity (MEDIUM or LOW — BLOCKERS and HIGHs must be fixed before phase exit)
- Description of the issue
- Source (which audit, which phase)

### Debt Review

Open findings are reviewed at every phase gate.
No new phase may exit if an unreviewed MEDIUM finding from a prior phase remains.
LOW findings may carry forward across multiple phases.

### Debt Promotion

If a MEDIUM or LOW finding is determined to be more severe than originally classified:
1. Owner decides the new severity
2. ROADMAP.md entry is updated
3. If elevated to HIGH: blocks current phase exit; fix required immediately
4. If elevated to BLOCKER: blocks all work; fix required before anything else

---

## 7. Phase Exit Criteria

### Universal Exit Criteria (all phases)

All of the following must be true before any phase may exit:

1. **Implementation complete** — all planned deliverables for the phase are implemented
2. **Build passes** — `npm run build` succeeds with no errors
3. **Backend tests pass** — `pytest` passes (no failures, no errors)
4. **Frontend tests pass** — `vitest run` passes (no failures, no errors)
5. **Codex PASS** — no BLOCKERS, no unresolved HIGHs
6. **PLATFORM_MAP current** — updated to reflect all changes in this phase
7. **ROADMAP updated** — phase marked complete; new stable checkpoint recorded
8. **Owner explicit approval** — "phase N exit approved" or equivalent in current session

### Phase-Specific Exit Criteria

| Phase | Additional exit criteria |
|---|---|
| Phase 1 (Canonical Product) | Reconciliation check: `products` and `channel_listings` row counts match `products_cache`; no price mismatches |
| Phase 2 (Channel Adapter) | All existing Apply paths verified to route through `ChannelAdapter`; live freshness check operational |
| Phase 3 (Scoped Permissions) | Existing users verified to have `scope = null` (no behavior change); intersection test cases pass |
| Phase 4 (Safety Engine) | Existing alarm thresholds verified to have migrated to `safety_policies` as global warn rules |
| Phase 5 (Rule Engine) | Default `ManualPriceRule` verified to produce identical prices to current passthrough behavior |
| Phase 6 (Change Set Engine) | DryRunDigest computation verified; state machine transitions tested; execution-time revalidation all 6 checks tested |
| Phase 7 (Source Adapter) | Nextcloud adapter produces identical output to current `nextcloud.py`; field mapping round-trip tested |
| Phase 8 (Scheduling) | Scheduler fires at correct UTC time for all 3 modes; DST test case passes; cancellation tested; abandonment recovery tested |
| Phase 9 (PostgreSQL) | Row count reconciliation passes; smoke test passes; rollback path documented and tested |

### Workspace Compatibility (Phases 1–7)

For all phases 1–7, the existing Workspace flow must remain fully operational.
Phase exit is blocked if the Workspace flow is broken (any regression in preview,
dry run, apply, rollback, or writeback).

---

## 8. Production Deployment Rules

### Prerequisites (all must be met before any deployment)

1. Codex PASS on the commit to be deployed
2. Gate 1 — "Owner approval to deploy" — given in the current session after PASS
3. No unresolved BLOCKER findings
4. Rollback plan documented (which `docker compose` commands restore previous version)
5. For DB schema changes: maintenance mode enabled before migration; disabled after

### Deployment Procedure

```
1. Owner grants Gate 1: "Owner approval to deploy" [commit hash]
2. Enable maintenance mode (if DB migration required)
   → Requires Gate 7: "Owner approval to run production action"
3. Pull latest origin/main on production host
4. docker compose up -d --build
5. Run smoke tests (health check, login, basic workflow)
6. If DB migration: verify migration success; disable maintenance mode
7. Monitor logs for 5 minutes
8. Report deployment outcome to owner
```

### No-Deploy Conditions

Claude Developer must not deploy when any of the following is true:
- Open BLOCKER findings exist
- Gate 1 has not been granted in the current session
- Tests are failing
- The working tree has uncommitted changes
- Deployment was not explicitly requested in the current session

### Rollback Trigger

Rollback is initiated by the owner if:
- Smoke tests fail after deployment
- Production errors appear in logs within 5 minutes of deployment
- Owner decides to rollback for any reason

Rollback does not require Codex audit; it is an emergency restore action.
Post-rollback, a retrospective is added to `docs/ROADMAP.md` open findings.

---

## 9. Emergency Change Rules

### Definition

An emergency change is any change that must be made outside the normal phase gate
process due to an active production incident, security vulnerability, or data integrity
risk.

### Emergency Change Authorization

Emergency changes require:
1. Owner verbal or written authorization naming the specific change
2. Gate 1 approval for deployment (still required)
3. Post-change Codex audit within the next planned session

The owner may waive the pre-implementation audit for emergency changes, but the
post-change audit is mandatory and may not be deferred more than one session.

### Emergency Change Scope

Emergency changes are limited to the minimum scope required to resolve the incident.
They must not introduce new features, refactors, or governance changes under the
cover of an emergency.

If an emergency change reveals a governance gap:
- The change fixes the immediate problem
- The governance gap is documented in `docs/ROADMAP.md` open findings
- A governance update is made in the next non-emergency session

### Safety-Critical Emergency Changes

Emergency changes to Apply paths, dry run logic, Emergency Apply, or authentication
still require their respective gate approvals (Gates 2–4, 6). The word "emergency"
does not bypass safety-critical gates. Only Gate 1 timing is adjusted (audit may
follow rather than precede).

### Post-Emergency Protocol

```
After every emergency change:
1. Add entry to ROADMAP.md: "Emergency change: [date], [description], [commit]"
2. Document root cause in the same entry
3. Request Codex audit of the emergency commit in the next session
4. If Codex finds new issues from the emergency change: treat as BLOCKER and fix immediately
```

---

## 10. Documentation Synchronization Rules

### Sync-on-Commit Rule

Every commit that changes code, schema, API contracts, routes, permissions, or workflow
behavior must update the affected documentation in the same commit.

| Change type | Documentation that must be updated in same commit |
|---|---|
| New API endpoint or changed signature | `docs/PLATFORM_MAP.md` Section A (Backend) |
| New route or changed permission guard | `docs/PLATFORM_MAP.md` Section C + `docs/ARCHITECTURE.md` route tree |
| New or changed workflow step | `docs/PLATFORM_MAP.md` Section B + `docs/ARCHITECTURE.md` |
| Permission added, removed, or changed | `docs/PLATFORM_MAP.md` Section C |
| New safety mechanism | `docs/PLATFORM_MAP.md` Section D |
| Phase completed | `docs/ROADMAP.md` (mark complete + stable checkpoint) |
| Architecture pattern change | `docs/ARCHITECTURE.md` + `docs/PLATFORM_MAP.md` |
| New owner decision | `docs/OWNER_DECISIONS.md` + any affected docs |
| New Human Approval Gate | `docs/OWNER_AGENT_WORKFLOW.md` + `docs/AI_OPERATING_MANUAL.md` |
| Safety invariant added or changed | `docs/ARCHITECTURE.md` Section: Critical Safety Invariants |

### PLATFORM_MAP Drift

PLATFORM_MAP drift (code and map disagree) is a HIGH finding in every Codex audit.

Codex must verify PLATFORM_MAP against current code using the drift detection checklist
in `docs/PLATFORM_MAP.md` Section H whenever any code change is audited.

PLATFORM_MAP must never be used as the source of truth for factual claims —
code and schema win. If the map and code disagree, update the map.

### ARCHITECTURE.md vs A2_ARCHITECTURE.md

`docs/ARCHITECTURE.md` describes the current implemented system.
`docs/A2_ARCHITECTURE.md` describes the target architecture.

During A2 implementation:
- As each phase is completed and in production, `docs/ARCHITECTURE.md` is updated
  to reflect the new implemented state
- `docs/A2_ARCHITECTURE.md` is updated only for architecture revisions (new REVISE cycles)
- Both documents may legitimately differ; `docs/ARCHITECTURE.md` is current truth

### ROADMAP.md Checkpoints

Every phase exit adds a stable checkpoint entry to `docs/ROADMAP.md`:
```
- `<commit_hash>` (Phase N: <one-line description>)
```

Stable checkpoints are never removed. They form the historical record.

### Documentation-Only Commits

Documentation-only commits (no code change) are permitted and do not require Codex audit.
They do require:
- Accurate content (no speculative claims about unimplemented features)
- Consistency with all other governance documents
- Normal commit and push process

### Stale Content Rule

Documentation must not claim a feature is implemented if it is not yet in production.
Future plans must be labeled as "planned", "blocked on A2", "future", or equivalent.
No document may describe the target A2 state as if it is the current state unless
the relevant phase is complete and deployed.

---

## Appendix: Cross-Reference Map

| Topic | Primary document | Also in |
|---|---|---|
| Owner decisions and policy | `docs/OWNER_DECISIONS.md` | — |
| Human Approval Gates (full) | `docs/OWNER_AGENT_WORKFLOW.md` | `docs/AI_OPERATING_MANUAL.md` (summary) |
| A2 implementation phases | `docs/A2_ARCHITECTURE.md` §15 | `docs/ROADMAP.md` |
| Current architecture | `docs/ARCHITECTURE.md` | `docs/PLATFORM_MAP.md` |
| Phase schedule | `docs/ROADMAP.md` | — |
| Delivery lifecycle and test gates | `docs/WORKFLOW.md` | — |
| AI agent roles and mandatory reading | `docs/AI_OPERATING_MANUAL.md` | `docs/OWNER_AGENT_WORKFLOW.md` |
| Dry Run contract | `docs/OWNER_DECISIONS.md` §Dry Run | `docs/ARCHITECTURE.md` §Safety |
| Safety invariants | `docs/ARCHITECTURE.md` §Critical Safety Invariants | `docs/PLATFORM_MAP.md` §D |
| Scheduling prerequisites | `docs/ROADMAP.md` §S1–S4 | `docs/A2_ARCHITECTURE.md` §15 |
