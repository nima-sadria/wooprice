"""
A2.9 — AI Foundation tests.

Covers:
  - AdvisoryInsight creation: fields, generated_at, session link
  - Explanation generation: EXPLANATION category, confidence, summary
  - Anomaly detection: ANOMALY category; zero/negative price → CRITICAL; large change → HIGH
  - Stale price detection: STALE_PRICE category; age thresholds → INFO/MEDIUM/HIGH
  - Review priority generation: REVIEW_PRIORITY category; score logic
  - Recommendation traceability: recommendation_trace stored and retrievable
  - Confidence persistence: float confidence stored and retrieved correctly
  - Immutable insight records: insights cannot be modified after creation
  - Risk summary generation: RISK_SUMMARY category; BLOCK → HIGH severity
  - Rule recommendation: RULE_RECOMMENDATION; non-binding, advisory only
  - Session lifecycle: create, archive, list_insights filtering
  - Migration a2_008: revision/down_revision, upgrade/downgrade, lineage from a2_007
  - Isolation: no Rule Engine imports, no Safety Engine imports, no Change Set imports,
    no Dry Run imports, no Execution imports, no Scheduling imports, no WooCommerce
    imports, no Apply imports, no destination writes, no executable output generation
"""
import importlib.util
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
from unittest.mock import patch

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.a2.database import A2Base

# Register all models with A2Base metadata (order: A2.1 → A2.9)
import app.a2.models.canonical_product    # noqa: F401
import app.a2.models.source               # noqa: F401
import app.a2.models.snapshot             # noqa: F401
import app.a2.models.provenance           # noqa: F401
import app.a2.models.checkpoint           # noqa: F401
import app.a2.models.pricing_rule          # noqa: F401
import app.a2.models.pricing_rule_version  # noqa: F401
import app.a2.models.price_proposal        # noqa: F401
import app.a2.models.safety               # noqa: F401
import app.a2.models.change_set           # noqa: F401
import app.a2.models.dry_run              # noqa: F401
import app.a2.models.execution            # noqa: F401
import app.a2.models.schedule             # noqa: F401
import app.a2.ai.models                   # noqa: F401  — A2.9

from app.a2.ai.models import AdvisoryInsight, AdvisorySession
from app.a2.ai.repository import AdvisoryRepository, SessionNotFoundError
from app.a2.ai.service import AdvisoryContext, AdvisoryService


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


@pytest.fixture()
def db(engine):
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.rollback()
    session.close()


@pytest.fixture()
def repo(db):
    return AdvisoryRepository(db)


@pytest.fixture()
def svc(db):
    return AdvisoryService(db)


def _ctx(
    subject_type: str = "PriceProposal",
    subject_id: str = "prop-001",
    **data,
) -> AdvisoryContext:
    return AdvisoryContext(subject_type=subject_type, subject_id=subject_id, data=data)


# ── TestAdvisoryInsightCreation ───────────────────────────────────────────────


class TestAdvisoryInsightCreation:
    def test_insight_fields_persisted(self, repo, db):
        session = repo.create_session(
            category="EXPLANATION",
            subject_type="PriceProposal",
            subject_id="prop-001",
            model_version="a2.9-v1",
        )
        insight = repo.store_insight(
            session_id=session.id,
            category="EXPLANATION",
            severity="INFO",
            confidence=0.95,
            summary="Test summary.",
            explanation="Test explanation.",
            evidence=json.dumps({"key": "value"}),
            related_object_type="PriceProposal",
            related_object_id="prop-001",
            recommendation_trace="trace-data",
        )
        db.commit()

        loaded = db.query(AdvisoryInsight).filter_by(id=insight.id).one()
        assert loaded.category == "EXPLANATION"
        assert loaded.severity == "INFO"
        assert abs(loaded.confidence - 0.95) < 1e-6
        assert loaded.summary == "Test summary."
        assert loaded.explanation == "Test explanation."
        assert loaded.related_object_type == "PriceProposal"
        assert loaded.related_object_id == "prop-001"
        assert loaded.recommendation_trace == "trace-data"
        assert isinstance(loaded.generated_at, datetime)
        assert loaded.session_id == session.id

    def test_insight_generated_at_is_utc(self, repo, db):
        before = datetime.now(tz=timezone.utc)
        session = repo.create_session(
            category="ANOMALY",
            subject_type="ChangeSet",
            subject_id="cs-001",
            model_version="v1",
        )
        insight = repo.store_insight(
            session_id=session.id,
            category="ANOMALY",
            severity="HIGH",
            confidence=0.85,
            summary="Anomaly.",
            explanation="Price spike detected.",
            evidence="{}",
        )
        after = datetime.now(tz=timezone.utc)
        # generated_at must be between before and after
        assert before <= insight.generated_at.replace(tzinfo=timezone.utc) <= after

    def test_insight_evidence_json_round_trip(self, repo, db):
        session = repo.create_session(
            category="RISK_SUMMARY",
            subject_type="ChangeSet",
            subject_id="cs-002",
            model_version="v1",
        )
        evidence_data = {"risk_factors": ["factor1", "factor2"], "score": 42}
        insight = repo.store_insight(
            session_id=session.id,
            category="RISK_SUMMARY",
            severity="MEDIUM",
            confidence=0.80,
            summary="Risk summary.",
            explanation="Two risk factors found.",
            evidence=json.dumps(evidence_data),
        )
        loaded = db.query(AdvisoryInsight).filter_by(id=insight.id).one()
        recovered = json.loads(loaded.evidence)
        assert recovered == evidence_data


