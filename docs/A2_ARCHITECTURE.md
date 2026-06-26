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
| A2.4 | Safety Policy Engine | READY FOR OWNER APPROVAL |
| A2.5 | Change Set Engine | CLOSED |
| A2.6 | Dry Run Engine | CLOSED |
| A2.7 | Execution Engine | CLOSED |
| A2.8 | Scheduling Engine | CLOSED |
| A2.9 | AI Foundation | READY FOR OWNER REVIEW |

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

### A2.4 — Safety Policy Engine (READY FOR OWNER APPROVAL)

Enforces business safety policies at the canonical model level: price change thresholds,
stock floor rules, alarm conditions, and operator-configurable block conditions.

### A2.5 — Change Set Engine (CLOSED)

Creates immutable, versioned Change Sets from approved Price Proposals that have passed
Safety Policy evaluation. A ChangeSet is the single authoritative record of what is proposed
to change, for which products, on which channel. Once a revision is created it is immutable;
any modification requires a new ChangeSetRevision. The state machine enforces lifecycle
transitions (DRAFT → READY → SUPERSEDED/ARCHIVED). Digest is a deterministic SHA-256 over
all item bindings (proposal_hash, safety_result_id, rule_version_id, product_id), destination
channel, scope, and source_snapshot_id — excluding UUIDs and timestamps.

Deliverables:
- `app/a2/models/change_set.py` — ChangeSet, ChangeSetRevision, ChangeSetItem ORM models
- `app/a2/repositories/change_set_repository.py` — ChangeSetRepository: CRUD, state machine, revision management
- `app/a2/services/change_set_service.py` — ChangeSetService: build, create_revision, transition, verify_digest; compute_change_set_digest
- `app/a2/services/__init__.py` — services package
- `alembic_a2/versions/a2_004_change_set_engine.py` — 3 a2_-prefixed tables (a2_change_sets, a2_change_set_revisions, a2_change_set_items); Numeric(14,4) for prices
- `tests/a2/test_a2_change_set.py` — 71 tests (digest determinism, revision immutability, state machine, repository CRUD, migration lineage, isolation)

### A2.6 — Dry Run Engine (CLOSED)

Validates a Change Set against safety policies and returns a structured dry-run result
(PASS / WARN / BLOCK) without writing to any external system.

The Dry Run Engine is completely read-only with respect to destination systems. It consumes
an immutable Change Set, verifies the Change Set digest, validates each item for completeness
and consistency, and produces an advisory DryRunReport. Seller confirmation is bound to the
exact Change Set digest; any change to proposals, safety results, rule versions, destination
channel, scope, or source snapshot invalidates the confirmation.

Deliverables:
- `app/a2/models/dry_run.py` — DryRun, DryRunResult, SellerConfirmation ORM models
- `app/a2/repositories/dry_run_repository.py` — DryRunRepository: CRUD, confirmation management
- `app/a2/services/dry_run_service.py` — DryRunService: execute/generate_report/confirm/invalidate; DryRunItemInput + DryRunReport dataclasses
- `alembic_a2/versions/a2_005_dry_run_engine.py` — migration a2_005 (3 a2_-prefixed tables; down_revision=a2_004)
- `tests/a2/test_a2_dry_run.py` — 73 tests (digest verification, item validation, confirmation invalidation scenarios, migration lineage, isolation)

### A2.7 — Execution Engine (CLOSED)

Executes approved, confirmed, immutable Change Sets through a controlled adapter interface.
The Execution Engine enforces five sequential prerequisites before processing any item:
(1) valid SellerConfirmation, (2) confirmation digest equals Change Set digest,
(3) Dry Run result is not BLOCK, (4) Dry Run digest_verified is True, (5) independent
digest recomputation from items matches the stored digest.

Live freshness is verified per item immediately before execution via the adapter. Freshness
failure hard-blocks the item (BLOCKED) and the overall execution (BLOCKED). Retry handles
transient adapter failures. Idempotency keys prevent duplicate execution records and
duplicate item records. Stale RUNNING detection (recovery foundation) is implemented
without automatic recovery.

A2.7 scope constraint: Real WooCommerce write APIs are NOT connected in this phase.
All execution goes through DummyExecutionAdapter (simulation only, no network calls).
No existing Workspace Apply or WooCommerce write logic is modified.

