# WooPrice A2 Architecture

## A2 Governance

| Area | Status |
|---|---|
| Governance | PASS |
| A2 Architecture | APPROVED |
| A2.1 — Canonical Product Model + PostgreSQL Foundation | CLOSED |
| A2.2 — Source Adapter Framework | CLOSED |
| A2.3 — Transformation Rule Engine | CLOSED |

---

## A2 Phase Sequence

| Phase | Name | Status |
|---|---|---|
| A2.1 | Canonical Product Model + PostgreSQL Foundation | CLOSED |
| A2.2 | Source Adapter Framework | CLOSED |
| A2.3 | Transformation Rule Engine | CLOSED |
| A2.4 | Safety Policy Engine | READY FOR OWNER REVIEW |
| A2.5 | Change Set Engine | NOT STARTED |
| A2.6 | Dry Run Engine | NOT STARTED |
| A2.7 | Execution Engine | NOT STARTED |
| A2.8 | Scheduling Engine | NOT STARTED |
| A2.9 | AI Foundation | NOT STARTED |

---

## A2 Phase Descriptions

### A2.1 — Canonical Product Model + PostgreSQL Foundation (CLOSED)

Establishes the normalized product schema in PostgreSQL and the migration tooling required
by all subsequent A2 phases. This is the foundational layer on which A2.2 through A2.9 are
built.

Deliverables:
- PostgreSQL schema for canonical product representation
- docker-compose.a2.yml override file defining PostgreSQL service
- Migration tooling and seed scripts
- Verification that the default stack (`docker compose up -d`) remains unaffected

### A2.2 — Source Adapter Framework (CLOSED)

Defines the adapter interface for ingesting product data from heterogeneous sources
(WooCommerce REST API, spreadsheet, direct DB) into the canonical product model.

### A2.3 — Transformation Rule Engine (CLOSED)

Implements the deterministic, reproducible price proposal pipeline. The Rule Engine
accepts published RuleVersions and source inputs (cost + currency), evaluates formulas
via an AST-based sandboxed evaluator (no eval/exec), and persists a PriceProposal with
full ProposalProvenance and ExecutionTrace. Identical inputs always produce the same
proposal_hash (determinism guarantee — hash excludes UUID and timestamp). Every proposal
is fully re-derivable from stored provenance (reproducibility guarantee). Rule versions
are immutable once published; parameter changes create new versions. The engine supports
5 rule types: cost_plus, fx_based, fee_based, formula, competition.

A2.3-R2 reconciles the REMOTE AST engine design with the LOCAL audit/provenance model.

Deliverables:
- `app/a2/rules/base.py` — RuleType enum (5 values), RuleDefinition frozen dataclass
- `app/a2/rules/formula.py` — AST-based sandboxed evaluator (Decimal arithmetic, no eval/exec)
- `app/a2/rules/engine.py` — RuleEngine: propose() / propose_all() returning ProposalEnvelope
- `app/a2/rules/proposal.py` — compute_proposal_hash (deterministic, excludes UUID/timestamp)
- `app/a2/models/pricing_rule.py` — PricingRule ORM model (table: a2_pricing_rules)
- `app/a2/models/pricing_rule_version.py` — PricingRuleVersion ORM model (is_published immutability)
- `app/a2/models/price_proposal.py` — PriceProposalRecord, ProposalProvenanceRecord, ExecutionTraceRecord
- `app/a2/repositories/rule_repository.py` — CRUD + publish_version() immutability guard + load_active_definitions()
- `app/a2/repositories/proposal_repository.py` — save(envelope) + find_by_hash() deduplication
- `alembic_a2/versions/a2_002_r2_transformation_rule_engine.py` — 5 a2_-prefixed tables (Numeric(14,4))
- `tests/a2/test_a2_rule_formula.py` — 35 tests (AST sandbox, arithmetic, extract_variables)
- `tests/a2/test_a2_proposal.py` — 14 tests (hash determinism, UUID/timestamp exclusion)
- `tests/a2/test_a2_rule_engine.py` — 38 tests (5 rule types, ProposalEnvelope, provenance, trace, migration)
- `tests/a2/test_a2_rule_repository.py` — 25 tests (CRUD, publish immutability, set_current_version)
- `tests/a2/test_a2_rules_isolation.py` — 14 tests (no WooCommerce, no eval/exec, scope isolation)

### A2.4 — Safety Policy Engine (READY FOR OWNER REVIEW)

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
