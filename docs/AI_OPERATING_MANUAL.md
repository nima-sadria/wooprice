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
docs/WORKFLOW.md
docs/ARCHITECTURE.md
docs/MIGRATION_STATUS.md
docs/PLATFORM_MAP.md

And the role-specific agent file from the docs/agents/ directory.

## Core Rule

No implementation is complete until:

* Build passes
* Tests pass
* Audit passes
* Stabilization commit created

## Platform Map Rule

Any AI implementation that changes architecture, routing, permissions, API contracts, workflow behavior, deployment behavior, or major UI modules must also update docs/PLATFORM_MAP.md in the same commit.

## Codex Audit Rule

Codex must verify whether docs/PLATFORM_MAP.md was updated when a change affects architecture, routes, permissions, workflows, API contracts, major UI modules, or deployment behavior.

## Current State

Stable tag:

react-wsd-stable

Current phase:

Phase 5 — Production Cutover Preparation

Every AI session must also read:

docs/ROADMAP.md

## Human Approval Gates

The following transitions require explicit human approval:

* Start Phase 6
* Production Cutover
* Deployment
* Major Architecture Changes

AI systems may prepare reports and audits but must stop and wait for approval before proceeding.