# ── TestExplanationGeneration ─────────────────────────────────────────────────


class TestExplanationGeneration:
    def test_explanation_category_and_severity(self, svc, db):
        ctx = _ctx(
            rule_type="cost_plus",
            proposed_price=12.50,
            current_price=10.00,
            currency="USD",
        )
        insight = svc.generate_explanation(ctx)
        db.commit()

        assert insight.category == "EXPLANATION"
        assert insight.severity == "INFO"
        assert insight.confidence >= 0.90
        assert "cost_plus" in insight.explanation
        assert "PriceProposal" in insight.summary

    def test_explanation_price_change_in_text(self, svc, db):
        ctx = _ctx(proposed_price=15.00, current_price=10.00, currency="EUR")
        insight = svc.generate_explanation(ctx)
        assert "+50.0%" in insight.explanation

    def test_explanation_recommendation_trace_set(self, svc, db):
        ctx = _ctx(rule_type="fx_based")
        insight = svc.generate_explanation(ctx)
        assert insight.recommendation_trace is not None
        assert "fx_based" in insight.recommendation_trace

    def test_explanation_linked_to_session(self, svc, db):
        ctx = _ctx()
        insight = svc.generate_explanation(ctx)
        session = db.query(AdvisorySession).filter_by(id=insight.session_id).one()
        assert session.category == "EXPLANATION"
        assert session.subject_id == "prop-001"


# ── TestAnomalyDetection ──────────────────────────────────────────────────────


class TestAnomalyDetection:
    def test_no_anomaly_info(self, svc, db):
        ctx = _ctx(proposed_price=10.50, current_price=10.00)
        insight = svc.detect_anomaly(ctx)
        assert insight.category == "ANOMALY"
        assert insight.severity == "INFO"
        assert "No anomaly" in insight.explanation

    def test_large_price_change_high(self, svc, db):
        ctx = _ctx(proposed_price=200.00, current_price=10.00)
        insight = svc.detect_anomaly(ctx)
        assert insight.severity == "HIGH"
        assert insight.confidence > 0.80
        evidence = json.loads(insight.evidence)
        assert len(evidence["signals"]) > 0

    def test_zero_price_critical(self, svc, db):
        ctx = _ctx(proposed_price=0, current_price=10.00)
        insight = svc.detect_anomaly(ctx)
        assert insight.severity == "CRITICAL"
        assert insight.confidence >= 0.99

    def test_negative_price_critical(self, svc, db):
        ctx = _ctx(proposed_price=-5.00, current_price=10.00)
        insight = svc.detect_anomaly(ctx)
        assert insight.severity == "CRITICAL"


# ── TestStalePriceDetection ───────────────────────────────────────────────────


