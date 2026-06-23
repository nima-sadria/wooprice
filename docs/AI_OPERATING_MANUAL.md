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

Before implementing anything that affects workflow, permissions, channels,
scheduling, or spreadsheet integration: read docs/OWNER_DECISIONS.md.

If the implementation would contradict an owner decision: stop and escalate.
Do not work around owner decisions. Do not assume the owner forgot.

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

The following transitions require explicit human approval:

* Start Phase 6 (complete — approved)
* Production Cutover (complete)
* Deployment
* Major Architecture Changes
* Any new channel adapter implementation
* Any scoped permissions implementation

AI systems may prepare reports and audits but must stop and wait for approval
before proceeding past any of the above gates.
## Claude Resource Usage Rules

For WooPrice:

- Do not spawn subagents.
- Do not use parallel agents.
- Do not delegate work to additional agents.
- Work as a single agent by default.
- Use additional agents only when explicitly requested by the project owner.

Reason:

WooPrice prioritizes predictable resource usage, auditability, and reproducible execution over parallel exploration.