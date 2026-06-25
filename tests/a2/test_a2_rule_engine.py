"""
A2.3 — Transformation Rule Engine tests.

Covers:
  - Formula Engine (CostPlusProfitFormula)
  - Rule Repository (RuleDefinition / RuleVersion CRUD + publish immutability)
  - Proposal Repository (PriceProposal persistence, digest lookup)
  - Rule Engine (evaluate, determinism, caching, provenance, execution trace)
  - Determinism guarantee (identical inputs → identical computation_digest)
  - Reproducibility guarantee (provenance stores all fields needed to re-derive)
  - Rule versioning (mutations create new versions; old versions remain published)
  - Rule precedence (active rules ordered by priority descending)
  - Scope boundary (competitor_reference raises NotImplementedError; unknown type raises ValueError)
  - Alembic migration a2_002 (creates expected tables)

All tests use in-memory SQLite; no PostgreSQL required.
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
import app.a2.models.source  # noqa: F401
import app.a2.models.snapshot  # noqa: F401
import app.a2.models.provenance  # noqa: F401
import app.a2.models.checkpoint  # noqa: F401
import app.a2.models.rule  # noqa: F401
import app.a2.models.proposal  # noqa: F401

from app.a2.engines.formula import (
    CostPlusProfitFormula,
    CostPlusProfitParameters,
)
from app.a2.engines.rule_engine import RuleEngine, RuleInput
from app.a2.repositories.proposal_repository import ProposalRepository
from app.a2.repositories.rule_repository import RuleRepository


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def engine():
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
def db(engine):
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def rule_repo(db):
    return RuleRepository(db)


@pytest.fixture()
def proposal_repo(db):
    return ProposalRepository(db)


@pytest.fixture()
def rule_engine(db):
    return RuleEngine(db)


def _make_params(margin: float = 50.0, currency: str = "USD", dp: int = 2) -> str:
    return json.dumps({"profit_margin_pct": margin, "currency": currency, "decimal_places": dp})


def _make_published_version(rule_repo, db, margin: float = 50.0, currency: str = "USD") -> tuple:
    """Helper: create a rule definition + published version. Returns (defn, version)."""
    defn = rule_repo.create_definition(
        rule_type="cost_plus_profit",
        display_name="Standard margin",
        priority=100,
    )
    db.commit()
    version = rule_repo.create_version(defn.id, _make_params(margin, currency))
    db.commit()
    rule_repo.publish_version(version.id)
    db.commit()
    return defn, version


# ── Formula Engine ────────────────────────────────────────────────────────────


class TestCostPlusProfitParameters:
    def test_valid_parameters(self):
        p = CostPlusProfitParameters(profit_margin_pct=50.0, currency="USD")
        assert p.profit_margin_pct == 50.0
        assert p.currency == "USD"
        assert p.rounding_mode == "round_half_up"
        assert p.decimal_places == 0

    def test_rounding_mode_ceil(self):
        p = CostPlusProfitParameters(profit_margin_pct=10.0, currency="EUR", rounding_mode="ceil")
        assert p.rounding_mode == "ceil"

    def test_rounding_mode_floor(self):
        p = CostPlusProfitParameters(profit_margin_pct=10.0, currency="EUR", rounding_mode="floor")
        assert p.rounding_mode == "floor"

    def test_margin_at_lower_bound(self):
        p = CostPlusProfitParameters(profit_margin_pct=-100.0, currency="USD")
        assert p.profit_margin_pct == -100.0

    def test_margin_at_upper_bound(self):
        p = CostPlusProfitParameters(profit_margin_pct=10_000.0, currency="USD")
        assert p.profit_margin_pct == 10_000.0

    def test_margin_below_lower_bound_raises(self):
        with pytest.raises(Exception):
            CostPlusProfitParameters(profit_margin_pct=-100.01, currency="USD")

    def test_margin_above_upper_bound_raises(self):
        with pytest.raises(Exception):
            CostPlusProfitParameters(profit_margin_pct=10_000.01, currency="USD")

    def test_decimal_places_zero(self):
        p = CostPlusProfitParameters(profit_margin_pct=10.0, currency="USD", decimal_places=0)
        assert p.decimal_places == 0

    def test_decimal_places_six(self):
        p = CostPlusProfitParameters(profit_margin_pct=10.0, currency="USD", decimal_places=6)
        assert p.decimal_places == 6

    def test_decimal_places_negative_raises(self):
        with pytest.raises(Exception):
            CostPlusProfitParameters(profit_margin_pct=10.0, currency="USD", decimal_places=-1)

    def test_decimal_places_above_six_raises(self):
        with pytest.raises(Exception):
            CostPlusProfitParameters(profit_margin_pct=10.0, currency="USD", decimal_places=7)


class TestCostPlusProfitFormula:
    def test_basic_calculation(self):
        params = CostPlusProfitParameters(profit_margin_pct=50.0, currency="USD", decimal_places=2)
        result = CostPlusProfitFormula(params).evaluate(Decimal("100"))
        assert result.proposed_price == Decimal("150.00")
        assert result.currency == "USD"

    def test_zero_margin(self):
        params = CostPlusProfitParameters(profit_margin_pct=0.0, currency="USD", decimal_places=2)
        result = CostPlusProfitFormula(params).evaluate(Decimal("100"))
        assert result.proposed_price == Decimal("100.00")

    def test_100_percent_margin(self):
        params = CostPlusProfitParameters(profit_margin_pct=100.0, currency="USD", decimal_places=2)
        result = CostPlusProfitFormula(params).evaluate(Decimal("100"))
        assert result.proposed_price == Decimal("200.00")

    def test_rounding_round_half_up(self):
        params = CostPlusProfitParameters(
            profit_margin_pct=10.0, currency="USD", rounding_mode="round_half_up", decimal_places=0
        )
        result = CostPlusProfitFormula(params).evaluate(Decimal("9.09"))
        assert result.proposed_price == Decimal("10")

    def test_rounding_ceil(self):
        params = CostPlusProfitParameters(
            profit_margin_pct=10.0, currency="USD", rounding_mode="ceil", decimal_places=0
        )
        result = CostPlusProfitFormula(params).evaluate(Decimal("10.00"))
        assert result.proposed_price == Decimal("11")

    def test_rounding_floor(self):
        params = CostPlusProfitParameters(
            profit_margin_pct=10.0, currency="USD", rounding_mode="floor", decimal_places=0
        )
        result = CostPlusProfitFormula(params).evaluate(Decimal("10.99"))
        assert result.proposed_price == Decimal("12")

    def test_zero_cost_raises(self):
        params = CostPlusProfitParameters(profit_margin_pct=50.0, currency="USD")
        with pytest.raises(ValueError, match="cost must be positive"):
            CostPlusProfitFormula(params).evaluate(Decimal("0"))

    def test_negative_cost_raises(self):
        params = CostPlusProfitParameters(profit_margin_pct=50.0, currency="USD")
        with pytest.raises(ValueError, match="cost must be positive"):
            CostPlusProfitFormula(params).evaluate(Decimal("-10"))

    def test_execution_trace_has_three_steps(self):
        params = CostPlusProfitParameters(profit_margin_pct=50.0, currency="USD", decimal_places=2)
        result = CostPlusProfitFormula(params).evaluate(Decimal("100"))
        assert len(result.trace) == 3
        step_names = [s.step_name for s in result.trace]
        assert step_names == ["margin_factor", "raw_price", "rounding"]

    def test_trace_step_json_is_valid(self):
        params = CostPlusProfitParameters(profit_margin_pct=50.0, currency="USD", decimal_places=2)
        result = CostPlusProfitFormula(params).evaluate(Decimal("100"))
        for step in result.trace:
            json.loads(step.step_input_json)
            json.loads(step.step_output_json)
            assert step.step_formula

    def test_determinism_across_calls(self):
        params = CostPlusProfitParameters(profit_margin_pct=33.33, currency="EUR", decimal_places=2)
        formula = CostPlusProfitFormula(params)
        r1 = formula.evaluate(Decimal("99.99"))
        r2 = formula.evaluate(Decimal("99.99"))
        assert r1.proposed_price == r2.proposed_price
        assert r1.currency == r2.currency


# ── Rule Repository ───────────────────────────────────────────────────────────


class TestRuleRepository:
    def test_create_definition(self, rule_repo, db):
        defn = rule_repo.create_definition(
            rule_type="cost_plus_profit",
            display_name="Test Rule",
        )
        db.commit()
        assert defn.id
        assert defn.rule_type == "cost_plus_profit"
        assert defn.display_name == "Test Rule"
        assert defn.is_active is True
        assert defn.priority == 100

    def test_get_definition(self, rule_repo, db):
        defn = rule_repo.create_definition(rule_type="cost_plus_profit", display_name="Rule A")
        db.commit()
        fetched = rule_repo.get_definition(defn.id)
        assert fetched is not None
        assert fetched.id == defn.id

    def test_get_definition_missing_returns_none(self, rule_repo):
        assert rule_repo.get_definition("nonexistent") is None

    def test_create_version_auto_increments(self, rule_repo, db):
        defn = rule_repo.create_definition(rule_type="cost_plus_profit", display_name="R")
        db.commit()
        v1 = rule_repo.create_version(defn.id, _make_params(10.0))
        v2 = rule_repo.create_version(defn.id, _make_params(20.0))
        db.commit()
        assert v1.version_number == 1
        assert v2.version_number == 2

    def test_publish_version_sets_is_published(self, rule_repo, db):
        defn = rule_repo.create_definition(rule_type="cost_plus_profit", display_name="R")
        db.commit()
        version = rule_repo.create_version(defn.id, _make_params())
        db.commit()
        assert version.is_published is False
        rule_repo.publish_version(version.id)
        db.commit()
        assert version.is_published is True
        assert version.published_at is not None

    def test_publish_already_published_raises(self, rule_repo, db):
        defn = rule_repo.create_definition(rule_type="cost_plus_profit", display_name="R")
        db.commit()
        version = rule_repo.create_version(defn.id, _make_params())
        db.commit()
        rule_repo.publish_version(version.id)
        db.commit()
        with pytest.raises(ValueError, match="already published"):
            rule_repo.publish_version(version.id)

    def test_publish_missing_version_raises(self, rule_repo):
        with pytest.raises(ValueError, match="not found"):
            rule_repo.publish_version("does-not-exist")

    def test_get_published_version_returns_none_for_draft(self, rule_repo, db):
        defn = rule_repo.create_definition(rule_type="cost_plus_profit", display_name="R")
        db.commit()
        version = rule_repo.create_version(defn.id, _make_params())
        db.commit()
        result = rule_repo.get_published_version(version.id)
        assert result is None

    def test_get_published_version_loads_rule(self, rule_repo, db):
        defn, version = _make_published_version(rule_repo, db)
        fetched = rule_repo.get_published_version(version.id)
        assert fetched is not None
        assert fetched.rule is not None
        assert fetched.rule.rule_type == "cost_plus_profit"

    def test_get_latest_published_version(self, rule_repo, db):
        defn = rule_repo.create_definition(rule_type="cost_plus_profit", display_name="R")
        db.commit()
        v1 = rule_repo.create_version(defn.id, _make_params(10.0))
        rule_repo.publish_version(v1.id)
        v2 = rule_repo.create_version(defn.id, _make_params(20.0))
        rule_repo.publish_version(v2.id)
        v3 = rule_repo.create_version(defn.id, _make_params(30.0))
        db.commit()
        latest = rule_repo.get_latest_published_version(defn.id)
        assert latest is not None
        assert latest.version_number == 2  # v3 is a draft; v2 is latest published

    def test_list_versions(self, rule_repo, db):
        defn = rule_repo.create_definition(rule_type="cost_plus_profit", display_name="R")
        db.commit()
        rule_repo.create_version(defn.id, _make_params(10.0))
        rule_repo.create_version(defn.id, _make_params(20.0))
        rule_repo.create_version(defn.id, _make_params(30.0))
        db.commit()
        versions = rule_repo.list_versions(defn.id)
        assert [v.version_number for v in versions] == [1, 2, 3]

    def test_get_active_rules_by_priority(self, rule_repo, db):
        rule_repo.create_definition(rule_type="cost_plus_profit", display_name="Low", priority=50)
        rule_repo.create_definition(rule_type="cost_plus_profit", display_name="High", priority=200)
        rule_repo.create_definition(rule_type="cost_plus_profit", display_name="Mid", priority=100)
        db.commit()
        rules = rule_repo.get_active_rules_by_priority()
        priorities = [r.priority for r in rules]
        assert priorities == sorted(priorities, reverse=True)

    def test_inactive_rules_excluded_from_priority_list(self, rule_repo, db):
        active = rule_repo.create_definition(rule_type="cost_plus_profit", display_name="Active", priority=100)
        inactive = rule_repo.create_definition(rule_type="cost_plus_profit", display_name="Inactive", priority=200)
        inactive.is_active = False
        db.commit()
        rules = rule_repo.get_active_rules_by_priority()
        ids = [r.id for r in rules]
        assert active.id in ids
        assert inactive.id not in ids


# ── Rule Versioning ───────────────────────────────────────────────────────────


class TestRuleVersioning:
    def test_old_version_remains_published_after_new_version_created(self, rule_repo, db):
        defn = rule_repo.create_definition(rule_type="cost_plus_profit", display_name="R")
        db.commit()
        v1 = rule_repo.create_version(defn.id, _make_params(10.0))
        rule_repo.publish_version(v1.id)
        db.commit()

        v2 = rule_repo.create_version(defn.id, _make_params(20.0))
        rule_repo.publish_version(v2.id)
        db.commit()

        refetched_v1 = rule_repo.get_published_version(v1.id)
        assert refetched_v1 is not None, "v1 must remain published after v2 is created"
        assert refetched_v1.version_number == 1

    def test_new_version_has_independent_parameters(self, rule_repo, db):
        defn = rule_repo.create_definition(rule_type="cost_plus_profit", display_name="R")
        db.commit()
        v1 = rule_repo.create_version(defn.id, _make_params(10.0))
        rule_repo.publish_version(v1.id)
        db.commit()

        v2 = rule_repo.create_version(defn.id, _make_params(99.0))
        rule_repo.publish_version(v2.id)
        db.commit()

        p1 = json.loads(v1.parameters_json)
        p2 = json.loads(v2.parameters_json)
        assert p1["profit_margin_pct"] == 10.0
        assert p2["profit_margin_pct"] == 99.0

    def test_draft_version_does_not_affect_published_status(self, rule_repo, db):
        defn, v_pub = _make_published_version(rule_repo, db, margin=50.0)
        v_draft = rule_repo.create_version(defn.id, _make_params(60.0))
        db.commit()
        assert v_draft.is_published is False
        assert rule_repo.get_published_version(v_pub.id) is not None


# ── Proposal Repository ───────────────────────────────────────────────────────


class TestProposalRepository:
    def _create_proposal(self, db, rule_version_id: str) -> "PriceProposal":  # type: ignore[name-defined]
        from app.a2.models.proposal import PriceProposal
        import uuid

        p = PriceProposal(
            id=str(uuid.uuid4()),
            rule_version_id=rule_version_id,
            source_snapshot_id="snap-001",
            input_cost=100.0,
            proposed_price=150.0,
            currency="USD",
            computation_digest="deadbeef" * 8,
            created_at=datetime.now(tz=timezone.utc),
        )
        db.add(p)
        db.flush()
        return p

    def test_get_proposal(self, proposal_repo, rule_repo, db):
        defn, version = _make_published_version(rule_repo, db)
        p = self._create_proposal(db, version.id)
        db.commit()
        fetched = proposal_repo.get(p.id)
        assert fetched is not None
        assert fetched.id == p.id

    def test_get_missing_proposal_returns_none(self, proposal_repo):
        assert proposal_repo.get("nonexistent") is None

    def test_find_by_digest(self, proposal_repo, rule_repo, db):
        defn, version = _make_published_version(rule_repo, db)
        p = self._create_proposal(db, version.id)
        db.commit()
        found = proposal_repo.find_by_digest(p.computation_digest)
        assert found is not None
        assert found.id == p.id

    def test_find_by_digest_missing_returns_none(self, proposal_repo):
        assert proposal_repo.find_by_digest("0" * 64) is None

    def test_list_by_snapshot(self, proposal_repo, rule_repo, db):
        defn, version = _make_published_version(rule_repo, db)
        from app.a2.models.proposal import PriceProposal
        import uuid

        for i in range(3):
            p = PriceProposal(
                id=str(uuid.uuid4()),
                rule_version_id=version.id,
                source_snapshot_id="snap-xyz",
                input_cost=float(10 * (i + 1)),
                proposed_price=float(15 * (i + 1)),
                currency="USD",
                computation_digest=f"digest-{i:064d}",
                created_at=datetime.now(tz=timezone.utc),
            )
            db.add(p)
        db.commit()
        results = proposal_repo.list_by_snapshot("snap-xyz")
        assert len(results) == 3

    def test_list_by_snapshot_other_snapshot_not_returned(self, proposal_repo, rule_repo, db):
        defn, version = _make_published_version(rule_repo, db)
        from app.a2.models.proposal import PriceProposal
        import uuid

        p = PriceProposal(
            id=str(uuid.uuid4()),
            rule_version_id=version.id,
            source_snapshot_id="snap-A",
            input_cost=100.0,
            proposed_price=150.0,
            currency="USD",
            computation_digest="a" * 64,
            created_at=datetime.now(tz=timezone.utc),
        )
        db.add(p)
        db.commit()
        assert proposal_repo.list_by_snapshot("snap-B") == []


# ── Rule Engine Integration ───────────────────────────────────────────────────


class TestRuleEngine:
    def _make_input(self, cost: str = "100.00", snapshot_id: str = "snap-001") -> RuleInput:
        return RuleInput(
            cost=Decimal(cost),
            currency="USD",
            source_row_ref="row-42",
            source_snapshot_id=snapshot_id,
            input_fields={"cost": cost, "sku": "ABC123"},
        )

    def test_evaluate_creates_proposal(self, rule_engine, rule_repo, proposal_repo, db):
        defn, version = _make_published_version(rule_repo, db, margin=50.0)
        result = rule_engine.evaluate(version.id, self._make_input())
        db.commit()
        assert result.proposal_id
        assert result.was_cached is False
        stored = proposal_repo.get(result.proposal_id)
        assert stored is not None
        assert stored.proposed_price == pytest.approx(150.0, rel=1e-4)
        assert stored.currency == "USD"

    def test_evaluate_unknown_version_raises(self, rule_engine):
        with pytest.raises(ValueError, match="not found or not published"):
            rule_engine.evaluate("nonexistent-id", self._make_input())

    def test_evaluate_draft_version_raises(self, rule_engine, rule_repo, db):
        defn = rule_repo.create_definition(rule_type="cost_plus_profit", display_name="R")
        db.commit()
        draft = rule_repo.create_version(defn.id, _make_params(50.0))
        db.commit()
        with pytest.raises(ValueError, match="not found or not published"):
            rule_engine.evaluate(draft.id, self._make_input())

    def test_evaluate_zero_cost_raises(self, rule_engine, rule_repo, db):
        defn, version = _make_published_version(rule_repo, db)
        bad_input = RuleInput(
            cost=Decimal("0"),
            currency="USD",
            source_row_ref="row-0",
            source_snapshot_id="snap-x",
            input_fields={},
        )
        with pytest.raises(ValueError, match="cost must be positive"):
            rule_engine.evaluate(version.id, bad_input)

    def test_evaluate_stores_provenance(self, rule_engine, rule_repo, proposal_repo, db):
        defn, version = _make_published_version(rule_repo, db)
        result = rule_engine.evaluate(version.id, self._make_input())
        db.commit()
        stored = proposal_repo.get(result.proposal_id)
        assert stored is not None
        assert len(stored.provenance) == 1
        assert stored.provenance[0].source_row_ref == "row-42"
        input_fields = json.loads(stored.provenance[0].input_fields_json)
        assert "cost" in input_fields

    def test_evaluate_stores_execution_trace(self, rule_engine, rule_repo, proposal_repo, db):
        defn, version = _make_published_version(rule_repo, db)
        result = rule_engine.evaluate(version.id, self._make_input())
        db.commit()
        stored = proposal_repo.get(result.proposal_id)
        assert stored is not None
        assert len(stored.trace) == 3
        step_names = [t.step_name for t in stored.trace]
        assert step_names == ["margin_factor", "raw_price", "rounding"]

    def test_evaluate_competitor_reference_raises_not_implemented(self, rule_engine, rule_repo, db):
        from app.a2.models.rule import RuleDefinition, RuleVersion
        import uuid

        now = datetime.now(tz=timezone.utc)
        defn = RuleDefinition(
            id=str(uuid.uuid4()),
            rule_type="competitor_reference",
            display_name="Competitor",
            priority=100,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        db.add(defn)
        db.flush()
        version = RuleVersion(
            id=str(uuid.uuid4()),
            rule_id=defn.id,
            version_number=1,
            parameters_json=_make_params(10.0),
            is_published=True,
            published_at=now,
            created_at=now,
        )
        db.add(version)
        db.commit()
        with pytest.raises(NotImplementedError, match="competitor_reference"):
            rule_engine.evaluate(version.id, self._make_input())

    def test_evaluate_unknown_rule_type_raises(self, rule_engine, rule_repo, db):
        defn, version = _make_published_version(rule_repo, db, margin=10.0)
        # Load the version via get_published_version so rule is eager-loaded
        loaded = rule_repo.get_published_version(version.id)
        # Mutate the in-memory rule_type to simulate an unknown future type
        loaded.rule.rule_type = "unknown_future_type"
        with pytest.raises(ValueError, match="Unknown rule_type"):
            rule_engine._dispatch(loaded, self._make_input())


# ── Determinism guarantee ─────────────────────────────────────────────────────


class TestDeterminism:
    """Identical inputs to the same published version always produce the same computation_digest."""

    def test_same_inputs_same_digest(self, rule_engine, rule_repo, proposal_repo, db):
        defn, version = _make_published_version(rule_repo, db, margin=50.0)
        inp = RuleInput(
            cost=Decimal("100.00"),
            currency="USD",
            source_row_ref="row-A",
            source_snapshot_id="snap-001",
            input_fields={"cost": "100.00"},
        )
        r1 = rule_engine.evaluate(version.id, inp)
        db.commit()

        r2 = rule_engine.evaluate(version.id, inp)
        db.commit()

        assert r1.proposal.computation_digest == r2.proposal.computation_digest

    def test_same_inputs_returns_cached_proposal(self, rule_engine, rule_repo, db):
        defn, version = _make_published_version(rule_repo, db, margin=50.0)
        inp = RuleInput(
            cost=Decimal("100.00"),
            currency="USD",
            source_row_ref="row-A",
            source_snapshot_id="snap-001",
            input_fields={"cost": "100.00"},
        )
        r1 = rule_engine.evaluate(version.id, inp)
        db.commit()
        r2 = rule_engine.evaluate(version.id, inp)
        db.commit()

        assert r2.was_cached is True
        assert r1.proposal_id == r2.proposal_id

    def test_different_cost_different_digest(self, rule_engine, rule_repo, db):
        defn, version = _make_published_version(rule_repo, db, margin=50.0)
        inp1 = RuleInput(
            cost=Decimal("100.00"),
            currency="USD",
            source_row_ref="row-A",
            source_snapshot_id="snap-001",
            input_fields={"cost": "100.00"},
        )
        inp2 = RuleInput(
            cost=Decimal("200.00"),
            currency="USD",
            source_row_ref="row-B",
            source_snapshot_id="snap-001",
            input_fields={"cost": "200.00"},
        )
        r1 = rule_engine.evaluate(version.id, inp1)
        db.commit()
        r2 = rule_engine.evaluate(version.id, inp2)
        db.commit()

        assert r1.proposal.computation_digest != r2.proposal.computation_digest
        assert r1.proposal_id != r2.proposal_id

    def test_different_rule_version_different_digest(self, rule_engine, rule_repo, db):
        defn = rule_repo.create_definition(rule_type="cost_plus_profit", display_name="R")
        db.commit()
        v1 = rule_repo.create_version(defn.id, _make_params(10.0))
        rule_repo.publish_version(v1.id)
        v2 = rule_repo.create_version(defn.id, _make_params(20.0))
        rule_repo.publish_version(v2.id)
        db.commit()

        inp = RuleInput(
            cost=Decimal("100.00"),
            currency="USD",
            source_row_ref="row-A",
            source_snapshot_id="snap-001",
            input_fields={"cost": "100.00"},
        )
        r1 = rule_engine.evaluate(v1.id, inp)
        db.commit()
        r2 = rule_engine.evaluate(v2.id, inp)
        db.commit()

        assert r1.proposal.computation_digest != r2.proposal.computation_digest


# ── Reproducibility guarantee ─────────────────────────────────────────────────


class TestReproducibility:
    """Given stored provenance (rule_version_id + input_fields_json), a proposal can be re-derived."""

    def test_stored_provenance_contains_all_inputs_for_rederivation(
        self, rule_engine, rule_repo, proposal_repo, db
    ):
        defn, version = _make_published_version(rule_repo, db, margin=30.0)
        inp = RuleInput(
            cost=Decimal("77.50"),
            currency="EUR",
            source_row_ref="row-rederive",
            source_snapshot_id="snap-repro",
            input_fields={"cost": "77.50", "sku": "XYZ"},
        )
        result = rule_engine.evaluate(version.id, inp)
        db.commit()

        stored = proposal_repo.get(result.proposal_id)
        prov = stored.provenance[0]

        # The provenance stores the input_fields
        input_fields = json.loads(prov.input_fields_json)
        assert input_fields["cost"] == "77.50"
        assert input_fields["sku"] == "XYZ"

        # Re-derive: given rule_version_id + cost + currency → same proposed_price
        params = CostPlusProfitParameters.model_validate_json(version.parameters_json)
        rederived = CostPlusProfitFormula(params).evaluate(Decimal(input_fields["cost"]))
        assert rederived.proposed_price == pytest.approx(
            Decimal("77.50") * (1 + Decimal("30") / Decimal("100")),
            rel=Decimal("1e-6"),
        )

    def test_execution_trace_records_formula_string(self, rule_engine, rule_repo, proposal_repo, db):
        defn, version = _make_published_version(rule_repo, db, margin=50.0)
        result = rule_engine.evaluate(
            version.id,
            RuleInput(
                cost=Decimal("100"),
                currency="USD",
                source_row_ref="row-1",
                source_snapshot_id="snap-trace",
                input_fields={},
            ),
        )
        db.commit()
        stored = proposal_repo.get(result.proposal_id)
        for step in stored.trace:
            assert step.step_formula


# ── Alembic migration a2_002 ──────────────────────────────────────────────────


class TestAlembicMigrationA2002:
    def test_upgrade_to_a2_002_creates_rule_engine_tables(self, tmp_path):
        db_url = "sqlite:///" + str(tmp_path / "a2_002_test.db").replace("\\", "/")
        with patch.dict(os.environ, {"A2_DATABASE_URL": db_url}):
            cfg = Config("alembic_a2.ini")
            cfg.set_main_option("sqlalchemy.url", db_url)
            command.upgrade(cfg, "head")

        eng = create_engine(db_url)
        tables = set(inspect(eng).get_table_names())
        eng.dispose()

        assert "a2_rule_definitions" in tables
        assert "a2_rule_versions" in tables
        assert "a2_price_proposals" in tables
        assert "a2_proposal_provenance" in tables
        assert "a2_execution_traces" in tables
        # Earlier tables must also be present
        assert "canonical_products" in tables
        assert "source_definitions" in tables

    def test_downgrade_from_a2_002_removes_rule_engine_tables(self, tmp_path):
        db_url = "sqlite:///" + str(tmp_path / "a2_002_down_test.db").replace("\\", "/")
        with patch.dict(os.environ, {"A2_DATABASE_URL": db_url}):
            cfg = Config("alembic_a2.ini")
            cfg.set_main_option("sqlalchemy.url", db_url)
            command.upgrade(cfg, "head")
            command.downgrade(cfg, "a2_001")

        eng = create_engine(db_url)
        tables = set(inspect(eng).get_table_names())
        eng.dispose()

        assert "a2_rule_definitions" not in tables
        assert "a2_rule_versions" not in tables
        assert "a2_price_proposals" not in tables
        assert "a2_proposal_provenance" not in tables
        assert "a2_execution_traces" not in tables
        # a2_001 tables must still be present
        assert "source_definitions" in tables

    def test_alembic_db_test_upgrade_includes_a2_002_tables(self, tmp_path):
        """The test_a2_db upgrade test must also see A2.3 tables at head."""
        db_url = "sqlite:///" + str(tmp_path / "a2_head_full.db").replace("\\", "/")
        with patch.dict(os.environ, {"A2_DATABASE_URL": db_url}):
            cfg = Config("alembic_a2.ini")
            cfg.set_main_option("sqlalchemy.url", db_url)
            command.upgrade(cfg, "head")

        eng = create_engine(db_url)
        tables = set(inspect(eng).get_table_names())
        eng.dispose()

        assert "a2_rule_definitions" in tables
        assert "a2_rule_versions" in tables

    def test_upgrade_to_a2_001_does_not_create_a2_002_tables(self, tmp_path):
        db_url = "sqlite:///" + str(tmp_path / "a2_001_only.db").replace("\\", "/")
        with patch.dict(os.environ, {"A2_DATABASE_URL": db_url}):
            cfg = Config("alembic_a2.ini")
            cfg.set_main_option("sqlalchemy.url", db_url)
            command.upgrade(cfg, "a2_001")

        eng = create_engine(db_url)
        tables = set(inspect(eng).get_table_names())
        eng.dispose()

        assert "source_definitions" in tables
        assert "a2_rule_definitions" not in tables
