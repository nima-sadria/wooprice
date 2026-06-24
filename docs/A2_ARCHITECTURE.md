# WooPrice A2 Architecture

## A2 Governance

| Area | Status |
|---|---|
| Governance | PASS |
| A2 Architecture | APPROVED |
| A2.1 — Canonical Product Model + PostgreSQL Foundation | COMPLETE |
| A2.2 — Source Adapter Framework | IN PROGRESS |

---

## A2 Phase Sequence

| Phase | Name | Status |
|---|---|---|
| A2.1 | Canonical Product Model + PostgreSQL Foundation | COMPLETE |
| A2.2 | Source Adapter Framework | IN PROGRESS |
| A2.3 | Transformation Rule Engine | NOT STARTED |
| A2.4 | Safety Policy Engine | NOT STARTED |
| A2.5 | Change Set Engine | NOT STARTED |
| A2.6 | Dry Run Engine | NOT STARTED |
| A2.7 | Execution Engine | NOT STARTED |
| A2.8 | Scheduling Engine | NOT STARTED |
| A2.9 | AI Foundation | NOT STARTED |

---

## A2 Phase Descriptions

### A2.1 — Canonical Product Model + PostgreSQL Foundation (COMPLETE)

Establishes the normalized product schema in PostgreSQL and the migration tooling required
by all subsequent A2 phases. This is the foundational layer on which A2.2 through A2.9 are
built.

Deliverables:
- PostgreSQL schema for canonical product representation
- docker-compose.a2.yml override file defining PostgreSQL service
- Migration tooling and seed scripts
- Verification that the default stack (`docker compose up -d`) remains unaffected

### A2.2 — Source Adapter Framework (IN PROGRESS)

Defines the adapter interface for ingesting product data from heterogeneous sources
(WooCommerce REST API, spreadsheet, direct DB) into the canonical product model.

### A2.3 — Transformation Rule Engine (NOT STARTED)

Implements the rule pipeline that transforms raw source data into normalized canonical
records, applying field mappings, type coercions, and enrichment logic.

### A2.4 — Safety Policy Engine (NOT STARTED)

Enforces business safety policies at the canonical model level: price change thresholds,
stock floor rules, alarm conditions, and operator-configurable block conditions.

### A2.5 — Change Set Engine (NOT STARTED)

Computes the delta between the current canonical state and the proposed new state,
producing a typed, immutable change set ready for validation and execution.

### A2.6 — Dry Run Engine (NOT STARTED)

Validates a change set against safety policies and returns a structured dry-run result
(passed / warnings / blocked) without writing to any external system.

### A2.7 — Execution Engine (NOT STARTED)

Applies an approved change set to WooCommerce and updates the canonical model, writing
audit and change-history records for every mutation.

### A2.8 — Scheduling Engine (NOT STARTED)

Provides cron-based and event-triggered scheduling for automated source ingestion,
transformation, dry run, and execution pipelines.

### A2.9 — AI Foundation (NOT STARTED)

Integrates AI-assisted capabilities: anomaly detection on proposed changes, natural-language
query over canonical product history, and suggested pricing actions.

---

## A2 Infrastructure

### PostgreSQL Compose Path

A2 PostgreSQL services are isolated in an override file so the default production stack
remains unmodified.

```
# Default production stack — no PostgreSQL
docker compose up -d

# A2 stack — includes PostgreSQL
docker compose -f docker-compose.yml -f docker-compose.a2.yml up -d
```

The `docker-compose.a2.yml` file is introduced in A2.1. It must never be referenced
or required by `docker-compose.yml` itself. The two files compose additively.

### Database Isolation

| Store | Engine | Scope |
|---|---|---|
| `wooprice.db` | SQLite | Current production — all phases up to A2.0 |
| A2 PostgreSQL | PostgreSQL | A2 track only; not used by current FastAPI app |

The SQLite database is not modified by any A2 phase. A2 phases operate on the PostgreSQL
schema exclusively until an explicit migration phase promotes PostgreSQL as the primary store.

---

## A2 Entry Gate Requirements

The following conditions must hold before any A2.2 implementation begins:

- [x] A2.1 Exit Gate audit: PASS
- [x] A2 Architecture approval status: APPROVED (confirmed above)
- [x] Governance status: PASS (confirmed above)
- [x] All A2.1 documentation inconsistencies: RESOLVED

---

## Cross-Document References

| Document | A2 Coverage |
|---|---|
| `docs/ROADMAP.md` | A2 Track section — governance, phase status table, compose path |
| `docs/ARCHITECTURE.md` | A2 Track section — governance, phase sequence, compose path |
| `docs/PLATFORM_MAP.md` | Section H — governance, phase sequence, compose path |
| `docs/A2_ARCHITECTURE.md` | This document — authoritative A2 reference |
