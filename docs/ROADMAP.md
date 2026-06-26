# WooPrice Roadmap

## Current Status

Current Stable Tag:

react-wsd-stable

Current Branch:

main

Latest Stable Commit:

5a2eeff

## Completed

* Phase 1
* Phase 2
* Phase 3
* Analytics Migration
* Auth Integration
* Direction Layer
* Logs Migration
* WS-A
* WS-B
* WS-C
* WS-D
* Documentation System
* AI Operating Manual
* Agent path fix (docs/agents/)

## Current Phase

Phase 6

Legacy Frontend Replacement

Status:

Implementation complete — pending Codex audit

Goals achieved:

* `.gitignore`: `static/assets/` excluded
* `Dockerfile`: two targeted COPY lines (dist/assets → static/assets; dist/index.html → static/index.html)
* `app/main.py`: `/assets/` static mount added
* `app/main.py`: SPA catch-all route appended (last route in file)
* `static/index.html`: replaced with React SPA entry point (700 bytes)
* Build verified: PASS — 0 TS errors
* Tests verified: 47 passed

Not performed (Phase 6 constraint — no deployment):

* `docker compose up -d --build`
* Production cutover
* Smoke test execution

Pending:

* Codex audit of Phase 6 stabilization commit
* Project owner approval for deployment

## Completed Phases (summary)

* Phase 5 — Production Cutover Preparation: Complete (commit 377acae)

## Upcoming

Phase 6 deployment

Prerequisites:

* Codex audit of Phase 6 changes passed
* Project owner approval

## Open Findings

### Medium

* WS-C M1
* WS-C M2
* WS-C M3

### Low

* WS-C L1
* WS-C L2
* WS-C L3
* WS-C L4

## A2 Track

A2 is the multi-phase data platform extension. It runs in parallel with the frontend
feature stream (7.x/8.x) and has its own governance gate.

### A2 Governance

| Area | Status |
|---|---|
| Governance | PASS |
| A2 Architecture | APPROVED |

### A2 Phase Status

| Phase | Name | Status |
|---|---|---|
| A2.1 | Canonical Product Model + PostgreSQL Foundation | CLOSED |
| A2.2 | Source Adapter Framework | CLOSED |
| A2.3 | Transformation Rule Engine | CLOSED |
| A2.4 | Safety Policy Engine | READY FOR OWNER APPROVAL |
| A2.5 | Change Set Engine | CLOSED |
| A2.6 | Dry Run Engine | CLOSED |
| A2.7 | Execution Engine | CLOSED |
| A2.8 | Scheduling Engine | CLOSED |
| A2.9 | AI Foundation | READY FOR OWNER REVIEW |

Architecture reference: `docs/A2_ARCHITECTURE.md`

### A2 PostgreSQL Compose Path

The default production stack does **not** include A2 PostgreSQL services.

```
# Default production stack (no PostgreSQL)
docker compose up -d

# A2 stack (includes PostgreSQL)
docker compose -f docker-compose.yml -f docker-compose.a2.yml up -d
```

---

## Stable Checkpoints

* react-wsd-stable
* 75c4be2
* 6fdd894
* 6bb8342
* 4ef73a8
* 5a2eeff (Phase 5 documentation stabilization)
* 377acae (Phase 5 Codex remediation — all findings resolved)
