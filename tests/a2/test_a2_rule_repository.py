"""
Integration tests — A2.3-R2 RuleRepository and ProposalRepository.

Uses in-memory SQLite. No PostgreSQL required.
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

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.a2.database import A2Base
import app.a2.models.canonical_product     # noqa: F401
import app.a2.models.source                # noqa: F401
import app.a2.models.snapshot              # noqa: F401
import app.a2.models.provenance            # noqa: F401
import app.a2.models.checkpoint            # noqa: F401
import app.a2.models.pricing_rule          # noqa: F401
import app.a2.models.pricing_rule_version  # noqa: F401
import app.a2.models.price_proposal        # noqa: F401

from app.a2.repositories.rule_repository import RuleRepository
from app.a2.repositories.proposal_repository import ProposalRepository
from app.a2.rules.base import RuleType
from app.a2.rules.engine import RuleEngine

_FIXED_TS = datetime(2026, 6, 26, 0, 0, 0, tzinfo=timezone.utc)


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


# ── RuleRepository — create and get ───────────────────────────────────────────

def test_create_and_get_rule(rule_repo, db):
    rule = rule_repo.create_rule(
        rule_name="Cost Plus 20%",
        rule_type=RuleType.COST_PLUS.value,
        priority=10,
    )
    db.commit()
    fetched = rule_repo.get_rule(rule.rule_id)
    assert fetched is not None
    assert fetched.rule_name == "Cost Plus 20%"
    assert fetched.rule_type == "cost_plus"
    assert fetched.priority == 10
    assert fetched.is_active is True


def test_get_rule_missing_returns_none(rule_repo):
    assert rule_repo.get_rule("nonexistent") is None


def test_create_rule_invalid_type_raises(rule_repo):
    with pytest.raises(ValueError, match="rule_type"):
        rule_repo.create_rule(rule_name="Bad", rule_type="unknown_type", priority=1)


# ── RuleRepository — deactivate ───────────────────────────────────────────────

def test_deactivate_rule(rule_repo, db):
    rule = rule_repo.create_rule(rule_name="R", rule_type="cost_plus", priority=1)
    db.commit()
    result = rule_repo.deactivate_rule(rule.rule_id)
    db.commit()
    assert result is True
    fetched = rule_repo.get_rule(rule.rule_id)
    assert fetched.is_active is False


def test_deactivate_missing_returns_false(rule_repo):
    assert rule_repo.deactivate_rule("nonexistent") is False


def test_list_active_excludes_inactive(rule_repo, db):
    r1 = rule_repo.create_rule(rule_name="R1", rule_type="cost_plus", priority=1)
    r2 = rule_repo.create_rule(rule_name="R2", rule_type="cost_plus", priority=2)
    db.commit()
    rule_repo.deactivate_rule(r2.rule_id)
    db.commit()
    active = rule_repo.list_active_rules()
    ids = [r.rule_id for r in active]
    assert r1.rule_id in ids
    assert r2.rule_id not in ids


def test_list_active_sorted_by_priority(rule_repo, db):
    rule_repo.create_rule(rule_name="High", rule_type="cost_plus", priority=5)
    rule_repo.create_rule(rule_name="Low", rule_type="cost_plus", priority=50)
    rule_repo.create_rule(rule_name="Med", rule_type="cost_plus", priority=20)
    db.commit()
    active = rule_repo.list_active_rules()
    priorities = [r.priority for r in active]
    assert priorities == sorted(priorities)


# ── RuleRepository — versions ─────────────────────────────────────────────────

def test_create_version_auto_increments(rule_repo, db):
    rule = rule_repo.create_rule(rule_name="R", rule_type="cost_plus", priority=1)
    db.commit()
    v1 = rule_repo.create_version(rule_id=rule.rule_id, formula="cost * 1.10", required_inputs=["cost"])
    v2 = rule_repo.create_version(rule_id=rule.rule_id, formula="cost * 1.20", required_inputs=["cost"])
    db.commit()
    assert v1.version_number == 1
    assert v2.version_number == 2


def test_publish_version_sets_is_published(rule_repo, db):
    rule = rule_repo.create_rule(rule_name="R", rule_type="cost_plus", priority=1)
    db.commit()
    v = rule_repo.create_version(rule_id=rule.rule_id, formula="cost * 1.10", required_inputs=["cost"])
    db.commit()
    assert v.is_published is False
    rule_repo.publish_version(v.version_id)
    db.commit()
    assert v.is_published is True
    assert v.published_at is not None


def test_publish_version_sets_is_current(rule_repo, db):
    rule = rule_repo.create_rule(rule_name="R", rule_type="cost_plus", priority=1)
    db.commit()
    v = rule_repo.create_version(rule_id=rule.rule_id, formula="cost * 1.10", required_inputs=["cost"])
    db.commit()
    assert v.is_current is False
    rule_repo.publish_version(v.version_id)
    db.commit()
    assert v.is_current is True


def test_publish_version_immutability_raises_on_republish(rule_repo, db):
    """publish_version() on an already-published version must raise ValueError."""
    rule = rule_repo.create_rule(rule_name="R", rule_type="cost_plus", priority=1)
    db.commit()
    v = rule_repo.create_version(rule_id=rule.rule_id, formula="cost * 1.10", required_inputs=["cost"])
    db.commit()
    rule_repo.publish_version(v.version_id)
    db.commit()

    with pytest.raises(ValueError, match="already published"):
        rule_repo.publish_version(v.version_id)


def test_publish_missing_version_raises(rule_repo):
    with pytest.raises(ValueError, match="not found"):
        rule_repo.publish_version("does-not-exist")


def test_publish_version_clears_previous_current(rule_repo, db):
    rule = rule_repo.create_rule(rule_name="R", rule_type="cost_plus", priority=1)
    db.commit()
    v1 = rule_repo.create_version(rule_id=rule.rule_id, formula="cost * 1.10", required_inputs=["cost"])
    db.commit()
    rule_repo.publish_version(v1.version_id)
    db.commit()
    assert v1.is_current is True

    v2 = rule_repo.create_version(rule_id=rule.rule_id, formula="cost * 1.20", required_inputs=["cost"])
    db.commit()
    rule_repo.publish_version(v2.version_id)
    db.commit()

    refetched_v1 = rule_repo.get_version(v1.version_id)
    assert refetched_v1.is_current is False
    assert v2.is_current is True


def test_published_version_remains_in_db_after_superseded(rule_repo, db):
    """An older published version must remain queryable even after being superseded."""
    rule = rule_repo.create_rule(rule_name="R", rule_type="cost_plus", priority=1)
    db.commit()
    v1 = rule_repo.create_version(rule_id=rule.rule_id, formula="cost * 1.10", required_inputs=["cost"])
    db.commit()
    rule_repo.publish_version(v1.version_id)
    db.commit()

    v2 = rule_repo.create_version(rule_id=rule.rule_id, formula="cost * 1.20", required_inputs=["cost"])
    db.commit()
    rule_repo.publish_version(v2.version_id)
    db.commit()

    fetched_v1 = rule_repo.get_version(v1.version_id)
    assert fetched_v1 is not None
    assert fetched_v1.is_published is True
    assert fetched_v1.formula == "cost * 1.10"


def test_set_current_version_switches_current(rule_repo, db):
    rule = rule_repo.create_rule(rule_name="R", rule_type="cost_plus", priority=1)
    db.commit()
    v1 = rule_repo.create_version(rule_id=rule.rule_id, formula="cost * 1.10", required_inputs=["cost"])
    db.commit()
    rule_repo.publish_version(v1.version_id)
    db.commit()

    v2 = rule_repo.create_version(rule_id=rule.rule_id, formula="cost * 1.20", required_inputs=["cost"])
    db.commit()
    rule_repo.publish_version(v2.version_id)
    db.commit()

    assert rule_repo.get_current_version(rule.rule_id).version_id == v2.version_id

    rule_repo.set_current_version(v1.version_id)
    db.commit()

    assert rule_repo.get_current_version(rule.rule_id).version_id == v1.version_id


def test_set_current_version_draft_returns_false(rule_repo, db):
    rule = rule_repo.create_rule(rule_name="R", rule_type="cost_plus", priority=1)
    db.commit()
    v = rule_repo.create_version(rule_id=rule.rule_id, formula="cost * 1.10", required_inputs=["cost"])
    db.commit()
    # v is not published
    assert rule_repo.set_current_version(v.version_id) is False


def test_set_current_version_missing_returns_false(rule_repo):
    assert rule_repo.set_current_version("nonexistent") is False


def test_get_current_version_none_before_publish(rule_repo, db):
    rule = rule_repo.create_rule(rule_name="R", rule_type="cost_plus", priority=1)
    db.commit()
    rule_repo.create_version(rule_id=rule.rule_id, formula="cost * 1.10", required_inputs=["cost"])
    db.commit()
    assert rule_repo.get_current_version(rule.rule_id) is None


def test_list_versions(rule_repo, db):
    rule = rule_repo.create_rule(rule_name="R", rule_type="cost_plus", priority=1)
    db.commit()
    rule_repo.create_version(rule_id=rule.rule_id, formula="cost * 1.10", required_inputs=["cost"])
    rule_repo.create_version(rule_id=rule.rule_id, formula="cost * 1.20", required_inputs=["cost"])
    db.commit()
    versions = rule_repo.list_versions(rule.rule_id)
    assert len(versions) == 2
    assert versions[0].version_number < versions[1].version_number


# ── RuleRepository — load_active_definitions ──────────────────────────────────

def test_load_active_definitions(rule_repo, db):
    rule = rule_repo.create_rule(rule_name="Cost+20%", rule_type="cost_plus", priority=10)
    db.commit()
    v = rule_repo.create_version(rule_id=rule.rule_id, formula="cost * 1.20", required_inputs=["cost"])
    db.commit()
    rule_repo.publish_version(v.version_id)
    db.commit()

    defs = rule_repo.load_active_definitions()
    assert len(defs) == 1
    d = defs[0]
    assert d.rule_id == rule.rule_id
    assert d.rule_name == "Cost+20%"
    assert d.rule_type == "cost_plus"
    assert d.priority == 10
    assert d.formula == "cost * 1.20"
    assert d.required_inputs == ["cost"]
    assert d.version_number == 1


def test_load_active_definitions_excludes_no_current_version(rule_repo, db):
    rule = rule_repo.create_rule(rule_name="NoVersion", rule_type="cost_plus", priority=10)
    db.commit()
    rule_repo.create_version(rule_id=rule.rule_id, formula="cost * 1.20", required_inputs=["cost"])
    db.commit()
    # no publish_version called → no current version

    assert rule_repo.load_active_definitions() == []


def test_load_active_definitions_excludes_inactive_rules(rule_repo, db):
    rule = rule_repo.create_rule(rule_name="R", rule_type="cost_plus", priority=1)
    db.commit()
    v = rule_repo.create_version(rule_id=rule.rule_id, formula="cost * 1.20", required_inputs=["cost"])
    db.commit()
    rule_repo.publish_version(v.version_id)
    rule_repo.deactivate_rule(rule.rule_id)
    db.commit()

    assert rule_repo.load_active_definitions() == []


def test_load_active_definitions_required_inputs_stored(rule_repo, db):
    rule = rule_repo.create_rule(rule_name="FX", rule_type="fx_based", priority=1)
    db.commit()
    v = rule_repo.create_version(
        rule_id=rule.rule_id,
        formula="cost * fx_rate",
        required_inputs=["cost", "fx_rate"],
    )
    db.commit()
    rule_repo.publish_version(v.version_id)
    db.commit()

    defs = rule_repo.load_active_definitions()
    assert defs[0].required_inputs == ["cost", "fx_rate"]


# ── End-to-end: Engine → Repository ───────────────────────────────────────────

def test_engine_proposal_round_trips(rule_repo, proposal_repo, db):
    """Full A2.3-R2 integration: create rule → generate proposal → persist → retrieve."""
    rule = rule_repo.create_rule(rule_name="Cost+20%", rule_type="cost_plus", priority=10)
    db.commit()
    v = rule_repo.create_version(rule_id=rule.rule_id, formula="cost * 1.20", required_inputs=["cost"])
    db.commit()
    rule_repo.publish_version(v.version_id)
    db.commit()

    defs = rule_repo.load_active_definitions()
    engine = RuleEngine()
    env = engine.propose(
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
    assert record.proposed_price == pytest.approx(120000.0, rel=1e-4)
    assert record.rule_id == rule.rule_id
    assert record.rule_version_number == 1
    assert record.source_id == "src-001"
    assert record.snapshot_id == "snap-001"
    assert len(record.provenance) == 1
    assert len(record.trace) == 3
    assert len(record.proposal_hash) == 64


def test_list_by_snapshot(rule_repo, proposal_repo, db):
    rule = rule_repo.create_rule(rule_name="R", rule_type="cost_plus", priority=1)
    db.commit()
    v = rule_repo.create_version(rule_id=rule.rule_id, formula="cost * 1.20", required_inputs=["cost"])
    db.commit()
    rule_repo.publish_version(v.version_id)
    db.commit()

    defs = rule_repo.load_active_definitions()
    engine = RuleEngine()
    for cost in ["10000", "20000", "30000"]:
        env = engine.propose(
            rules=defs,
            canonical_product_id=f"prod-{cost}",
            source_id="src",
            snapshot_id="snap-xyz",
            input_values={"cost": Decimal(cost)},
            currency="IDR",
        )
        proposal_repo.save(env)
    db.commit()

    results = proposal_repo.list_by_snapshot("snap-xyz")
    assert len(results) == 3


def test_list_by_product(rule_repo, proposal_repo, db):
    """list_by_product() returns all proposals for a given canonical_product_id (IR-R2-005)."""
    rule = rule_repo.create_rule(rule_name="R", rule_type="cost_plus", priority=1)
    db.commit()
    v = rule_repo.create_version(rule_id=rule.rule_id, formula="cost * 1.20", required_inputs=["cost"])
    db.commit()
    rule_repo.publish_version(v.version_id)
    db.commit()

    defs = rule_repo.load_active_definitions()
    engine = RuleEngine()

    env1 = engine.propose(
        rules=defs,
        canonical_product_id="prod-list-by-product",
        source_id="src",
        snapshot_id="snap-1",
        input_values={"cost": Decimal("10000")},
        currency="IDR",
        generated_at=_FIXED_TS,
    )
    proposal_repo.save(env1)

    env2 = engine.propose(
        rules=defs,
        canonical_product_id="prod-list-by-product",
        source_id="src",
        snapshot_id="snap-2",
        input_values={"cost": Decimal("20000")},
        currency="IDR",
        generated_at=_FIXED_TS,
    )
    proposal_repo.save(env2)

    env_other = engine.propose(
        rules=defs,
        canonical_product_id="other-product",
        source_id="src",
        snapshot_id="snap-3",
        input_values={"cost": Decimal("30000")},
        currency="IDR",
        generated_at=_FIXED_TS,
    )
    proposal_repo.save(env_other)
    db.commit()

    results = proposal_repo.list_by_product("prod-list-by-product")
    assert len(results) == 2
    ids = {p.canonical_product_id for p in results}
    assert ids == {"prod-list-by-product"}

    other_results = proposal_repo.list_by_product("other-product")
    assert len(other_results) == 1