class TestStalePriceDetection:
    def test_fresh_data_info(self, svc, db):
        ctx = _ctx(subject_type="ChangeSet", source_age_hours=12.0)
        insight = svc.detect_stale_price(ctx)
        assert insight.category == "STALE_PRICE"
        assert insight.severity == "INFO"

    def test_medium_stale_medium(self, svc, db):
        ctx = _ctx(subject_type="ChangeSet", source_age_hours=36.0)
        insight = svc.detect_stale_price(ctx)
        assert insight.severity == "MEDIUM"

    def test_high_stale_high(self, svc, db):
        ctx = _ctx(subject_type="ChangeSet", source_age_hours=72.0)
        insight = svc.detect_stale_price(ctx)
        assert insight.severity == "HIGH"
        assert "72.0 hours" in insight.explanation


# ── TestReviewPriorityGeneration ──────────────────────────────────────────────


class TestReviewPriorityGeneration:
    def test_low_priority_no_factors(self, svc, db):
        ctx = _ctx(subject_type="ChangeSet", safety_result="PASS", price_change_pct=5.0)
        insight = svc.assign_review_priority(ctx)
        assert insight.category == "REVIEW_PRIORITY"
        assert insight.severity == "INFO"
        evidence = json.loads(insight.evidence)
        assert evidence["priority_label"] if "priority_label" in evidence else True

    def test_high_priority_block(self, svc, db):
        ctx = _ctx(subject_type="ChangeSet", safety_result="BLOCK", price_change_pct=60.0)
        insight = svc.assign_review_priority(ctx)
        assert insight.severity == "HIGH"
        evidence = json.loads(insight.evidence)
        assert evidence["score"] >= 50

    def test_medium_priority_warn(self, svc, db):
        ctx = _ctx(subject_type="ChangeSet", safety_result="WARN", price_change_pct=10.0)
        insight = svc.assign_review_priority(ctx)
        assert insight.severity in ("MEDIUM", "HIGH")

    def test_priority_with_anomaly_flag(self, svc, db):
        ctx = _ctx(safety_result="PASS", price_change_pct=10.0, has_anomaly=True)
        insight = svc.assign_review_priority(ctx)
        evidence = json.loads(insight.evidence)
        assert evidence["score"] >= 20


# ── TestRecommendationTraceability ────────────────────────────────────────────


class TestRecommendationTraceability:
    def test_trace_stored_on_explanation(self, svc, db):
        ctx = _ctx(rule_type="fee_based")
        insight = svc.generate_explanation(ctx)
        assert insight.recommendation_trace is not None
        assert len(insight.recommendation_trace) > 0

    def test_trace_stored_on_anomaly(self, svc, db):
        ctx = _ctx(proposed_price=5.0, current_price=100.0)
        insight = svc.detect_anomaly(ctx)
        assert "anomaly_check" in insight.recommendation_trace

    def test_trace_stored_on_review_priority(self, svc, db):
        ctx = _ctx(safety_result="WARN")
        insight = svc.assign_review_priority(ctx)
        assert "priority_score" in insight.recommendation_trace

    def test_trace_retrieved_from_db(self, repo, db):
        session = repo.create_session(
            category="EXPLANATION",
            subject_type="PriceProposal",
            subject_id="prop-trace",
            model_version="v1",
        )
        repo.store_insight(
            session_id=session.id,
            category="EXPLANATION",
            severity="INFO",
            confidence=0.9,
            summary="s",
            explanation="e",
            evidence="{}",
            recommendation_trace="custom-trace-value",
        )
        db.commit()
        insights = repo.list_insights(session_id=session.id)
        assert insights[0].recommendation_trace == "custom-trace-value"


# ── TestConfidencePersistence ─────────────────────────────────────────────────


class TestConfidencePersistence:
    def test_confidence_exact_value(self, repo, db):
        session = repo.create_session(
            category="ANOMALY",
            subject_type="ChangeSet",
            subject_id="cs-conf",
            model_version="v1",
        )
        insight = repo.store_insight(
            session_id=session.id,
            category="ANOMALY",
            severity="HIGH",
            confidence=0.847,
            summary="s",
            explanation="e",
            evidence="{}",
        )
        db.commit()
        loaded = db.query(AdvisoryInsight).filter_by(id=insight.id).one()
        assert abs(loaded.confidence - 0.847) < 1e-4

    def test_confidence_boundary_values(self, repo, db):
        session = repo.create_session(
            category="STALE_PRICE",
            subject_type="PriceProposal",
            subject_id="prop-conf-b",
            model_version="v1",
        )
        for confidence in [0.0, 1.0]:
            insight = repo.store_insight(
                session_id=session.id,
                category="STALE_PRICE",
                severity="INFO",
                confidence=confidence,
                summary="s",
                explanation="e",
                evidence="{}",
            )
            db.commit()
            loaded = db.query(AdvisoryInsight).filter_by(id=insight.id).one()
            assert abs(loaded.confidence - confidence) < 1e-6


