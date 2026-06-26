"""
A2.3-R2 — Rule Engine tests.

Covers:
  - All 5 rule types (cost_plus, fx_based, fee_based, formula, competition)
  - Rule precedence (ascending priority order)
  - Missing-input skip behaviour
  - propose() / propose_all()
  - ProposalEnvelope structure (proposal + 3 trace steps)
  - Determinism: same inputs → same proposal_hash
  - Determinism: hash excludes UUID and timestamp
  - Equal-priority rule stable secondary ordering (rule_id as tiebreaker)
  - Proposal provenance persistence
  - Execution trace persistence (3 steps per proposal)
  - Alembic migration a2_002_r2 (upgrade / downgrade / lineage)
"""
import os
os.environ.setdefault("A2_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("NEXTCLOUD_URL", "http://example.invalid")
os.environ.setdefault("NEXTCLOUD_USER", "x")
os.environ.setdefault("NEXTCLOUD_PASSWORD", "x")
os.environ.setdefault("NEXTCLOUD_FILE_PATH", "/x.xlsx")
os.environ.setdefault("WC_URL", "http://example.invalid")
os.environ.setdefault("WC_KEY", "x")
os.environ.setdefault("WC_SECRET", "x")

import json
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.a2.database import A2Base
import app.a2.models.canonical_product  # noqa: F401
import app.a2.models.source             # noqa: F401
import app.a2.models.snapshot           # noqa: F401
import app.a2.models.provenance         # noqa: F401
import app.a2.models.checkpoint         # noqa: F401
import app.a2.models.pricing_rule       # noqa: F401
import app.a2.models.pricing_rule_version  # noqa: F401
import app.a2.models.price_proposal     # noqa: F401

from app.a2.rules.base import RuleDefinition, RuleType
from app.a2.rules.engine import NoApplicableRuleError, ProposalEnvelope, RuleEngine
from app.a2.repositories.proposal_repository import ProposalRepository
from app.a2.repositories.rule_repository import RuleRepository

_FIXED_TS = datetime(2026, 6, 26, 12, 0, 0, tzinfo=timezone.utc)

ENGINE = RuleEngine()


def _rule(
    *,
    rule_id: str = "rule-001",
    rule_name: str = "Test Rule",
    rule_type: str = RuleType.COST_PLUS.value,
    priority: int = 10,
    version_id: str = "ver-001",
    version_number: int = 1,
    formula: str = "cost * 1.20",
    required_inputs: list[str] | None = None,
) -> RuleDefinition:
    if required_inputs is None:
        required_inputs = ["cost"]
    return RuleDefinition(
        rule_id=rule_id,
        rule_name=rule_name,
        rule_type=rule_type,
        priority=priority,
        version_id=version_id,
        version_number=version_number,
        formula=formula,
        required_inputs=required_inputs,
    )


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def db_engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    A2Base.metadata.create_all(eng)
    yield eng
    A2Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture()
def db(db_engine):
    Session = sessionmaker(bind=db_engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def rule_repo(db):
    return RuleRepository(db)


@pytest.fixture()
def proposal_repo(db):
    return ProposalRepository(db)


# ── Rule types ────────────────────────────────────────────────────────────────

def test_propose_cost_plus():
    rule = _rule(formula="cost * 1.20", required_inputs=["cost"])
    env = ENGINE.propose(
        rules=[rule],
        canonical_product_id="prod-001",
        source_id="src-001",
        snapshot_id="snap-001",
        input_values={"cost": Decimal("100000")},
        currency="IDR",
        generated_at=_FIXED_TS,
    )
    assert env.proposal.proposed_price == Decimal("100000") * Decimal("1.20")
    assert env.proposal.currency == "IDR"
    assert env.proposal.rule_id == "rule-001"


def test_propose_fx_based():
    rule = _rule(
        rule_type=RuleType.FX_BASED.value,
        formula="cost * fx_rate",
        required_inputs=["cost", "fx_rate"],
    )
    env = ENGINE.propose(
        rules=[rule],
        canonical_product_id="prod-002",
        source_id="src-001",
        snapshot_id="snap-001",
        input_values={"cost": Decimal("100"), "fx_rate": Decimal("15000")},
        currency="IDR",
        generated_at=_FIXED_TS,
    )
    assert env.proposal.proposed_price == Decimal("1500000")


def test_propose_fee_based():
    rule = _rule(
        rule_type=RuleType.FEE_BASED.value,
        formula="(cost + fee) * 1.10",
        required_inputs=["cost", "fee"],
    )
    env = ENGINE.propose(
        rules=[rule],
        canonical_product_id="prod-003",
        source_id="src-001",
        snapshot_id="snap-001",
        input_values={"cost": Decimal("100000"), "fee": Decimal("5000")},
        currency="IDR",
        generated_at=_FIXED_TS,
    )
    assert env.proposal.proposed_price == (Decimal("100000") + Decimal("5000")) * Decimal("1.10")


def test_propose_competition():
    rule = _rule(
        rule_type=RuleType.COMPETITION.value,
        formula="competitor_price * 0.95",
        required_inputs=["competitor_price"],
    )
    env = ENGINE.propose(
        rules=[rule],
        canonical_product_id="prod-004",
        source_id="src-001",
        snapshot_id="snap-001",
        input_values={"competitor_price": Decimal("200000")},
        currency="IDR",
        generated_at=_FIXED_TS,
    )
    assert env.proposal.proposed_price == Decimal("200000") * Decimal("0.95")


def test_propose_formula_type():
    rule = _rule(
        rule_type=RuleType.FORMULA.value,
        formula="cost * fx_rate + fee",
        required_inputs=["cost", "fx_rate", "fee"],
    )
    env = ENGINE.propose(
        rules=[rule],
        canonical_product_id="prod-005",
        source_id="src-001",
        snapshot_id="snap-001",
        input_values={"cost": Decimal("10"), "fx_rate": Decimal("15000"), "fee": Decimal("500")},
        currency="IDR",
        generated_at=_FIXED_TS,
    )
    assert env.proposal.proposed_price == Decimal("10") * Decimal("15000") + Decimal("500")


# ── ProposalEnvelope structure ─────────────────────────────────────────────────

def test_propose_returns_envelope():
    rule = _rule()
    result = ENGINE.propose(
        rules=[rule],
        canonical_product_id="p",
        source_id="s",
        snapshot_id="sn",
        input_values={"cost": Decimal("100000")},
        currency="IDR",
        generated_at=_FIXED_TS,
    )
    assert isinstance(result, ProposalEnvelope)
    assert result.proposal is not None
    assert len(result.trace) == 3


def test_envelope_trace_step_names():
    rule = _rule()
    env = ENGINE.propose(
        rules=[rule],
        canonical_product_id="p",
        source_id="s",
        snapshot_id="sn",
        input_values={"cost": Decimal("100000")},
        currency="IDR",
        generated_at=_FIXED_TS,
    )
    names = [t.step_name for t in env.trace]
    assert names == ["input_capture", "formula_evaluation", "hash_computation"]


def test_envelope_trace_step_order():
    rule = _rule()
    env = ENGINE.propose(
        rules=[rule],
        canonical_product_id="p",
        source_id="s",
        snapshot_id="sn",
        input_values={"cost": Decimal("100000")},
        currency="IDR",
        generated_at=_FIXED_TS,
    )
    orders = [t.step_order for t in env.trace]
    assert orders == [1, 2, 3]


def test_envelope_trace_formula_step_records_formula():
    rule = _rule(formula="cost * 1.5")
    env = ENGINE.propose(
        rules=[rule],
        canonical_product_id="p",
        source_id="s",
        snapshot_id="sn",
        input_values={"cost": Decimal("100000")},
        currency="IDR",
        generated_at=_FIXED_TS,
    )
    formula_step = next(t for t in env.trace if t.step_name == "formula_evaluation")
    assert formula_step.step_formula == "cost * 1.5"


def test_envelope_trace_json_is_valid():
    rule = _rule()
    env = ENGINE.propose(
        rules=[rule],
        canonical_product_id="p",
        source_id="s",
        snapshot_id="sn",
        input_values={"cost": Decimal("100000")},
        currency="IDR",
        generated_at=_FIXED_TS,
    )
    for step in env.trace:
        json.loads(step.step_input_json)
        json.loads(step.step_output_json)


def test_proposal_has_all_required_fields():
    rule = _rule()
    env = ENGINE.propose(
        rules=[rule],
        canonical_product_id="prod-prov",
        source_id="src-prov",
        snapshot_id="snap-prov",
        input_values={"cost": Decimal("100000")},
        currency="IDR",
        generated_at=_FIXED_TS,
    )
    p = env.proposal
    assert p.proposal_id
    assert p.canonical_product_id == "prod-prov"
    assert p.source_id == "src-prov"
    assert p.snapshot_id == "snap-prov"
    assert p.rule_id == "rule-001"
    assert p.rule_version == 1
    assert p.rule_version_id == "ver-001"
    assert p.proposed_price is not None
    assert p.currency == "IDR"
    assert p.generated_at == _FIXED_TS
    assert p.input_values == {"cost": "100000"}
    assert p.proposal_hash
    assert len(p.proposal_hash) == 64


def test_proposal_is_immutable():
    rule = _rule()
    env = ENGINE.propose(
        rules=[rule],
        canonical_product_id="p",
        source_id="s",
        snapshot_id="sn",
        input_values={"cost": Decimal("100000")},
        currency="IDR",
        generated_at=_FIXED_TS,
    )
    with pytest.raises(Exception):
        env.proposal.proposed_price = Decimal("999")  # type: ignore[misc]


def test_proposal_input_values_stored_as_strings():
    rule = _rule(formula="cost * fx_rate", required_inputs=["cost", "fx_rate"])
    env = ENGINE.propose(
        rules=[rule],
        canonical_product_id="p",
        source_id="s",
        snapshot_id="sn",
        input_values={"cost": Decimal("100"), "fx_rate": Decimal("15000")},
        currency="IDR",
        generated_at=_FIXED_TS,
    )
    assert isinstance(env.proposal.input_values["cost"], str)
    assert isinstance(env.proposal.input_values["fx_rate"], str)


# ── Rule precedence ────────────────────────────────────────────────────────────

def test_highest_priority_wins():
    low = _rule(rule_id="low", priority=20, formula="cost * 1.10", required_inputs=["cost"])
    high = _rule(rule_id="high", priority=5, formula="cost * 1.50", required_inputs=["cost"])
    env = ENGINE.propose(
        rules=[low, high],
        canonical_product_id="prod-006",
        source_id="src",
        snapshot_id="snap",
        input_values={"cost": Decimal("100000")},
        currency="IDR",
        generated_at=_FIXED_TS,
    )
    assert env.proposal.rule_id == "high"
    assert env.proposal.proposed_price == Decimal("150000")


def test_priority_order_is_ascending():
    r1 = _rule(rule_id="r1", priority=1, formula="cost * 2", required_inputs=["cost"])
    r2 = _rule(rule_id="r2", priority=10, formula="cost * 3", required_inputs=["cost"])
    r3 = _rule(rule_id="r3", priority=100, formula="cost * 4", required_inputs=["cost"])
    env = ENGINE.propose(
        rules=[r3, r1, r2],  # shuffled
        canonical_product_id="prod-007",
        source_id="src",
        snapshot_id="snap",
        input_values={"cost": Decimal("1000")},
        currency="IDR",
        generated_at=_FIXED_TS,
    )
    assert env.proposal.rule_id == "r1"
    assert env.proposal.proposed_price == Decimal("2000")


def test_equal_priority_uses_rule_id_as_tiebreaker():
    """Equal-priority rules must select deterministically by rule_id."""
    r_a = _rule(rule_id="aaa", priority=10, formula="cost * 1.10", required_inputs=["cost"])
    r_b = _rule(rule_id="bbb", priority=10, formula="cost * 1.20", required_inputs=["cost"])
    env1 = ENGINE.propose(
        rules=[r_a, r_b],
        canonical_product_id="p",
        source_id="s",
        snapshot_id="sn",
        input_values={"cost": Decimal("100")},
        currency="IDR",
        generated_at=_FIXED_TS,
    )
    env2 = ENGINE.propose(
        rules=[r_b, r_a],  # reversed order
        canonical_product_id="p",
        source_id="s",
        snapshot_id="sn",
        input_values={"cost": Decimal("100")},
        currency="IDR",
        generated_at=_FIXED_TS,
    )
    assert env1.proposal.rule_id == env2.proposal.rule_id  # stable tiebreaker


def test_rule_with_missing_inputs_is_skipped():
    no_fx = _rule(
        rule_id="no-fx",
        priority=1,
        formula="cost * fx_rate",
        required_inputs=["cost", "fx_rate"],
    )
    fallback = _rule(
        rule_id="fallback",
        priority=2,
        formula="cost * 1.20",
        required_inputs=["cost"],
    )
    env = ENGINE.propose(
        rules=[no_fx, fallback],
        canonical_product_id="prod-008",
        source_id="src",
        snapshot_id="snap",
        input_values={"cost": Decimal("100000")},  # no fx_rate
        currency="IDR",
        generated_at=_FIXED_TS,
    )
    assert env.proposal.rule_id == "fallback"


def test_all_rules_missing_inputs_raises():
    r1 = _rule(rule_id="r1", priority=1, formula="fx_rate * 1000", required_inputs=["fx_rate"])
    r2 = _rule(rule_id="r2", priority=2, formula="competitor_price * 0.9", required_inputs=["competitor_price"])
    with pytest.raises(NoApplicableRuleError):
        ENGINE.propose(
            rules=[r1, r2],
            canonical_product_id="prod-009",
            source_id="src",
            snapshot_id="snap",
            input_values={"cost": Decimal("50000")},
            currency="IDR",
            generated_at=_FIXED_TS,
        )


def test_empty_rules_raises():
    with pytest.raises(NoApplicableRuleError):
        ENGINE.propose(
            rules=[],
            canonical_product_id="prod-010",
            source_id="src",
            snapshot_id="snap",
            input_values={"cost": Decimal("100000")},
            currency="IDR",
            generated_at=_FIXED_TS,
        )


# ── propose_all ────────────────────────────────────────────────────────────────

def test_propose_all_returns_all_applicable():
    r1 = _rule(rule_id="r1", priority=1, formula="cost * 1.10", required_inputs=["cost"])
    r2 = _rule(rule_id="r2", priority=2, formula="cost * 1.20", required_inputs=["cost"])
    r3 = _rule(rule_id="r3", priority=3, formula="competitor_price * 0.9", required_inputs=["competitor_price"])
    envs = ENGINE.propose_all(
        rules=[r1, r2, r3],
        canonical_product_id="p",
        source_id="s",
        snapshot_id="sn",
        input_values={"cost": Decimal("100000")},  # r3 skipped: no competitor_price
        currency="IDR",
        generated_at=_FIXED_TS,
    )
    assert len(envs) == 2
    assert envs[0].proposal.rule_id == "r1"
    assert envs[1].proposal.rule_id == "r2"


def test_propose_all_empty_when_no_inputs_match():
    r1 = _rule(rule_id="r1", priority=1, formula="fx_rate", required_inputs=["fx_rate"])
    envs = ENGINE.propose_all(
        rules=[r1],
        canonical_product_id="p",
        source_id="s",
        snapshot_id="sn",
        input_values={"cost": Decimal("100000")},
        currency="IDR",
        generated_at=_FIXED_TS,
    )
    assert envs == []


def test_propose_all_each_envelope_has_trace():
    r1 = _rule(rule_id="r1", priority=1, formula="cost * 1.10", required_inputs=["cost"])
    r2 = _rule(rule_id="r2", priority=2, formula="cost * 1.20", required_inputs=["cost"])
    envs = ENGINE.propose_all(
        rules=[r1, r2],
        canonical_product_id="p",
        source_id="s",
        snapshot_id="sn",
        input_values={"cost": Decimal("100000")},
        currency="IDR",
        generated_at=_FIXED_TS,
    )
    for env in envs:
        assert len(env.trace) == 3


# ── Determinism ────────────────────────────────────────────────────────────────

def test_same_inputs_produce_same_hash():
    rule = _rule()
    env1 = ENGINE.propose(
        rules=[rule],
        canonical_product_id="prod-det",
        source_id="src",
        snapshot_id="snap",
        input_values={"cost": Decimal("100000")},
        currency="IDR",
        generated_at=_FIXED_TS,
    )
    env2 = ENGINE.propose(
        rules=[rule],
        canonical_product_id="prod-det",
        source_id="src",
        snapshot_id="snap",
        input_values={"cost": Decimal("100000")},
        currency="IDR",
        generated_at=_FIXED_TS,
    )
    assert env1.proposal.proposal_hash == env2.proposal.proposal_hash


def test_hash_does_not_depend_on_uuid():
    """Two proposals for same inputs must have same hash regardless of proposal_id UUID."""
    rule = _rule()
    env1 = ENGINE.propose(
        rules=[rule],
        canonical_product_id="p",
        source_id="s",
        snapshot_id="sn",
        input_values={"cost": Decimal("100000")},
        currency="IDR",
        generated_at=_FIXED_TS,
    )
    env2 = ENGINE.propose(
        rules=[rule],
        canonical_product_id="p",
        source_id="s",
        snapshot_id="sn",
        input_values={"cost": Decimal("100000")},
        currency="IDR",
        generated_at=_FIXED_TS,
    )
    assert env1.proposal.proposal_id != env2.proposal.proposal_id  # UUIDs differ
    assert env1.proposal.proposal_hash == env2.proposal.proposal_hash  # hashes match


def test_hash_does_not_depend_on_generated_at():
    """Two proposals for same inputs at different timestamps must have same hash."""
    rule = _rule()
    ts1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    ts2 = datetime(2026, 12, 31, tzinfo=timezone.utc)
    env1 = ENGINE.propose(
        rules=[rule],
        canonical_product_id="p",
        source_id="s",
        snapshot_id="sn",
        input_values={"cost": Decimal("100000")},
        currency="IDR",
        generated_at=ts1,
    )
    env2 = ENGINE.propose(
        rules=[rule],
        canonical_product_id="p",
        source_id="s",
        snapshot_id="sn",
        input_values={"cost": Decimal("100000")},
        currency="IDR",
        generated_at=ts2,
    )
    assert env1.proposal.proposal_hash == env2.proposal.proposal_hash


def test_different_cost_different_hash():
    rule = _rule()
    env1 = ENGINE.propose(
        rules=[rule],
        canonical_product_id="p",
        source_id="s",
        snapshot_id="sn",
        input_values={"cost": Decimal("100000")},
        currency="IDR",
        generated_at=_FIXED_TS,
    )
    env2 = ENGINE.propose(
        rules=[rule],
        canonical_product_id="p",
        source_id="s",
        snapshot_id="sn",
        input_values={"cost": Decimal("200000")},
        currency="IDR",
        generated_at=_FIXED_TS,
    )
    assert env1.proposal.proposal_hash != env2.proposal.proposal_hash


def test_different_rule_version_id_different_hash():
    r1 = _rule(version_id="ver-001")
    r2 = _rule(version_id="ver-002")
    env1 = ENGINE.propose(
        rules=[r1],
        canonical_product_id="p",
        source_id="s",
        snapshot_id="sn",
        input_values={"cost": Decimal("100000")},
        currency="IDR",
        generated_at=_FIXED_TS,
    )
    env2 = ENGINE.propose(
        rules=[r2],
        canonical_product_id="p",
        source_id="s",
        snapshot_id="sn",
        input_values={"cost": Decimal("100000")},
        currency="IDR",
        generated_at=_FIXED_TS,
    )
    assert env1.proposal.proposal_hash != env2.proposal.proposal_hash


# ── Repository persistence (provenance + trace) ───────────────────────────────

def test_save_persists_proposal(rule_repo, proposal_repo, db):
    rule = rule_repo.create_rule(rule_name="Cost+20%", rule_type="cost_plus", priority=10)
    db.commit()
    v = rule_repo.create_version(rule_id=rule.rule_id, formula="cost * 1.20", required_inputs=["cost"])
    db.commit()
    rule_repo.publish_version(v.version_id)
    db.commit()

    defs = rule_repo.load_active_definitions()
    env = ENGINE.propose(
        rules=defs,
        canonical_product_id="prod-001",
        source_id="src-001",
        snapshot_id="snap-001",
        input_values={"cost": Decimal("100000")},
        currency="IDR",
        generated_at=_FIXED_TS,
    )
    proposal_repo.save(env)
    db.commit()

    record = proposal_repo.get(env.proposal.proposal_id)
    assert record is not None
    assert record.proposal_id == env.proposal.proposal_id
    assert record.proposed_price == pytest.approx(float(Decimal("120000")), rel=1e-4)
    assert record.currency == "IDR"
    assert record.rule_id == rule.rule_id
    assert record.rule_version_number == 1
    assert record.proposal_hash == env.proposal.proposal_hash


def test_save_persists_provenance(rule_repo, proposal_repo, db):
    rule = rule_repo.create_rule(rule_name="R", rule_type="cost_plus", priority=1)
    db.commit()
    v = rule_repo.create_version(rule_id=rule.rule_id, formula="cost * 1.30", required_inputs=["cost"])
    db.commit()
    rule_repo.publish_version(v.version_id)
    db.commit()

    defs = rule_repo.load_active_definitions()
    env = ENGINE.propose(
        rules=defs,
        canonical_product_id="prod-prov",
        source_id="src-prov",
        snapshot_id="snap-prov",
        input_values={"cost": Decimal("77500")},
        currency="EUR",
        generated_at=_FIXED_TS,
    )
    proposal_repo.save(env)
    db.commit()

    record = proposal_repo.get(env.proposal.proposal_id)
    assert len(record.provenance) == 1
    prov = record.provenance[0]
    assert prov.rule_version_id == v.version_id
    assert prov.source_id == "src-prov"
    assert prov.snapshot_id == "snap-prov"
    assert prov.formula == "cost * 1.30"
    stored_inputs = json.loads(prov.input_values_json)
    assert stored_inputs.get("cost") == "77500"


def test_save_persists_execution_trace(rule_repo, proposal_repo, db):
    rule = rule_repo.create_rule(rule_name="R", rule_type="cost_plus", priority=1)
    db.commit()
    v = rule_repo.create_version(rule_id=rule.rule_id, formula="cost * 1.20", required_inputs=["cost"])
    db.commit()
    rule_repo.publish_version(v.version_id)
    db.commit()

    defs = rule_repo.load_active_definitions()
    env = ENGINE.propose(
        rules=defs,
        canonical_product_id="p",
        source_id="s",
        snapshot_id="sn",
        input_values={"cost": Decimal("100000")},
        currency="IDR",
        generated_at=_FIXED_TS,
    )
    proposal_repo.save(env)
    db.commit()

    record = proposal_repo.get(env.proposal.proposal_id)
    assert len(record.trace) == 3
    names = [t.step_name for t in record.trace]
    assert names == ["input_capture", "formula_evaluation", "hash_computation"]
    orders = [t.step_order for t in record.trace]
    assert orders == [1, 2, 3]


def test_find_by_hash_deduplication(rule_repo, proposal_repo, db):
    rule = rule_repo.create_rule(rule_name="R", rule_type="cost_plus", priority=1)
    db.commit()
    v = rule_repo.create_version(rule_id=rule.rule_id, formula="cost * 1.20", required_inputs=["cost"])
    db.commit()
    rule_repo.publish_version(v.version_id)
    db.commit()

    defs = rule_repo.load_active_definitions()
    env = ENGINE.propose(
        rules=defs,
        canonical_product_id="prod-dup",
        source_id="src",
        snapshot_id="sn",
        input_values={"cost": Decimal("100000")},
        currency="IDR",
        generated_at=_FIXED_TS,
    )
    proposal_repo.save(env)
    db.commit()

    # Same inputs → same hash → find_by_hash returns existing
    cached = proposal_repo.find_by_hash(env.proposal.proposal_hash)
    assert cached is not None
    assert cached.proposal_hash == env.proposal.proposal_hash


def test_find_by_hash_missing_returns_none(proposal_repo):
    assert proposal_repo.find_by_hash("0" * 64) is None


def test_reproducibility_from_stored_provenance(rule_repo, proposal_repo, db):
    """Given stored provenance (formula + input_values), proposal is re-derivable."""
    from app.a2.rules.formula import evaluate_formula

    rule = rule_repo.create_rule(rule_name="R", rule_type="cost_plus", priority=1)
    db.commit()
    v = rule_repo.create_version(rule_id=rule.rule_id, formula="cost * 1.35", required_inputs=["cost"])
    db.commit()
    rule_repo.publish_version(v.version_id)
    db.commit()

    defs = rule_repo.load_active_definitions()
    env = ENGINE.propose(
        rules=defs,
        canonical_product_id="p",
        source_id="s",
        snapshot_id="sn",
        input_values={"cost": Decimal("80000")},
        currency="IDR",
        generated_at=_FIXED_TS,
    )
    proposal_repo.save(env)
    db.commit()

    record = proposal_repo.get(env.proposal.proposal_id)
    prov = record.provenance[0]

    stored_inputs = {k: Decimal(str_v) for k, str_v in json.loads(prov.input_values_json).items()}
    rederived = evaluate_formula(prov.formula, stored_inputs)
    assert rederived == env.proposal.proposed_price


# ── Alembic migration a2_002_r2 ───────────────────────────────────────────────

class TestAlembicMigrationA2002R2:
    def test_upgrade_creates_all_r2_tables(self, tmp_path):
        db_url = "sqlite:///" + str(tmp_path / "a2_002_r2_test.db").replace("\\", "/")
        with patch.dict(os.environ, {"A2_DATABASE_URL": db_url}):
            cfg = Config("alembic_a2.ini")
            cfg.set_main_option("sqlalchemy.url", db_url)
            command.upgrade(cfg, "a2_002_r2")

        eng = create_engine(db_url)
        tables = set(inspect(eng).get_table_names())
        eng.dispose()

        assert "a2_pricing_rules" in tables
        assert "a2_pricing_rule_versions" in tables
        assert "a2_price_proposals" in tables
        assert "a2_proposal_provenance" in tables
        assert "a2_execution_traces" in tables
        # Earlier tables must also be present
        assert "canonical_products" in tables
        assert "source_definitions" in tables

    def test_upgrade_head_includes_r2_tables(self, tmp_path):
        db_url = "sqlite:///" + str(tmp_path / "head_r2.db").replace("\\", "/")
        with patch.dict(os.environ, {"A2_DATABASE_URL": db_url}):
            cfg = Config("alembic_a2.ini")
            cfg.set_main_option("sqlalchemy.url", db_url)
            command.upgrade(cfg, "head")

        eng = create_engine(db_url)
        tables = set(inspect(eng).get_table_names())
        eng.dispose()

        assert "a2_pricing_rules" in tables
        assert "a2_pricing_rule_versions" in tables
        assert "a2_price_proposals" in tables
        assert "a2_proposal_provenance" in tables
        assert "a2_execution_traces" in tables

    def test_downgrade_from_r2_removes_r2_tables(self, tmp_path):
        db_url = "sqlite:///" + str(tmp_path / "a2_002_r2_down.db").replace("\\", "/")
        with patch.dict(os.environ, {"A2_DATABASE_URL": db_url}):
            cfg = Config("alembic_a2.ini")
            cfg.set_main_option("sqlalchemy.url", db_url)
            command.upgrade(cfg, "a2_002_r2")
            command.downgrade(cfg, "a2_001")

        eng = create_engine(db_url)
        tables = set(inspect(eng).get_table_names())
        eng.dispose()

        assert "a2_pricing_rules" not in tables
        assert "a2_pricing_rule_versions" not in tables
        assert "a2_price_proposals" not in tables
        assert "a2_proposal_provenance" not in tables
        assert "a2_execution_traces" not in tables
        assert "source_definitions" in tables

    def test_upgrade_to_a2_001_does_not_create_r2_tables(self, tmp_path):
        db_url = "sqlite:///" + str(tmp_path / "a2_001_only.db").replace("\\", "/")
        with patch.dict(os.environ, {"A2_DATABASE_URL": db_url}):
            cfg = Config("alembic_a2.ini")
            cfg.set_main_option("sqlalchemy.url", db_url)
            command.upgrade(cfg, "a2_001")

        eng = create_engine(db_url)
        tables = set(inspect(eng).get_table_names())
        eng.dispose()

        assert "source_definitions" in tables
        assert "a2_pricing_rules" not in tables

    def test_old_a2_002_tables_do_not_exist(self, tmp_path):
        """The obsolete LOCAL a2_002 tables must not be created by the reconciled migration."""
        db_url = "sqlite:///" + str(tmp_path / "no_old_tables.db").replace("\\", "/")
        with patch.dict(os.environ, {"A2_DATABASE_URL": db_url}):
            cfg = Config("alembic_a2.ini")
            cfg.set_main_option("sqlalchemy.url", db_url)
            command.upgrade(cfg, "head")

        eng = create_engine(db_url)
        tables = set(inspect(eng).get_table_names())
        eng.dispose()

        # These were LOCAL a2_002 table names — must NOT exist in R2
        assert "a2_rule_definitions" not in tables
        assert "a2_rule_versions" not in tables


# ── Remediation tests (IR-R2-004, IR-R2-006) ─────────────────────────────────

def test_propose_all_empty_rules_returns_empty_list():
    """propose_all() with an empty rules list must return [] (IR-R2-004)."""
    envs = ENGINE.propose_all(
        rules=[],
        canonical_product_id="p",
        source_id="s",
        snapshot_id="sn",
        input_values={"cost": Decimal("100000")},
        currency="IDR",
        generated_at=_FIXED_TS,
    )
    assert envs == []


def test_find_formula_from_trace_fallback():
    """_find_formula_from_trace returns sentinel when no formula_evaluation step present (IR-R2-006)."""
    from app.a2.repositories.proposal_repository import ProposalRepository
    from app.a2.rules.engine import ProposalEnvelope, TraceStep

    step = TraceStep(
        step_order=1,
        step_name="input_capture",
        step_input_json="{}",
        step_output_json="{}",
        step_formula="(captured)",
    )
    envelope = ProposalEnvelope(proposal=None, trace=[step])  # type: ignore[arg-type]
    result = ProposalRepository._find_formula_from_trace(envelope)
    assert result == "(formula not recorded)"
