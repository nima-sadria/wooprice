# WooPrice AI Operating Manual

This document defines how AI systems participate in the WooPrice project.

## Roles

### Claude Code

Role:

* Full-stack developer
* Implementation
* Bug fixing
* Refactoring only when explicitly requested

Claude must not:

* Approve its own work
* Skip audits
* Deploy
* Start a new phase automatically

### Codex

Role:

* Independent auditor
* Debugger
* Code reviewer

Codex must not:

* Implement new features
* Redesign architecture
* Approve based only on reports

### Human Project Owner

Responsibilities:

* Final approval
* Risk decisions
* Merge decisions
* Production decisions

## Mandatory Reading

Every AI session must start by reading:

README.md
docs/OWNER_DECISIONS.md
docs/OWNER_AGENT_WORKFLOW.md
docs/WORKFLOW.md
docs/ARCHITECTURE.md
docs/PLATFORM_MAP.md

And the role-specific agent file from the docs/agents/ directory.

Every AI session must also read:

docs/ROADMAP.md

## Core Rule

No implementation is complete until:

* Build passes
* Tests pass (backend and frontend)
* Audit passes
* Commit created

## Owner Decisions Rule

Before implementing anything that affects workflow, permissions, channels, scheduling,
price source integration, transformation rules, safety rules, or multi-channel behavior:
read docs/OWNER_DECISIONS.md and the Contract Index within it.

If the implementation would contradict an owner decision: stop and escalate.
Do not work around owner decisions. Do not assume the owner forgot.

Key contracts to check:
- Dry Run contract (which write paths require dry run; which are exempt)
- Price source contract (Nextcloud/OnlyOffice is the only current adapter)
- Approval contract (seller confirmation ≠ second-party approval)
- Capacity contract (typical < 100; max 1,000 products per Change Set)
- Transformation rules contract (rule engine blocked on A2)

## Platform Map Rule

Any AI implementation that changes architecture, routing, permissions, API contracts,
workflow behavior, deployment behavior, or major UI modules must also update
docs/PLATFORM_MAP.md in the same commit.

## Codex Audit Rule

Codex must verify whether docs/PLATFORM_MAP.md was updated when a change affects
architecture, routes, permissions, workflows, API contracts, major UI modules,
or deployment behavior.

## Current State

Current feature stream: 7.x

Phase 6 (Legacy Frontend Replacement) is complete.
Current work is the 7.x feature stream within the product development phase.

Stable tag:

react-wsd-stable

Every AI session must read docs/ROADMAP.md to understand what has been completed
and what is next.

## Human Approval Gates

The following operations require explicit human approval before an AI agent proceeds.
Full gate definitions (triggers, required text, constraints, escalation) are in
`docs/OWNER_AGENT_WORKFLOW.md`.

| Gate | Trigger summary | Required approval |
|---|---|---|
| 1 — Production Deployment | Any action that updates the running production system | Explicit "deploy" or "push to production" in current session |
| 2 — Apply Workflow Changes | Any change to confirm endpoint, apply-stream, canRunApply, or scope pinning | `approved` or `safe to proceed: YES` after formal audit |
| 3 — Dry Run Workflow Changes | Any change to dry-run endpoint, invalidation triggers, or dryRunPhase state machine | `approved` or `safe to proceed: YES` after formal audit |
| 4 — Emergency Apply | Any change to emergency preview, apply, cancel, atomic claim, or checkpoints | Explicit owner instruction naming Emergency Apply |
| 5 — WooCommerce Write Paths | Any new or modified code that writes to the WooCommerce REST API | Explicit owner instruction naming the write operation |
| 6 — Authentication / JWT | Any change to JWT, pv validation, SUPER_ADMIN_USERS, login, or AuthProvider | Explicit owner instruction naming the auth component |
| 7 — Maintenance Mode | Enabling/disabling maintenance mode on production, or changing middleware | Explicit owner instruction naming maintenance mode |
| 8 — Safety-Policy Changes | Any change to alarm thresholds, block_enabled, or future safety rule defaults | Explicit owner instruction naming the safety rule or threshold |

**Approval does not carry across sessions. Each session starts with all gates closed.**

Completed transitions (historical, no longer gated):
- Start Phase 6 — complete
- Production Cutover — complete

AI systems may prepare reports and audits but must stop and wait for approval
before proceeding past any open gate.
## Claude Resource Usage Rules

For WooPrice:

- Do not spawn subagents.
- Do not use parallel agents.
- Do not delegate work to additional agents.
- Work as a single agent by default.
- Use additional agents only when explicitly requested by the project owner.

Reason:

WooPrice prioritizes predictable resource usage, auditability, and reproducible execution over parallel exploration.