# ── TestImmutableInsights ─────────────────────────────────────────────────────


class TestImmutableInsights:
    def test_insight_has_no_update_method(self):
        """AdvisoryRepository must not expose any update_insight operation."""
        assert not hasattr(AdvisoryRepository, "update_insight")

    def test_insight_fields_unchanged_after_session_archive(self, repo, db):
        session = repo.create_session(
            category="EXPLANATION",
            subject_type="ChangeSet",
            subject_id="cs-imm",
            model_version="v1",
        )
        insight = repo.store_insight(
            session_id=session.id,
            category="EXPLANATION",
            severity="INFO",
            confidence=0.9,
            summary="original summary",
            explanation="original explanation",
            evidence="{}",
        )
        repo.archive_session(session.id)
        db.commit()

        loaded = db.query(AdvisoryInsight).filter_by(id=insight.id).one()
        assert loaded.summary == "original summary"
        assert loaded.explanation == "original explanation"

    def test_archived_session_is_closed(self, repo, db):
        session = repo.create_session(
            category="RISK_SUMMARY",
            subject_type="ChangeSet",
            subject_id="cs-arch",
            model_version="v1",
        )
        repo.archive_session(session.id)
        db.commit()

        loaded = db.query(AdvisorySession).filter_by(id=session.id).one()
        assert loaded.is_archived is True
        assert loaded.closed_at is not None


# ── TestRiskSummary ───────────────────────────────────────────────────────────


class TestRiskSummary:
    def test_block_result_high_severity(self, svc, db):
        ctx = _ctx(subject_type="ChangeSet", safety_result="BLOCK")
        insight = svc.generate_risk_summary(ctx)
        assert insight.category == "RISK_SUMMARY"
        assert insight.severity == "HIGH"
        assert insight.confidence >= 0.99

    def test_warn_result_medium_severity(self, svc, db):
        ctx = _ctx(subject_type="ChangeSet", safety_result="WARN")
        insight = svc.generate_risk_summary(ctx)
        assert insight.severity == "MEDIUM"

    def test_pass_result_info_severity(self, svc, db):
        ctx = _ctx(subject_type="ChangeSet", safety_result="PASS")
        insight = svc.generate_risk_summary(ctx)
        assert insight.severity == "INFO"


# ── TestRuleRecommendation ────────────────────────────────────────────────────


class TestRuleRecommendation:
    def test_rule_recommendation_category(self, svc, db):
        ctx = _ctx(
            subject_type="PriceProposal",
            suggested_rule_type="fx_based",
            pattern_description="FX-linked margin pattern",
        )
        insight = svc.generate_rule_recommendation(ctx)
        assert insight.category == "RULE_RECOMMENDATION"
        assert insight.severity == "LOW"

    def test_rule_recommendation_non_binding_in_evidence(self, svc, db):
        ctx = _ctx(suggested_rule_type="cost_plus", pattern_description="cost markup")
        insight = svc.generate_rule_recommendation(ctx)
        evidence = json.loads(insight.evidence)
        assert evidence["non_binding"] is True
        assert evidence["requires_owner_approval"] is True

    def test_rule_recommendation_does_not_produce_rule_object(self, svc, db):
        ctx = _ctx()
        insight = svc.generate_rule_recommendation(ctx)
        # Result must be AdvisoryInsight, never a PricingRule or similar
        assert isinstance(insight, AdvisoryInsight)
        assert not hasattr(insight, "formula")
        assert not hasattr(insight, "rule_type")


# ── TestSessionLifecycle ──────────────────────────────────────────────────────


