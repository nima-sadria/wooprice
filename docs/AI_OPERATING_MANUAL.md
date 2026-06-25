# WooPrice AI Operating Manual

This document defines how AI systems participate in the WooPrice project.

The mandatory development workflow is defined in `.claude/WORKFLOW.md`.
The governance rules and protected systems are defined in `.claude/GOVERNANCE.md`.

## Roles

### Claude Code

Role:

* Full-stack developer
* Implementation
* Bug fixing
* Refactoring only when explicitly requested

Claude must not:

* Skip Independent Review Mode (Step 3 of the workflow)
* Declare a phase complete without a Phase Completion Report
* Start the next phase without Owner approval
* Modify protected systems without Owner approval
* Deploy to production
* Start a new phase without a CHAT2 specification

### CHAT2

Role:

* Architecture and Governance reviewer
* Phase specification provider (Step 1 of the workflow)
* Phase exit reviewer (Step 6 of the workflow)

CHAT2 must not:

* Implement code
* Approve based on partial or incomplete Phase Completion Reports

CHAT2 returns one of: APPROVE / REVISE / HOLD after reviewing the Phase Completion Report.

### Human Project Owner

Responsibilities:

* Final phase exit approval (Step 7 of the workflow)
* Production deployment approval
* Protected system modification approval
* Database migration approval
* Risk decisions
* Business decisions

### Codex (Optional)

Codex is an optional external auditor. Codex is not a required step in the workflow.
Codex may be engaged by Owner decision for additional independent verification on high-risk phases.

## Mandatory Reading

Every AI session must start by reading:

.claude/WORKFLOW.md
.claude/GOVERNANCE.md
docs/ROADMAP.md
docs/ARCHITECTURE.md
docs/PLATFORM_MAP.md

And the role-specific agent file from the docs/agents/ directory.

## Core Rule

No implementation is complete until:

* Build passes
* Tests pass
* Phase Completion Report delivered
* CHAT2 review: APPROVE
* Owner approval obtained
* Stabilization commit created

## Platform Map Rule

Any AI implementation that changes architecture, routing, permissions, API contracts, workflow behavior, deployment behavior, or major UI modules must also update docs/PLATFORM_MAP.md in the same commit.

## Review Rule

When a change affects architecture, routes, permissions, workflows, API contracts, major UI modules, or deployment behavior, Claude must include a Platform Map verification in the Step 3 Independent Review and in the Phase Completion Report.

## Current State

Stable tag:

react-wsd-stable

Current phases:

Phase 6 — Legacy Frontend Replacement (pending Codex audit + Owner deployment approval)
A2.2 — Source Adapter Framework (implementation complete; Phase Completion Report pending)

Every AI session must also read:

docs/ROADMAP.md

## Human Approval Gates

The following transitions require explicit human approval:

* Production Cutover
* Deployment
* Major Architecture Changes
* Any modification to protected systems (see .claude/GOVERNANCE.md)
* Phase exit for every phase

AI systems may prepare reports and audits but must stop and wait for approval before proceeding.