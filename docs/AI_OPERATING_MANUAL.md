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

And the role-specific file from docs/agents.

## Core Rule

No implementation is complete until:

* Build passes
* Tests pass
* Audit passes
* Stabilization commit created

## Current State

Stable tag:

react-wsd-stable

Current phase:

Phase 5 — Production Cutover Preparation