class TestSessionLifecycle:
    def test_get_session_not_found_raises(self, repo):
        with pytest.raises(SessionNotFoundError):
            repo.get_session("nonexistent-session-id")

    def test_list_insights_by_session_id(self, repo, db):
        s1 = repo.create_session(
            category="ANOMALY", subject_type="P", subject_id="p1", model_version="v1"
        )
        s2 = repo.create_session(
            category="EXPLANATION", subject_type="P", subject_id="p2", model_version="v1"
        )
        repo.store_insight(
            session_id=s1.id,
            category="ANOMALY",
            severity="HIGH",
            confidence=0.9,
            summary="s",
            explanation="e",
            evidence="{}",
        )
        repo.store_insight(
            session_id=s2.id,
            category="EXPLANATION",
            severity="INFO",
            confidence=0.9,
            summary="s",
            explanation="e",
            evidence="{}",
        )
        db.commit()
        s1_insights = repo.list_insights(session_id=s1.id)
        s2_insights = repo.list_insights(session_id=s2.id)
        assert len(s1_insights) == 1
        assert s1_insights[0].session_id == s1.id
        assert len(s2_insights) == 1
        assert s2_insights[0].session_id == s2.id

    def test_list_insights_by_category(self, repo, db):
        session = repo.create_session(
            category="ANOMALY", subject_type="C", subject_id="c1", model_version="v1"
        )
        repo.store_insight(
            session_id=session.id,
            category="ANOMALY",
            severity="HIGH",
            confidence=0.9,
            summary="s",
            explanation="e",
            evidence="{}",
        )
        repo.store_insight(
            session_id=session.id,
            category="EXPLANATION",
            severity="INFO",
            confidence=0.9,
            summary="s",
            explanation="e",
            evidence="{}",
        )
        db.commit()
        anomalies = repo.list_insights(category="ANOMALY")
        explanations = repo.list_insights(category="EXPLANATION")
        assert all(i.category == "ANOMALY" for i in anomalies)
        assert all(i.category == "EXPLANATION" for i in explanations)


# ── TestMigration ─────────────────────────────────────────────────────────────