Deliverables:
- `app/a2/models/execution.py` — Execution, ExecutionBatch, ExecutionItem, ExecutionAttempt ORM models
- `app/a2/repositories/execution_repository.py` — ExecutionRepository: state machine, idempotency, stale detection
- `app/a2/services/execution_service.py` — ExecutionService: orchestrates execution lifecycle; ChannelExecutionAdapter ABC; DummyExecutionAdapter (test/simulation only); ExecutionItemInput, FreshnessContext, FreshnessResult, ExecuteItemResult, ExecutionReport dataclasses
- `alembic_a2/versions/a2_006_execution_engine.py` — migration a2_006 (down_revision=a2_005); 4 a2_-prefixed tables
- `tests/a2/test_a2_execution.py` — 72 tests (prerequisites, freshness, outcomes, idempotency, retry, state machine, terminal states, cancel, recovery, repository, report, migration, isolation)

### A2.8 — Scheduling Engine (CLOSED)

Enables deferred execution of an already-confirmed, immutable Change Set through the
A2.7 Execution Engine. The Scheduling Engine is a time-based triggering layer only —
it never authorizes execution by itself, never re-evaluates rules or safety policies,
and never modifies the Change Set it schedules.

A2.7 remains the authoritative validation layer: confirmation digest, Change Set digest,
Dry Run state, item freshness, and idempotency are all independently verified by A2.7
on every dispatch. Scheduling cannot override or bypass those checks.

Lease ownership enforces single-executor guarantee (one worker per run at a time).
Expired leases may be reclaimed. Heartbeats extend active leases. Retry/backoff policy
tracks attempt count and schedules next_run_at after failure. Stale lease detection
enables operator recovery of abandoned runs.

A2.8 scope constraint: No real WooCommerce write APIs connected. No ChannelExecutionAdapter
implementation in A2.8 production code. No existing Workspace or Apply workflow modified.

Deliverables:
- `app/a2/models/schedule.py` — Schedule, ScheduleRun, ScheduleLease ORM models
- `app/a2/repositories/scheduler_repository.py` — SchedulerRepository: state machines, lease acquisition, heartbeat, stale detection, retry
- `app/a2/services/scheduler_service.py` — SchedulerService: orchestrates lifecycle; dispatch contract to A2.7 ExecutionService
- `alembic_a2/versions/a2_007_scheduling_engine.py` — migration a2_007 (down_revision=a2_006); 3 a2_-prefixed tables
- `tests/a2/test_a2_scheduling.py` — 38 tests, all pass

### A2.9 — AI Foundation (READY FOR OWNER REVIEW)

Provides advisory intelligence that assists pricing decisions while remaining completely
outside the Trusted Execution Path. The AI Foundation is advisory only — it never
participates in deterministic execution, never authorizes a Change Set, never triggers
execution or scheduling, and never writes to any destination channel.

All AI output is a single object type: AdvisoryInsight. No executable domain objects
(PriceProposal, ChangeSet, DryRunResult, ExecutionPlan, Schedule, ApplyCommand) are
ever produced by A2.9 components.

Prior phases (Rule Engine, Safety Engine, Change Set Engine, Dry Run Engine, Execution
Engine, Scheduling Engine) must never import from `app.a2.ai`. The dependency is
one-way: AI may read prior-phase outputs; prior phases must never depend on AI.

Deliverables:
- `app/a2/ai/__init__.py` — AI Foundation package (isolation boundary declared)
- `app/a2/ai/models.py` — AdvisorySession, AdvisoryInsight ORM models; plain-string
  subject_id and related_object_id (phase independence — no FK to prior-phase tables)
- `app/a2/ai/repository.py` — AdvisoryRepository: create_session, store_insight,
  list_insights, get_session, archive_session
- `app/a2/ai/service.py` — AdvisoryService: generate_explanation, generate_risk_summary,
  detect_anomaly, detect_stale_price, assign_review_priority, generate_rule_recommendation
- `alembic_a2/versions/a2_008_ai_foundation.py` — migration a2_008 (down_revision=a2_007);
  2 a2_-prefixed tables (a2_advisory_sessions, a2_advisory_insights)
- `tests/a2/test_a2_advisory.py` — 51 tests, all pass

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
