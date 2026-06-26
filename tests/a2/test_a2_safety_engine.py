"""
A2.4 — Safety Policy Engine tests.

Covers:
  - All policy types: percentage_change, missing_zero, extra_zero, historical_anomaly
  - All policy modes: WARN, BLOCK, REQUIRE_OVERRIDE
  - Default installation mode is WARN
  - SafetyResult structure (all required audit fields present)
  - Override framework: audit trail correctness, authorization enforcement
  - Policy versioning: threshold changes create new versions; old evaluations remain valid
  - Category, brand, user, channel scoping (data model and repository)
  - EvaluationReport aggregate properties (is_blocked, requires_override, etc.)
  - Safety Repository CRUD
  - Scope-filtered published version retrieval
  - Alembic migration a2_003 (creates expected tables; lineage correct)
  - Isolation: no imports from future phases (A2.5+)
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
import app.a2.models.pricing_rule          # noqa: F401 — A2.3-R2
import app.a2.models.pricing_rule_version  # noqa: F401 — A2.3-R2
import app.a2.models.price_proposal        # noqa: F401 — A2.3-R2
import app.a2.models.safety                # noqa: F401

from app.a2.engines.safety_engine import EvaluationContext, SafetyEngine
from app.a2.repositories.safety_repository import SafetyRepository


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
def repo(db):
    return SafetyRepository(db)


@pytest.fixture()
def safety_engine(db):
    return SafetyEngine(db)


def _make_context(
    proposal_id: str = "prop-001",
    cost: str = "100.00",
    proposed: str = "150.00",
    currency: str = "USD",
    **kwargs,
) -> EvaluationContext:
    return EvaluationContext(
        proposal_id=proposal_id,
        input_cost=Decimal(cost),
        proposed_price=Decimal(proposed),
        currency=currency,
        **kwargs,
    )


def _make_published_version(repo, db, policy_type: str, params: dict, mode: str = "WARN"):
    """Create, publish and return a (policy, version) for tests."""
    policy = repo.create_policy(policy_type=policy_type, display_name=f"Test {policy_type}")
    db.commit()
    version = repo.create_version(policy.id, json.dumps(params), mode=mode)
    db.commit()
    repo.publish_version(version.id)
    db.commit()
    return policy, repo.get_published_version(version.id)


# ── Default mode is WARN ──────────────────────────────────────────────────────


class TestDefaultPolicyMode:
    def test_create_version_default_mode_is_warn(self, repo, db):
        policy = repo.create_policy(policy_type="percentage_change", display_name="Default Mode")
        db.commit()
        version = repo.create_version(policy.id, json.dumps({"max_margin_pct": 200.0}))
        db.commit()
        assert version.mode == "WARN"

    def test_warn_mode_does_not_block(self, safety_engine, repo, db):
        _, version = _make_published_version(
            repo, db, "percentage_change", {"max_margin_pct": 10.0}, mode="WARN"
        )
        ctx = _make_context(cost="100", proposed="500")  # 400% margin — exceeds limit
        report = safety_engine.evaluate(ctx, [version])
        db.commit()
        assert report.results[0].outcome == "WARN"
        assert not report.is_blocked


# ── Policy type: percentage_change ────────────────────────────────────────────


class TestPercentageChangePolicy:
    def test_within_bounds_is_pass(self, safety_engine, repo, db):
        _, version = _make_published_version(
            repo, db, "percentage_change", {"min_margin_pct": 10.0, "max_margin_pct": 200.0}
        )
        ctx = _make_context(cost="100", proposed="150")  # 50% margin — within bounds
        report = safety_engine.evaluate(ctx, [version])
        db.commit()
        assert report.results[0].outcome == "PASS"

    def test_above_max_margin_triggers(self, safety_engine, repo, db):
        _, version = _make_published_version(
            repo, db, "percentage_change", {"max_margin_pct": 100.0}, mode="WARN"
        )
        ctx = _make_context(cost="100", proposed="500")  # 400% — exceeds 100%
        report = safety_engine.evaluate(ctx, [version])
        db.commit()
        result = report.results[0]
        assert result.outcome == "WARN"
        assert "max_margin_pct" in result.triggered_threshold

    def test_below_min_margin_triggers(self, safety_engine, repo, db):
        _, version = _make_published_version(
            repo, db, "percentage_change", {"min_margin_pct": 20.0}, mode="BLOCK"
        )
        ctx = _make_context(cost="100", proposed="105")  # 5% margin — below 20%
        report = safety_engine.evaluate(ctx, [version])
        db.commit()
        result = report.results[0]
        assert result.outcome == "BLOCK"
        assert "min_margin_pct" in result.triggered_threshold
        assert report.is_blocked

    def test_zero_cost_does_not_trigger(self, safety_engine, repo, db):
        _, version = _make_published_version(
            repo, db, "percentage_change", {"max_margin_pct": 100.0}
        )
        ctx = _make_context(cost="0", proposed="150")
        report = safety_engine.evaluate(ctx, [version])
        db.commit()
        assert report.results[0].outcome == "PASS"

    def test_evaluated_value_contains_margin_pct(self, safety_engine, repo, db):
        _, version = _make_published_version(
            repo, db, "percentage_change", {"max_margin_pct": 200.0}
        )
        ctx = _make_context(cost="100", proposed="150")
        report = safety_engine.evaluate(ctx, [version])
        db.commit()
        assert "margin_pct" in report.results[0].evaluated_value


# ── Policy type: missing_zero ─────────────────────────────────────────────────


class TestMissingZeroPolicy:
    def test_normal_price_is_pass(self, safety_engine, repo, db):
        _, version = _make_published_version(
            repo, db, "missing_zero", {"min_price_to_cost_ratio": 0.5}
        )
        ctx = _make_context(cost="100", proposed="90")  # 0.9 ratio — above 0.5
        report = safety_engine.evaluate(ctx, [version])
        db.commit()
        assert report.results[0].outcome == "PASS"

    def test_suspiciously_low_price_triggers(self, safety_engine, repo, db):
        _, version = _make_published_version(
            repo, db, "missing_zero", {"min_price_to_cost_ratio": 0.5}, mode="BLOCK"
        )
        ctx = _make_context(cost="100", proposed="10")  # 0.1 ratio — below 0.5
        report = safety_engine.evaluate(ctx, [version])
        db.commit()
        result = report.results[0]
        assert result.outcome == "BLOCK"
        assert "min_price_to_cost_ratio" in result.triggered_threshold
        assert report.is_blocked

    def test_zero_cost_is_pass(self, safety_engine, repo, db):
        _, version = _make_published_version(
            repo, db, "missing_zero", {"min_price_to_cost_ratio": 0.5}
        )
        ctx = _make_context(cost="0", proposed="5")
        report = safety_engine.evaluate(ctx, [version])
        db.commit()
        assert report.results[0].outcome == "PASS"

    def test_evaluated_value_contains_ratio(self, safety_engine, repo, db):
        _, version = _make_published_version(
            repo, db, "missing_zero", {"min_price_to_cost_ratio": 0.5}
        )
        ctx = _make_context(cost="100", proposed="80")
        report = safety_engine.evaluate(ctx, [version])
        db.commit()
        assert "price_to_cost_ratio" in report.results[0].evaluated_value


# ── Policy type: extra_zero ───────────────────────────────────────────────────


class TestExtraZeroPolicy:
    def test_normal_price_is_pass(self, safety_engine, repo, db):
        _, version = _make_published_version(
            repo, db, "extra_zero", {"max_price_to_cost_ratio": 10.0}
        )
        ctx = _make_context(cost="100", proposed="150")  # 1.5 ratio — below 10
        report = safety_engine.evaluate(ctx, [version])
        db.commit()
        assert report.results[0].outcome == "PASS"

    def test_suspiciously_high_price_triggers(self, safety_engine, repo, db):
        _, version = _make_published_version(
            repo, db, "extra_zero", {"max_price_to_cost_ratio": 10.0}, mode="REQUIRE_OVERRIDE"
        )
        ctx = _make_context(cost="100", proposed="2000")  # 20x ratio — above 10
        report = safety_engine.evaluate(ctx, [version])
        db.commit()
        result = report.results[0]
        assert result.outcome == "REQUIRE_OVERRIDE"
        assert "max_price_to_cost_ratio" in result.triggered_threshold
        assert report.requires_override

    def test_zero_cost_is_pass(self, safety_engine, repo, db):
        _, version = _make_published_version(
            repo, db, "extra_zero", {"max_price_to_cost_ratio": 10.0}
        )
        ctx = _make_context(cost="0", proposed="999")
        report = safety_engine.evaluate(ctx, [version])
        db.commit()
        assert report.results[0].outcome == "PASS"


# ── Policy type: historical_anomaly ──────────────────────────────────────────


class TestHistoricalAnomalyPolicy:
    def test_within_deviation_is_pass(self, safety_engine, repo, db):
        _, version = _make_published_version(
            repo, db, "historical_anomaly",
            {"reference_price": 100.0, "max_deviation_pct": 30.0}
        )
        ctx = _make_context(cost="80", proposed="120")  # 20% deviation from 100 — within 30%
        report = safety_engine.evaluate(ctx, [version])
        db.commit()
        assert report.results[0].outcome == "PASS"

    def test_exceeds_deviation_triggers(self, safety_engine, repo, db):
        _, version = _make_published_version(
            repo, db, "historical_anomaly",
            {"reference_price": 100.0, "max_deviation_pct": 30.0},
            mode="WARN",
        )
        ctx = _make_context(cost="80", proposed="200")  # 100% deviation from 100 — exceeds 30%
        report = safety_engine.evaluate(ctx, [version])
        db.commit()
        result = report.results[0]
        assert result.outcome == "WARN"
        assert "max_deviation_pct" in result.triggered_threshold
        assert report.has_warnings

    def test_zero_reference_is_pass(self, safety_engine, repo, db):
        _, version = _make_published_version(
            repo, db, "historical_anomaly",
            {"reference_price": 0.0, "max_deviation_pct": 30.0}
        )
        ctx = _make_context(cost="80", proposed="120")
        report = safety_engine.evaluate(ctx, [version])
        db.commit()
        assert report.results[0].outcome == "PASS"

    def test_evaluated_value_contains_deviation_pct(self, safety_engine, repo, db):
        _, version = _make_published_version(
            repo, db, "historical_anomaly",
            {"reference_price": 100.0, "max_deviation_pct": 50.0}
        )
        ctx = _make_context(cost="80", proposed="120")
        report = safety_engine.evaluate(ctx, [version])
        db.commit()
        assert "deviation_pct" in report.results[0].evaluated_value


# ── SafetyResult structure ─────────────────────────────────────────────────────


class TestSafetyResultStructure:
    def test_all_required_fields_present(self, safety_engine, repo, db):
        _, version = _make_published_version(
            repo, db, "percentage_change", {"max_margin_pct": 200.0}
        )
        ctx = _make_context()
        report = safety_engine.evaluate(ctx, [version])
        db.commit()
        result = report.results[0]

        assert result.id
        assert result.proposal_id == "prop-001"
        assert result.policy_version_id == version.id
        assert result.policy_name
        assert result.policy_mode in ("WARN", "BLOCK", "REQUIRE_OVERRIDE")
        assert result.outcome in ("PASS", "WARN", "BLOCK", "REQUIRE_OVERRIDE")
        assert result.created_at is not None

    def test_pass_result_has_no_triggered_threshold(self, safety_engine, repo, db):
        _, version = _make_published_version(
            repo, db, "percentage_change", {"max_margin_pct": 200.0}
        )
        ctx = _make_context(cost="100", proposed="150")  # 50% — within limit
        report = safety_engine.evaluate(ctx, [version])
        db.commit()
        result = report.results[0]
        assert result.outcome == "PASS"
        assert result.triggered_threshold is None

    def test_triggered_result_has_threshold_and_value(self, safety_engine, repo, db):
        _, version = _make_published_version(
            repo, db, "percentage_change", {"max_margin_pct": 20.0}
        )
        ctx = _make_context(cost="100", proposed="500")  # 400% — exceeds 20%
        report = safety_engine.evaluate(ctx, [version])
        db.commit()
        result = report.results[0]
        assert result.triggered_threshold is not None
        assert result.evaluated_value is not None


# ── Override framework ────────────────────────────────────────────────────────


class TestOverrideFramework:
    def test_record_override_creates_log(self, safety_engine, repo, db):
        _, version = _make_published_version(
            repo, db, "extra_zero", {"max_price_to_cost_ratio": 5.0}, mode="REQUIRE_OVERRIDE"
        )
        ctx = _make_context(cost="10", proposed="1000")
        report = safety_engine.evaluate(ctx, [version])
        db.commit()

        result = report.results[0]
        assert result.outcome == "REQUIRE_OVERRIDE"

        log = safety_engine.record_override(
            result.id,
            authorizing_user="manager@example.com",
            justification="Confirmed correct — premium product launch price.",
        )
        db.commit()

        assert log.safety_result_id == result.id
        assert log.authorizing_user == "manager@example.com"
        assert log.justification
        assert log.created_at is not None

    def test_override_requires_require_override_outcome(self, safety_engine, repo, db):
        _, version = _make_published_version(
            repo, db, "percentage_change", {"max_margin_pct": 200.0}, mode="WARN"
        )
        ctx = _make_context(cost="100", proposed="500")  # triggers WARN, not REQUIRE_OVERRIDE
        report = safety_engine.evaluate(ctx, [version])
        db.commit()

        with pytest.raises(ValueError, match="REQUIRE_OVERRIDE"):
            safety_engine.record_override(
                report.results[0].id,
                authorizing_user="admin",
                justification="Attempt to override WARN",
            )

    def test_override_missing_result_raises(self, safety_engine):
        with pytest.raises(ValueError, match="not found"):
            safety_engine.record_override(
                "nonexistent-id",
                authorizing_user="admin",
                justification="N/A",
            )

    def test_override_log_persisted_on_result(self, safety_engine, repo, db):
        _, version = _make_published_version(
            repo, db, "extra_zero", {"max_price_to_cost_ratio": 2.0}, mode="REQUIRE_OVERRIDE"
        )
        ctx = _make_context(cost="10", proposed="500")
        report = safety_engine.evaluate(ctx, [version])
        db.commit()

        result_id = report.results[0].id
        safety_engine.record_override(result_id, "user-X", "OK for bulk order pricing")
        db.commit()

        fetched = repo.get_result(result_id)
        assert len(fetched.override_log) == 1
        assert fetched.override_log[0].authorizing_user == "user-X"


# ── EvaluationReport properties ───────────────────────────────────────────────


class TestEvaluationReport:
    def test_all_pass_when_no_triggers(self, safety_engine, repo, db):
        _, v1 = _make_published_version(repo, db, "percentage_change", {"max_margin_pct": 500.0})
        _, v2 = _make_published_version(repo, db, "extra_zero", {"max_price_to_cost_ratio": 50.0})
        ctx = _make_context(cost="100", proposed="150")
        report = safety_engine.evaluate(ctx, [v1, v2])
        db.commit()
        assert report.all_pass
        assert not report.is_blocked
        assert not report.requires_override
        assert not report.has_warnings

    def test_is_blocked_when_any_block(self, safety_engine, repo, db):
        _, v_warn = _make_published_version(repo, db, "percentage_change", {"max_margin_pct": 20.0}, mode="WARN")
        _, v_block = _make_published_version(repo, db, "extra_zero", {"max_price_to_cost_ratio": 2.0}, mode="BLOCK")
        ctx = _make_context(cost="10", proposed="500")  # triggers both
        report = safety_engine.evaluate(ctx, [v_warn, v_block])
        db.commit()
        assert report.is_blocked
        assert report.has_warnings

    def test_requires_override_when_any_require_override(self, safety_engine, repo, db):
        _, version = _make_published_version(
            repo, db, "missing_zero", {"min_price_to_cost_ratio": 0.8}, mode="REQUIRE_OVERRIDE"
        )
        ctx = _make_context(cost="100", proposed="10")  # 0.1 — below 0.8
        report = safety_engine.evaluate(ctx, [version])
        db.commit()
        assert report.requires_override
        assert not report.is_blocked

    def test_multiple_results_stored(self, safety_engine, repo, db):
        _, v1 = _make_published_version(repo, db, "percentage_change", {"max_margin_pct": 500.0})
        _, v2 = _make_published_version(repo, db, "missing_zero", {"min_price_to_cost_ratio": 0.1})
        _, v3 = _make_published_version(repo, db, "extra_zero", {"max_price_to_cost_ratio": 100.0})
        ctx = _make_context(cost="100", proposed="150")
        report = safety_engine.evaluate(ctx, [v1, v2, v3])
        db.commit()
        assert len(report.results) == 3


# ── Policy versioning ─────────────────────────────────────────────────────────


class TestPolicyVersioning:
    def test_version_number_auto_increments(self, repo, db):
        policy = repo.create_policy(policy_type="percentage_change", display_name="R")
        db.commit()
        v1 = repo.create_version(policy.id, json.dumps({"max_margin_pct": 100.0}))
        v2 = repo.create_version(policy.id, json.dumps({"max_margin_pct": 200.0}))
        db.commit()
        assert v1.version_number == 1
        assert v2.version_number == 2

    def test_publish_already_published_raises(self, repo, db):
        policy = repo.create_policy(policy_type="percentage_change", display_name="R")
        db.commit()
        version = repo.create_version(policy.id, json.dumps({"max_margin_pct": 100.0}))
        db.commit()
        repo.publish_version(version.id)
        db.commit()
        with pytest.raises(ValueError, match="already published"):
            repo.publish_version(version.id)

    def test_old_version_remains_valid_after_new_version_published(self, repo, db):
        policy = repo.create_policy(policy_type="percentage_change", display_name="R")
        db.commit()
        v1 = repo.create_version(policy.id, json.dumps({"max_margin_pct": 100.0}))
        repo.publish_version(v1.id)
        v2 = repo.create_version(policy.id, json.dumps({"max_margin_pct": 200.0}))
        repo.publish_version(v2.id)
        db.commit()
        refetched = repo.get_published_version(v1.id)
        assert refetched is not None
        assert refetched.version_number == 1

    def test_draft_version_not_returned_by_get_published(self, repo, db):
        policy = repo.create_policy(policy_type="percentage_change", display_name="R")
        db.commit()
        draft = repo.create_version(policy.id, json.dumps({"max_margin_pct": 100.0}))
        db.commit()
        assert repo.get_published_version(draft.id) is None

    def test_threshold_change_creates_new_version_with_new_params(self, repo, db):
        policy = repo.create_policy(policy_type="percentage_change", display_name="R")
        db.commit()
        v1 = repo.create_version(policy.id, json.dumps({"max_margin_pct": 100.0}))
        repo.publish_version(v1.id)
        v2 = repo.create_version(policy.id, json.dumps({"max_margin_pct": 50.0}))
        repo.publish_version(v2.id)
        db.commit()
        p1 = json.loads(v1.parameters_json)
        p2 = json.loads(v2.parameters_json)
        assert p1["max_margin_pct"] == 100.0
        assert p2["max_margin_pct"] == 50.0


# ── Scoping support ───────────────────────────────────────────────────────────


class TestScopingSupport:
    def test_global_scope_policy(self, repo, db):
        policy = repo.create_policy(
            policy_type="percentage_change",
            display_name="Global margin",
            scope_type="global",
        )
        db.commit()
        assert policy.scope_type == "global"
        assert policy.scope_value is None

    def test_category_scope_policy(self, repo, db):
        policy = repo.create_policy(
            policy_type="missing_zero",
            display_name="Electronics floor",
            scope_type="category",
            scope_value="electronics",
        )
        db.commit()
        assert policy.scope_type == "category"
        assert policy.scope_value == "electronics"

    def test_brand_scope_policy(self, repo, db):
        policy = repo.create_policy(
            policy_type="extra_zero",
            display_name="BrandX ceiling",
            scope_type="brand",
            scope_value="brand-x",
        )
        db.commit()
        assert policy.scope_type == "brand"
        assert policy.scope_value == "brand-x"

    def test_user_scope_policy(self, repo, db):
        policy = repo.create_policy(
            policy_type="percentage_change",
            display_name="Operator limit",
            scope_type="user",
            scope_value="user-123",
        )
        db.commit()
        assert policy.scope_type == "user"

    def test_channel_scope_policy(self, repo, db):
        policy = repo.create_policy(
            policy_type="historical_anomaly",
            display_name="Channel price anomaly",
            scope_type="channel",
            scope_value="woocommerce-main",
        )
        db.commit()
        assert policy.scope_type == "channel"

    def test_get_published_versions_for_scope_filters_correctly(self, repo, db):
        global_policy = repo.create_policy(
            policy_type="percentage_change", display_name="Global", scope_type="global"
        )
        cat_policy = repo.create_policy(
            policy_type="missing_zero", display_name="Cat",
            scope_type="category", scope_value="electronics"
        )
        db.commit()
        for policy in [global_policy, cat_policy]:
            v = repo.create_version(policy.id, json.dumps({"max_margin_pct": 100.0, "min_price_to_cost_ratio": 0.5}))
            repo.publish_version(v.id)
        db.commit()

        cat_versions = repo.get_published_versions_for_scope("category", "electronics")
        assert len(cat_versions) == 1
        assert cat_versions[0].policy.scope_type == "category"

        global_versions = repo.get_published_versions_for_scope("global")
        assert len(global_versions) == 1
        assert global_versions[0].policy.scope_type == "global"

    def test_get_active_published_versions_returns_all_active(self, repo, db):
        for ptype in ["percentage_change", "missing_zero", "extra_zero"]:
            policy = repo.create_policy(policy_type=ptype, display_name=ptype)
            db.commit()
            v = repo.create_version(policy.id, json.dumps({"max_margin_pct": 100.0, "min_price_to_cost_ratio": 0.5, "max_price_to_cost_ratio": 10.0}))
            repo.publish_version(v.id)
        db.commit()
        versions = repo.get_active_published_versions()
        assert len(versions) == 3


# ── Repository safety result queries ─────────────────────────────────────────


class TestSafetyResultRepository:
    def test_list_results_for_proposal(self, safety_engine, repo, db):
        _, v1 = _make_published_version(repo, db, "percentage_change", {"max_margin_pct": 500.0})
        _, v2 = _make_published_version(repo, db, "extra_zero", {"max_price_to_cost_ratio": 100.0})
        ctx = _make_context(proposal_id="p-multi")
        safety_engine.evaluate(ctx, [v1, v2])
        db.commit()
        results = repo.list_results_for_proposal("p-multi")
        assert len(results) == 2

    def test_proposal_is_blocked(self, safety_engine, repo, db):
        _, version = _make_published_version(
            repo, db, "percentage_change", {"max_margin_pct": 10.0}, mode="BLOCK"
        )
        ctx = _make_context(proposal_id="p-block", cost="100", proposed="500")
        safety_engine.evaluate(ctx, [version])
        db.commit()
        assert repo.proposal_is_blocked("p-block") is True

    def test_proposal_not_blocked_when_only_warn(self, safety_engine, repo, db):
        _, version = _make_published_version(
            repo, db, "percentage_change", {"max_margin_pct": 10.0}, mode="WARN"
        )
        ctx = _make_context(proposal_id="p-warn", cost="100", proposed="500")
        safety_engine.evaluate(ctx, [version])
        db.commit()
        assert repo.proposal_is_blocked("p-warn") is False

    def test_proposal_requires_override(self, safety_engine, repo, db):
        _, version = _make_published_version(
            repo, db, "percentage_change", {"max_margin_pct": 10.0}, mode="REQUIRE_OVERRIDE"
        )
        ctx = _make_context(proposal_id="p-ro", cost="100", proposed="500")
        safety_engine.evaluate(ctx, [version])
        db.commit()
        assert repo.proposal_requires_override("p-ro") is True

    def test_proposal_requires_override_false_after_override(self, safety_engine, repo, db):
        _, version = _make_published_version(
            repo, db, "percentage_change", {"max_margin_pct": 10.0}, mode="REQUIRE_OVERRIDE"
        )
        ctx = _make_context(proposal_id="p-ro2", cost="100", proposed="500")
        report = safety_engine.evaluate(ctx, [version])
        db.commit()
        safety_engine.record_override(report.results[0].id, "manager", "Approved.")
        db.commit()
        assert repo.proposal_requires_override("p-ro2") is False

    def test_get_result_loads_override_log(self, safety_engine, repo, db):
        _, version = _make_published_version(
            repo, db, "extra_zero", {"max_price_to_cost_ratio": 2.0}, mode="REQUIRE_OVERRIDE"
        )
        ctx = _make_context(proposal_id="p-log", cost="10", proposed="500")
        report = safety_engine.evaluate(ctx, [version])
        db.commit()
        result_id = report.results[0].id
        safety_engine.record_override(result_id, "approver", "All good.")
        db.commit()
        fetched = repo.get_result(result_id)
        assert len(fetched.override_log) == 1


# ── Alembic migration a2_003 ──────────────────────────────────────────────────


class TestAlembicMigrationA2003:
    def test_upgrade_to_a2_003_creates_safety_tables(self, tmp_path):
        db_url = "sqlite:///" + str(tmp_path / "a2_003_test.db").replace("\\", "/")
        with patch.dict(os.environ, {"A2_DATABASE_URL": db_url}):
            cfg = Config("alembic_a2.ini")
            cfg.set_main_option("sqlalchemy.url", db_url)
            command.upgrade(cfg, "head")

        eng = create_engine(db_url)
        tables = set(inspect(eng).get_table_names())
        eng.dispose()

        assert "a2_safety_policies" in tables
        assert "a2_policy_versions" in tables
        assert "a2_safety_results" in tables
        assert "a2_override_logs" in tables
        # Earlier tables must also be present
        assert "a2_pricing_rules" in tables
        assert "source_definitions" in tables

    def test_downgrade_from_a2_003_removes_safety_tables(self, tmp_path):
        db_url = "sqlite:///" + str(tmp_path / "a2_003_down_test.db").replace("\\", "/")
        with patch.dict(os.environ, {"A2_DATABASE_URL": db_url}):
            cfg = Config("alembic_a2.ini")
            cfg.set_main_option("sqlalchemy.url", db_url)
            command.upgrade(cfg, "head")
            command.downgrade(cfg, "a2_002_r2")

        eng = create_engine(db_url)
        tables = set(inspect(eng).get_table_names())
        eng.dispose()

        assert "a2_safety_policies" not in tables
        assert "a2_policy_versions" not in tables
        assert "a2_safety_results" not in tables
        assert "a2_override_logs" not in tables
        assert "a2_pricing_rules" in tables

    def test_upgrade_to_a2_002_r2_does_not_create_safety_tables(self, tmp_path):
        db_url = "sqlite:///" + str(tmp_path / "a2_002_r2_only.db").replace("\\", "/")
        with patch.dict(os.environ, {"A2_DATABASE_URL": db_url}):
            cfg = Config("alembic_a2.ini")
            cfg.set_main_option("sqlalchemy.url", db_url)
            command.upgrade(cfg, "a2_002_r2")

        eng = create_engine(db_url)
        tables = set(inspect(eng).get_table_names())
        eng.dispose()

        assert "a2_pricing_rules" in tables
        assert "a2_safety_policies" not in tables


# ── Isolation ─────────────────────────────────────────────────────────────────


class TestIsolation:
    def test_safety_engine_does_not_import_future_phases(self):
        import importlib
        import re
        spec = importlib.util.find_spec("app.a2.engines.safety_engine")
        with open(spec.origin) as f:
            content = f.read()
        # Check for actual import statements (not docstring mentions)
        for forbidden in ["change_set", "dry_run", "execution_engine"]:
            pattern = rf"^(?:from|import)\s+.*{forbidden}", re.MULTILINE
            assert not re.search(rf"^(?:from|import)\s+.*{forbidden}", content, re.MULTILINE), \
                f"Found import of forbidden module {forbidden!r}"

    def test_safety_engine_does_not_write_to_woocommerce(self):
        import importlib
        import re
        spec = importlib.util.find_spec("app.a2.engines.safety_engine")
        with open(spec.origin) as f:
            content = f.read()
        # Check for actual import statements referencing WooCommerce client
        for forbidden in ["wcapi", "woocommerce_client", "import wc"]:
            assert forbidden not in content.lower(), \
                f"Found WooCommerce write reference {forbidden!r} in safety engine"