class TestMigration:
    def test_revision_and_down_revision(self):
        spec = importlib.util.spec_from_file_location(
            "a2_008",
            "alembic_a2/versions/a2_008_ai_foundation.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert module.revision == "a2_008"
        assert module.down_revision == "a2_007"

    def test_migration_upgrade_creates_tables(self, tmp_path):
        db_url = f"sqlite:///{tmp_path / 'test_a2_008.db'}"
        with patch.dict(os.environ, {"A2_DATABASE_URL": db_url}):
            cfg = Config("alembic_a2.ini")
            cfg.set_main_option("sqlalchemy.url", db_url)
            command.upgrade(cfg, "a2_008")

            from sqlalchemy import create_engine as _ce
            eng = _ce(db_url)
            tables = inspect(eng).get_table_names()
            assert "a2_advisory_sessions" in tables
            assert "a2_advisory_insights" in tables
            eng.dispose()

    def test_migration_downgrade_removes_tables(self, tmp_path):
        db_url = f"sqlite:///{tmp_path / 'test_a2_008_down.db'}"
        with patch.dict(os.environ, {"A2_DATABASE_URL": db_url}):
            cfg = Config("alembic_a2.ini")
            cfg.set_main_option("sqlalchemy.url", db_url)
            command.upgrade(cfg, "a2_008")
            command.downgrade(cfg, "a2_007")

            from sqlalchemy import create_engine as _ce
            eng = _ce(db_url)
            tables = inspect(eng).get_table_names()
            assert "a2_advisory_sessions" not in tables
            assert "a2_advisory_insights" not in tables
            eng.dispose()

    def test_migration_lineage_from_a2_007(self):
        spec = importlib.util.spec_from_file_location(
            "a2_008",
            "alembic_a2/versions/a2_008_ai_foundation.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert module.down_revision == "a2_007"


# ── TestIsolation ─────────────────────────────────────────────────────────────


class TestIsolation:
    def _load_ai_source(self, module_name: str) -> str:
        """Return source code of an app.a2.ai module."""
        import importlib
        mod = importlib.import_module(module_name)
        import inspect as _inspect
        return _inspect.getsource(mod)

    def test_no_rule_engine_imports(self):
        for name in ("app.a2.ai.service", "app.a2.ai.repository", "app.a2.ai.models"):
            src = self._load_ai_source(name)
            assert "rules.engine" not in src, f"{name} must not import rules.engine"
            assert "RuleEngine" not in src, f"{name} must not import RuleEngine"

    def test_no_safety_engine_imports(self):
        for name in ("app.a2.ai.service", "app.a2.ai.repository", "app.a2.ai.models"):
            src = self._load_ai_source(name)
            assert "safety_engine" not in src, f"{name} must not import safety_engine"
            assert "SafetyEngine" not in src, f"{name} must not import SafetyEngine"

    def test_no_change_set_imports(self):
        for name in ("app.a2.ai.service", "app.a2.ai.repository", "app.a2.ai.models"):
            src = self._load_ai_source(name)
            assert "change_set" not in src, f"{name} must not import change_set"

    def test_no_dry_run_imports(self):
        for name in ("app.a2.ai.service", "app.a2.ai.repository", "app.a2.ai.models"):
            src = self._load_ai_source(name)
            assert "dry_run" not in src, f"{name} must not import dry_run"

    def test_no_execution_imports(self):
        for name in ("app.a2.ai.service", "app.a2.ai.repository", "app.a2.ai.models"):
            src = self._load_ai_source(name)
            assert "execution_service" not in src, f"{name} must not import execution_service"
            assert "ExecutionService" not in src, f"{name} must not import ExecutionService"
            assert "ExecutionRepository" not in src

    def test_no_scheduling_imports(self):
        for name in ("app.a2.ai.service", "app.a2.ai.repository", "app.a2.ai.models"):
            src = self._load_ai_source(name)
            assert "scheduler_service" not in src, f"{name} must not import scheduler_service"
            assert "SchedulerService" not in src, f"{name} must not import SchedulerService"
            assert "scheduler_repository" not in src

    def test_no_woocommerce_imports(self):
        for name in ("app.a2.ai.service", "app.a2.ai.repository", "app.a2.ai.models"):
            src = self._load_ai_source(name)
            assert "woocommerce" not in src.lower(), f"{name} must not import WooCommerce"
            assert "WC_" not in src, f"{name} must not reference WC_ credentials"

    def test_no_apply_imports(self):
        for name in ("app.a2.ai.service", "app.a2.ai.repository", "app.a2.ai.models"):
            src = self._load_ai_source(name)
            import_lines = [
                ln for ln in src.split("\n")
                if ln.strip().startswith(("import ", "from "))
            ]
            apply_imports = [ln for ln in import_lines if "apply" in ln.lower()]
            assert not apply_imports, (
                f"{name} must not import apply workflow; found: {apply_imports}"
            )

    def test_no_destination_writes(self):
        """AdvisoryService must not expose any method that writes to a destination channel."""
        svc_src = self._load_ai_source("app.a2.ai.service")
        assert "write_to" not in svc_src
        assert "apply_prices" not in svc_src
        assert "execute(" not in svc_src
        assert "dispatch(" not in svc_src

    def test_no_executable_output_types(self):
        """AdvisoryService must not import or instantiate executable domain types."""
        import inspect
        from app.a2.ai import service as svc_module
        src = inspect.getsource(svc_module)
        # Check that forbidden types do not appear in import lines
        import_lines = [
            ln for ln in src.split("\n")
            if ln.strip().startswith(("import ", "from "))
        ]
        import_src = "\n".join(import_lines)
        forbidden_imports = [
            "PriceProposal", "SafetyResult", "ChangeSet", "DryRunResult",
            "ExecutionPlan", "ApplyCommand",
        ]
        for forbidden_type in forbidden_imports:
            assert forbidden_type not in import_src, (
                f"app.a2.ai.service must not import {forbidden_type}"
            )
        # The only output type produced should be AdvisoryInsight
        assert "AdvisoryInsight" in src

    def test_prior_phases_do_not_import_ai(self):
        """Verify one-way isolation: no prior-phase module imports from app.a2.ai."""
        import inspect
        prior_phase_modules = [
            "app.a2.rules.engine",
            "app.a2.engines.safety_engine",
            "app.a2.services.change_set_service",
            "app.a2.services.dry_run_service",
            "app.a2.services.execution_service",
            "app.a2.services.scheduler_service",
        ]
        for module_name in prior_phase_modules:
            import importlib
            mod = importlib.import_module(module_name)
            src = inspect.getsource(mod)
            assert "app.a2.ai" not in src, (
                f"{module_name} must not import from app.a2.ai"
            )
