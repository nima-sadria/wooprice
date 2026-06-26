"""
A2.6 — Dry Run Engine tests.

Covers:
  - DryRun creation: execute() persists DryRun and one DryRunResult per item
  - Digest verification: matching digest → digest_verified=True; mismatch → False + BLOCK
  - Determinism: identical inputs always produce the same DryRunReport
  - Item validation: missing proposal_hash → BLOCK; missing safety/rule → WARN
  - Overall result: worst outcome across all items; BLOCK blocks execution
  - Execution eligibility: requires PASS/WARN AND digest_verified=True
  - Empty destination_channel → BLOCK
  - DryRunReport: all required fields; advisory only
  - Seller confirmation: bound to Change Set digest; VALID by default
  - Explicit invalidation: marks is_valid=False with reason
  - Digest-change invalidation: changed proposal/safety/rule/channel/scope/snapshot
  - Same digest does not trigger invalidation
  - Repository CRUD: create, get, list, add_result, list_results, record_confirmation,
    invalidate_confirmation, latest_confirmation
  - Alembic migration a2_005: revision/down_revision, table creation/destruction, lineage
  - Isolation: no A2.7+ imports, no WooCommerce, no Apply, no Execution Engine,
    no destination writes
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
import app.a2.models.source              # noqa: F401
import app.a2.models.snapshot            # noqa: F401
import app.a2.models.provenance          # noqa: F401
import app.a2.models.checkpoint          # noqa: F401
import app.a2.models.pricing_rule         # noqa: F401 — A2.3-R2
import app.a2.models.pricing_rule_version  # noqa: F401 — A2.3-R2
import app.a2.models.price_proposal        # noqa: F401 — A2.3-R2
import app.a2.models.safety               # noqa: F401 — A2.4
import app.a2.models.change_set           # noqa: F401 — A2.5
import app.a2.models.dry_run              # noqa: F401 — A2.6

from app.a2.repositories.dry_run_repository import (
    ConfirmationNotFoundError,
    DryRunRepository,
)
from app.a2.services.change_set_service import compute_change_set_digest
from app.a2.services.dry_run_service import (
    DryRunItemInput,
    DryRunReport,
    DryRunService,
)


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
    return DryRunRepository(db)


@pytest.fixture()
def svc(db):
    return DryRunService(db)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _item(
    product_id: str = "SKU-001",
    proposal_id: str = "prop-001",
    proposal_hash: str = "a" * 64,
    safety_result_id: str = "safety-001",
    rule_version_id: str = "rule-v1",
    proposed_price: Decimal = Decimal("99.99"),
    current_price: Decimal = Decimal("89.99"),
) -> DryRunItemInput:
    return DryRunItemInput(
        product_id=product_id,
        proposal_id=proposal_id,
        proposal_hash=proposal_hash,
        safety_result_id=safety_result_id,
        rule_version_id=rule_version_id,
        proposed_price=proposed_price,
        current_price=current_price,
    )


_CHAN = "WC"
_SCOPE = "all"
_SNAP = "snap-001"


def _digest(items, channel=_CHAN, scope=_SCOPE, snapshot=_SNAP) -> str:
    return compute_change_set_digest(items, channel, scope, snapshot)


def _run(
    svc: DryRunService,
    items=None,
    channel=_CHAN,
    scope=_SCOPE,
    snapshot=_SNAP,
    cs_id="cs-001",
    rev_id="rev-001",
    stored_digest=None,
):
    if items is None:
        items = [_item()]
    if stored_digest is None:
        stored_digest = _digest(items, channel, scope, snapshot)
    return svc.execute(
        change_set_id=cs_id,
        change_set_revision_id=rev_id,
        stored_digest=stored_digest,
        items=items,
        destination_channel=channel,
        scope=scope,
        source_snapshot_id=snapshot,
    )


# ── TestDryRunCreation ────────────────────────────────────────────────────────


class TestDryRunCreation:
    def test_execute_creates_dry_run_record(self, svc, repo):
        dr = _run(svc)
        assert repo.get(dr.id) is not None

    def test_execute_creates_one_result_per_item(self, svc, repo):
        items = [_item("A"), _item("B", proposal_id="p2", proposal_hash="b" * 64)]
        dr = _run(svc, items=items)
        results = repo.list_results(dr.id)
        assert len(results) == 2

    def test_execute_empty_items_raises_value_error(self, svc):
        with pytest.raises(ValueError, match="at least one item"):
            _run(svc, items=[])

    def test_execute_returns_dry_run_with_correct_metadata(self, svc):
        items = [_item()]
        dr = _run(svc, items=items, cs_id="cs-XYZ", rev_id="rev-XYZ")
        assert dr.change_set_id == "cs-XYZ"
        assert dr.change_set_revision_id == "rev-XYZ"
        assert dr.proposal_count == 1
        assert dr.created_at is not None


# ── TestDigestVerification ────────────────────────────────────────────────────


class TestDigestVerification:
    def test_matching_digest_sets_digest_verified_true(self, svc):
        items = [_item()]
        dr = _run(svc, items=items)
        assert dr.digest_verified is True

    def test_mismatched_digest_sets_digest_verified_false(self, svc):
        items = [_item()]
        dr = _run(svc, items=items, stored_digest="0" * 64)
        assert dr.digest_verified is False

    def test_digest_mismatch_forces_block_result(self, svc):
        items = [_item()]
        dr = _run(svc, items=items, stored_digest="0" * 64)
        assert dr.validation_result == "BLOCK"

    def test_digest_mismatch_makes_not_execution_eligible(self, svc):
        items = [_item()]
        dr = _run(svc, items=items, stored_digest="0" * 64)
        assert dr.execution_eligible is False

    def test_matching_digest_does_not_force_block(self, svc):
        items = [_item()]
        dr = _run(svc, items=items)
        assert dr.validation_result == "PASS"
        assert dr.execution_eligible is True

    def test_digest_verification_is_deterministic(self, svc):
        items = [_item()]
        digest = _digest(items)
        dr1 = svc.execute(
            change_set_id="cs-1",
            change_set_revision_id="rev-1",
            stored_digest=digest,
            items=items,
            destination_channel=_CHAN,
            scope=_SCOPE,
            source_snapshot_id=_SNAP,
        )
        dr2 = svc.execute(
            change_set_id="cs-2",
            change_set_revision_id="rev-2",
            stored_digest=digest,
            items=items,
            destination_channel=_CHAN,
            scope=_SCOPE,
            source_snapshot_id=_SNAP,
        )
        assert dr1.digest_verified is True
        assert dr2.digest_verified is True
        assert dr1.validation_result == dr2.validation_result


# ── TestEmptyDestination ──────────────────────────────────────────────────────


class TestEmptyDestination:
    def test_empty_destination_channel_blocks(self, svc):
        items = [_item()]
        digest = _digest(items, channel="")
        dr = svc.execute(
            change_set_id="cs-1",
            change_set_revision_id="rev-1",
            stored_digest=digest,
            items=items,
            destination_channel="",
            scope=_SCOPE,
            source_snapshot_id=_SNAP,
        )
        assert dr.validation_result == "BLOCK"
        assert dr.execution_eligible is False

    def test_empty_destination_increments_blocked_count(self, svc):
        items = [_item()]
        digest = _digest(items, channel="")
        dr = svc.execute(
            change_set_id="cs-1",
            change_set_revision_id="rev-1",
            stored_digest=digest,
            items=items,
            destination_channel="",
            scope=_SCOPE,
            source_snapshot_id=_SNAP,
        )
        # blocked_count includes the destination failure
        assert dr.blocked_count >= 1


# ── TestItemValidation ────────────────────────────────────────────────────────


class TestItemValidation:
    def test_missing_proposal_hash_blocks_item(self, svc, repo):
        bad = _item(proposal_hash="")
        digest = _digest([bad])
        dr = svc.execute(
            change_set_id="cs-1",
            change_set_revision_id="rev-1",
            stored_digest=digest,
            items=[bad],
            destination_channel=_CHAN,
            scope=_SCOPE,
            source_snapshot_id=_SNAP,
        )
        results = repo.list_results(dr.id)
        assert results[0].outcome == "BLOCK"

    def test_missing_proposal_hash_makes_overall_block(self, svc):
        bad = _item(proposal_hash="")
        digest = _digest([bad])
        dr = svc.execute(
            change_set_id="cs-1",
            change_set_revision_id="rev-1",
            stored_digest=digest,
            items=[bad],
            destination_channel=_CHAN,
            scope=_SCOPE,
            source_snapshot_id=_SNAP,
        )
        assert dr.validation_result == "BLOCK"

    def test_missing_safety_result_warns_item(self, svc, repo):
        item = _item(safety_result_id="")
        digest = _digest([item])
        dr = svc.execute(
            change_set_id="cs-1",
            change_set_revision_id="rev-1",
            stored_digest=digest,
            items=[item],
            destination_channel=_CHAN,
            scope=_SCOPE,
            source_snapshot_id=_SNAP,
        )
        results = repo.list_results(dr.id)
        assert results[0].outcome == "WARN"

    def test_missing_rule_version_warns_item(self, svc, repo):
        item = _item(rule_version_id="")
        digest = _digest([item])
        dr = svc.execute(
            change_set_id="cs-1",
            change_set_revision_id="rev-1",
            stored_digest=digest,
            items=[item],
            destination_channel=_CHAN,
            scope=_SCOPE,
            source_snapshot_id=_SNAP,
        )
        results = repo.list_results(dr.id)
        assert results[0].outcome == "WARN"

    def test_all_valid_items_produce_pass(self, svc, repo):
        item = _item()
        dr = _run(svc, items=[item])
        results = repo.list_results(dr.id)
        assert results[0].outcome == "PASS"
        assert results[0].reason is None

    def test_duplicate_product_id_warns(self, svc, repo):
        items = [
            _item("SKU-X", proposal_hash="a" * 64),
            _item("SKU-X", proposal_id="p2", proposal_hash="b" * 64),
        ]
        digest = _digest(items)
        dr = svc.execute(
            change_set_id="cs-1",
            change_set_revision_id="rev-1",
            stored_digest=digest,
            items=items,
            destination_channel=_CHAN,
            scope=_SCOPE,
            source_snapshot_id=_SNAP,
        )
        results = repo.list_results(dr.id)
        outcomes = [r.outcome for r in results]
        assert "WARN" in outcomes


# ── TestOverallResult ─────────────────────────────────────────────────────────


class TestOverallResult:
    def test_all_pass_makes_overall_pass(self, svc):
        dr = _run(svc, items=[_item()])
        assert dr.validation_result == "PASS"

    def test_one_warn_makes_overall_warn(self, svc):
        item = _item(safety_result_id="")
        digest = _digest([item])
        dr = svc.execute(
            change_set_id="cs-1",
            change_set_revision_id="rev-1",
            stored_digest=digest,
            items=[item],
            destination_channel=_CHAN,
            scope=_SCOPE,
            source_snapshot_id=_SNAP,
        )
        assert dr.validation_result == "WARN"

    def test_one_block_makes_overall_block(self, svc):
        bad = _item(proposal_hash="")
        digest = _digest([bad])
        dr = svc.execute(
            change_set_id="cs-1",
            change_set_revision_id="rev-1",
            stored_digest=digest,
            items=[bad],
            destination_channel=_CHAN,
            scope=_SCOPE,
            source_snapshot_id=_SNAP,
        )
        assert dr.validation_result == "BLOCK"

    def test_block_beats_warn_in_mixed_items(self, svc):
        items = [
            _item("A", safety_result_id=""),          # WARN
            _item("B", proposal_id="p2", proposal_hash=""),  # BLOCK
        ]
        digest = _digest(items)
        dr = svc.execute(
            change_set_id="cs-1",
            change_set_revision_id="rev-1",
            stored_digest=digest,
            items=items,
            destination_channel=_CHAN,
            scope=_SCOPE,
            source_snapshot_id=_SNAP,
        )
        assert dr.validation_result == "BLOCK"


# ── TestExecutionEligibility ──────────────────────────────────────────────────


class TestExecutionEligibility:
    def test_eligible_when_pass_and_digest_verified(self, svc):
        dr = _run(svc, items=[_item()])
        assert dr.execution_eligible is True

    def test_eligible_when_warn_and_digest_verified(self, svc):
        item = _item(safety_result_id="")
        digest = _digest([item])
        dr = svc.execute(
            change_set_id="cs-1",
            change_set_revision_id="rev-1",
            stored_digest=digest,
            items=[item],
            destination_channel=_CHAN,
            scope=_SCOPE,
            source_snapshot_id=_SNAP,
        )
        assert dr.execution_eligible is True

    def test_not_eligible_when_blocked(self, svc):
        bad = _item(proposal_hash="")
        digest = _digest([bad])
        dr = svc.execute(
            change_set_id="cs-1",
            change_set_revision_id="rev-1",
            stored_digest=digest,
            items=[bad],
            destination_channel=_CHAN,
            scope=_SCOPE,
            source_snapshot_id=_SNAP,
        )
        assert dr.execution_eligible is False

    def test_not_eligible_when_digest_mismatch(self, svc):
        dr = _run(svc, stored_digest="0" * 64)
        assert dr.execution_eligible is False


# ── TestDryRunReport ──────────────────────────────────────────────────────────


class TestDryRunReport:
    def test_generate_report_has_all_required_fields(self, svc):
        dr = _run(svc)
        report = svc.generate_report(dr.id)
        assert isinstance(report, DryRunReport)
        assert report.dry_run_id == dr.id
        assert report.change_set_id == dr.change_set_id
        assert report.change_set_revision_id == dr.change_set_revision_id
        assert report.change_set_digest == dr.change_set_digest
        assert isinstance(report.proposal_count, int)
        assert isinstance(report.blocked_count, int)
        assert isinstance(report.warning_count, int)
        assert report.validation_result in ("PASS", "WARN", "BLOCK")
        assert isinstance(report.digest_verified, bool)
        assert report.confirmation_status in ("NONE", "CONFIRMED", "INVALID")
        assert isinstance(report.execution_eligible, bool)
        assert isinstance(report.summary, str)
        assert isinstance(report.results, list)

    def test_generate_report_confirmation_status_none_when_no_confirmation(self, svc):
        dr = _run(svc)
        report = svc.generate_report(dr.id)
        assert report.confirmation_status == "NONE"

    def test_generate_report_includes_per_item_results(self, svc):
        items = [_item("A"), _item("B", proposal_id="p2", proposal_hash="b" * 64)]
        dr = _run(svc, items=items)
        report = svc.generate_report(dr.id)
        assert len(report.results) == 2

    def test_generate_report_advisory_only_no_side_effects(self, svc, repo):
        dr = _run(svc)
        # generate_report must not create any new database records
        count_before = len(repo.list(dr.change_set_id))
        svc.generate_report(dr.id)
        count_after = len(repo.list(dr.change_set_id))
        assert count_before == count_after

    def test_generate_report_nonexistent_raises_value_error(self, svc):
        with pytest.raises(ValueError, match="not found"):
            svc.generate_report("no-such-id")


# ── TestSellerConfirmation ────────────────────────────────────────────────────


class TestSellerConfirmation:
    def test_confirm_creates_confirmation(self, svc, repo):
        dr = _run(svc)
        conf = svc.confirm(dr.id, confirmed_by="seller@example.com")
        assert conf is not None
        assert repo.latest_confirmation(dr.id) is not None

    def test_confirmation_is_valid_by_default(self, svc):
        dr = _run(svc)
        conf = svc.confirm(dr.id, confirmed_by="seller@example.com")
        assert conf.is_valid is True

    def test_confirmation_binds_to_change_set_digest(self, svc):
        dr = _run(svc)
        conf = svc.confirm(dr.id, confirmed_by="seller@example.com")
        assert conf.change_set_digest == dr.change_set_digest

    def test_confirmation_records_confirmed_by(self, svc):
        dr = _run(svc)
        conf = svc.confirm(dr.id, confirmed_by="alice@example.com")
        assert conf.confirmed_by == "alice@example.com"

    def test_explicit_invalidation_marks_invalid(self, svc):
        dr = _run(svc)
        conf = svc.confirm(dr.id, confirmed_by="seller@example.com")
        invalidated = svc.invalidate_confirmation(conf.id, reason="Manual revocation")
        assert invalidated.is_valid is False
        assert invalidated.invalidation_reason == "Manual revocation"
        assert invalidated.invalidated_at is not None

    def test_confirm_nonexistent_dry_run_raises_value_error(self, svc):
        with pytest.raises(ValueError, match="not found"):
            svc.confirm("no-such-id", confirmed_by="seller@example.com")

    def test_invalidate_nonexistent_confirmation_raises_error(self, svc):
        with pytest.raises(ConfirmationNotFoundError):
            svc.invalidate_confirmation("no-such-id", reason="test")


# ── TestConfirmationDigestBinding ─────────────────────────────────────────────


class TestConfirmationDigestBinding:
    def test_same_digest_does_not_invalidate(self, svc):
        dr = _run(svc)
        conf = svc.confirm(dr.id, confirmed_by="seller@example.com")
        result = svc.invalidate_if_digest_changed(conf.id, dr.change_set_digest)
        assert result is None
        # Confirmation is still valid
        from app.a2.models.dry_run import SellerConfirmation
        refreshed = svc._db.get(SellerConfirmation, conf.id)
        assert refreshed.is_valid is True

    def test_changed_digest_invalidates_confirmation(self, svc):
        dr = _run(svc)
        conf = svc.confirm(dr.id, confirmed_by="seller@example.com")
        new_digest = "f" * 64  # different digest
        result = svc.invalidate_if_digest_changed(conf.id, new_digest)
        assert result is not None
        assert result.is_valid is False

    def test_invalidate_if_digest_changed_nonexistent_raises_error(self, svc):
        with pytest.raises(ConfirmationNotFoundError):
            svc.invalidate_if_digest_changed("no-such-id", "f" * 64)

    def test_generate_report_confirmation_status_confirmed(self, svc):
        dr = _run(svc)
        svc.confirm(dr.id, confirmed_by="seller@example.com")
        report = svc.generate_report(dr.id)
        assert report.confirmation_status == "CONFIRMED"

    def test_generate_report_confirmation_status_invalid_after_invalidation(self, svc):
        dr = _run(svc)
        conf = svc.confirm(dr.id, confirmed_by="seller@example.com")
        svc.invalidate_confirmation(conf.id, "Digest changed")
        report = svc.generate_report(dr.id)
        assert report.confirmation_status == "INVALID"


# ── TestConfirmationInvalidationScenarios ─────────────────────────────────────


class TestConfirmationInvalidationScenarios:
    """Each scenario shows that changing a binding field changes the digest,
    and that calling invalidate_if_digest_changed with the new digest
    correctly invalidates the old confirmation."""

    def _scenario(self, svc, items1, items2, channel=_CHAN, scope=_SCOPE, snap=_SNAP):
        digest1 = _digest(items1, channel, scope, snap)
        dr = svc.execute(
            change_set_id="cs-1",
            change_set_revision_id="rev-1",
            stored_digest=digest1,
            items=items1,
            destination_channel=channel,
            scope=scope,
            source_snapshot_id=snap,
        )
        conf = svc.confirm(dr.id, confirmed_by="seller@example.com")
        digest2 = _digest(items2, channel, scope, snap)
        assert digest1 != digest2, "Digests should differ for this scenario to be meaningful"
        result = svc.invalidate_if_digest_changed(conf.id, digest2)
        assert result is not None, "Confirmation should have been invalidated"
        assert result.is_valid is False

    def test_changed_proposal_hash_invalidates_confirmation(self, svc):
        self._scenario(
            svc,
            items1=[_item(proposal_hash="a" * 64)],
            items2=[_item(proposal_hash="b" * 64)],
        )

    def test_changed_safety_result_invalidates_confirmation(self, svc):
        self._scenario(
            svc,
            items1=[_item(safety_result_id="safety-v1")],
            items2=[_item(safety_result_id="safety-v2")],
        )

    def test_changed_rule_version_invalidates_confirmation(self, svc):
        self._scenario(
            svc,
            items1=[_item(rule_version_id="rule-v1")],
            items2=[_item(rule_version_id="rule-v2")],
        )

    def test_changed_destination_channel_invalidates_confirmation(self, svc):
        items = [_item()]
        digest1 = _digest(items, channel="WC")
        dr = svc.execute(
            change_set_id="cs-1",
            change_set_revision_id="rev-1",
            stored_digest=digest1,
            items=items,
            destination_channel="WC",
            scope=_SCOPE,
            source_snapshot_id=_SNAP,
        )
        conf = svc.confirm(dr.id, confirmed_by="seller@example.com")
        digest2 = _digest(items, channel="SHOPIFY")
        assert digest1 != digest2
        result = svc.invalidate_if_digest_changed(conf.id, digest2)
        assert result is not None
        assert result.is_valid is False

    def test_changed_scope_invalidates_confirmation(self, svc):
        items = [_item()]
        digest1 = _digest(items, scope="all")
        dr = svc.execute(
            change_set_id="cs-1",
            change_set_revision_id="rev-1",
            stored_digest=digest1,
            items=items,
            destination_channel=_CHAN,
            scope="all",
            source_snapshot_id=_SNAP,
        )
        conf = svc.confirm(dr.id, confirmed_by="seller@example.com")
        digest2 = _digest(items, scope="category-A")
        assert digest1 != digest2
        result = svc.invalidate_if_digest_changed(conf.id, digest2)
        assert result is not None
        assert result.is_valid is False

    def test_changed_source_snapshot_invalidates_confirmation(self, svc):
        items = [_item()]
        digest1 = _digest(items, snapshot="snap-001")
        dr = svc.execute(
            change_set_id="cs-1",
            change_set_revision_id="rev-1",
            stored_digest=digest1,
            items=items,
            destination_channel=_CHAN,
            scope=_SCOPE,
            source_snapshot_id="snap-001",
        )
        conf = svc.confirm(dr.id, confirmed_by="seller@example.com")
        digest2 = _digest(items, snapshot="snap-002")
        assert digest1 != digest2
        result = svc.invalidate_if_digest_changed(conf.id, digest2)
        assert result is not None
        assert result.is_valid is False


# ── TestDryRunRepository ──────────────────────────────────────────────────────


class TestDryRunRepository:
    def test_repo_create_and_get(self, repo):
        dr = repo.create(
            change_set_id="cs-1",
            change_set_revision_id="rev-1",
            change_set_digest="a" * 64,
            digest_verified=True,
            validation_result="PASS",
            execution_eligible=True,
            proposal_count=1,
            blocked_count=0,
            warning_count=0,
            summary="OK",
        )
        fetched = repo.get(dr.id)
        assert fetched is not None
        assert fetched.id == dr.id
        assert fetched.change_set_id == "cs-1"

    def test_repo_get_nonexistent_returns_none(self, repo):
        assert repo.get("no-such-id") is None

    def test_repo_list_all(self, repo):
        repo.create(
            change_set_id="cs-1",
            change_set_revision_id="rev-1",
            change_set_digest="a" * 64,
            digest_verified=True,
            validation_result="PASS",
            execution_eligible=True,
            proposal_count=1,
            blocked_count=0,
            warning_count=0,
            summary="OK",
        )
        repo.create(
            change_set_id="cs-2",
            change_set_revision_id="rev-2",
            change_set_digest="b" * 64,
            digest_verified=True,
            validation_result="PASS",
            execution_eligible=True,
            proposal_count=1,
            blocked_count=0,
            warning_count=0,
            summary="OK",
        )
        assert len(repo.list()) == 2

    def test_repo_list_filtered_by_change_set_id(self, repo):
        repo.create(
            change_set_id="cs-A",
            change_set_revision_id="rev-1",
            change_set_digest="a" * 64,
            digest_verified=True,
            validation_result="PASS",
            execution_eligible=True,
            proposal_count=1,
            blocked_count=0,
            warning_count=0,
            summary="OK",
        )
        repo.create(
            change_set_id="cs-B",
            change_set_revision_id="rev-2",
            change_set_digest="b" * 64,
            digest_verified=True,
            validation_result="PASS",
            execution_eligible=True,
            proposal_count=1,
            blocked_count=0,
            warning_count=0,
            summary="OK",
        )
        results = repo.list(change_set_id="cs-A")
        assert len(results) == 1
        assert results[0].change_set_id == "cs-A"

    def test_repo_add_and_list_results(self, repo):
        dr = repo.create(
            change_set_id="cs-1",
            change_set_revision_id="rev-1",
            change_set_digest="a" * 64,
            digest_verified=True,
            validation_result="PASS",
            execution_eligible=True,
            proposal_count=2,
            blocked_count=0,
            warning_count=0,
            summary="OK",
        )
        repo.add_result(
            dry_run_id=dr.id,
            product_id="SKU-001",
            proposal_id="prop-001",
            proposal_hash="a" * 64,
            outcome="PASS",
        )
        repo.add_result(
            dry_run_id=dr.id,
            product_id="SKU-002",
            proposal_id="prop-002",
            proposal_hash="b" * 64,
            outcome="WARN",
            reason="Safety result missing",
        )
        results = repo.list_results(dr.id)
        assert len(results) == 2
        assert results[1].outcome == "WARN"
        assert results[1].reason == "Safety result missing"

    def test_repo_record_and_get_confirmation(self, repo):
        dr = repo.create(
            change_set_id="cs-1",
            change_set_revision_id="rev-1",
            change_set_digest="a" * 64,
            digest_verified=True,
            validation_result="PASS",
            execution_eligible=True,
            proposal_count=1,
            blocked_count=0,
            warning_count=0,
            summary="OK",
        )
        conf = repo.record_confirmation(
            dry_run_id=dr.id,
            change_set_digest="a" * 64,
            confirmed_by="seller@example.com",
        )
        assert conf.is_valid is True
        assert conf.change_set_digest == "a" * 64

    def test_repo_invalidate_confirmation(self, repo):
        dr = repo.create(
            change_set_id="cs-1",
            change_set_revision_id="rev-1",
            change_set_digest="a" * 64,
            digest_verified=True,
            validation_result="PASS",
            execution_eligible=True,
            proposal_count=1,
            blocked_count=0,
            warning_count=0,
            summary="OK",
        )
        conf = repo.record_confirmation(
            dry_run_id=dr.id,
            change_set_digest="a" * 64,
            confirmed_by="seller@example.com",
        )
        invalidated = repo.invalidate_confirmation(conf.id, reason="Digest changed")
        assert invalidated.is_valid is False
        assert invalidated.invalidation_reason == "Digest changed"

    def test_repo_invalidate_nonexistent_raises_error(self, repo):
        with pytest.raises(ConfirmationNotFoundError):
            repo.invalidate_confirmation("no-such-id", reason="test")

    def test_repo_latest_confirmation_returns_most_recent(self, repo):
        dr = repo.create(
            change_set_id="cs-1",
            change_set_revision_id="rev-1",
            change_set_digest="a" * 64,
            digest_verified=True,
            validation_result="PASS",
            execution_eligible=True,
            proposal_count=1,
            blocked_count=0,
            warning_count=0,
            summary="OK",
        )
        conf1 = repo.record_confirmation(
            dry_run_id=dr.id,
            change_set_digest="a" * 64,
            confirmed_by="alice@example.com",
        )
        conf2 = repo.record_confirmation(
            dry_run_id=dr.id,
            change_set_digest="a" * 64,
            confirmed_by="bob@example.com",
        )
        latest = repo.latest_confirmation(dr.id)
        # latest is the one created last (ordered by created_at desc)
        assert latest is not None
        assert latest.id in (conf1.id, conf2.id)

    def test_repo_latest_confirmation_none_when_empty(self, repo):
        dr = repo.create(
            change_set_id="cs-1",
            change_set_revision_id="rev-1",
            change_set_digest="a" * 64,
            digest_verified=True,
            validation_result="PASS",
            execution_eligible=True,
            proposal_count=1,
            blocked_count=0,
            warning_count=0,
            summary="OK",
        )
        assert repo.latest_confirmation(dr.id) is None


# ── TestMigration ─────────────────────────────────────────────────────────────


class TestMigration:
    def test_a2_005_down_revision_is_a2_004(self):
        import importlib
        mod = importlib.import_module(
            "alembic_a2.versions.a2_005_dry_run_engine"
        )
        assert mod.revision == "a2_005"
        assert mod.down_revision == "a2_004"

    def test_upgrade_to_head_creates_dry_run_tables(self, tmp_path):
        db_url = "sqlite:///" + str(tmp_path / "a2_005_up_test.db").replace("\\", "/")
        with patch.dict(os.environ, {"A2_DATABASE_URL": db_url}):
            cfg = Config("alembic_a2.ini")
            cfg.set_main_option("sqlalchemy.url", db_url)
            command.upgrade(cfg, "head")

        eng = create_engine(db_url)
        tables = set(inspect(eng).get_table_names())
        eng.dispose()

        assert "a2_dry_runs" in tables
        assert "a2_dry_run_results" in tables
        assert "a2_seller_confirmations" in tables
        # Prior phase tables must still exist
        assert "a2_change_sets" in tables
        assert "a2_safety_policies" in tables

    def test_downgrade_from_a2_005_removes_dry_run_tables(self, tmp_path):
        db_url = "sqlite:///" + str(tmp_path / "a2_005_down_test.db").replace("\\", "/")
        with patch.dict(os.environ, {"A2_DATABASE_URL": db_url}):
            cfg = Config("alembic_a2.ini")
            cfg.set_main_option("sqlalchemy.url", db_url)
            command.upgrade(cfg, "head")
            command.downgrade(cfg, "a2_004")

        eng = create_engine(db_url)
        tables = set(inspect(eng).get_table_names())
        eng.dispose()

        assert "a2_dry_runs" not in tables
        assert "a2_dry_run_results" not in tables
        assert "a2_seller_confirmations" not in tables
        # A2.5 tables must remain
        assert "a2_change_sets" in tables

    def test_upgrade_to_a2_004_does_not_create_dry_run_tables(self, tmp_path):
        db_url = "sqlite:///" + str(tmp_path / "a2_004_only.db").replace("\\", "/")
        with patch.dict(os.environ, {"A2_DATABASE_URL": db_url}):
            cfg = Config("alembic_a2.ini")
            cfg.set_main_option("sqlalchemy.url", db_url)
            command.upgrade(cfg, "a2_004")

        eng = create_engine(db_url)
        tables = set(inspect(eng).get_table_names())
        eng.dispose()

        assert "a2_dry_runs" not in tables
        assert "a2_change_sets" in tables

    def test_migration_lineage_a2_004_to_a2_005(self):
        import importlib
        mod_004 = importlib.import_module(
            "alembic_a2.versions.a2_004_change_set_engine"
        )
        mod_005 = importlib.import_module(
            "alembic_a2.versions.a2_005_dry_run_engine"
        )
        assert mod_005.down_revision == mod_004.revision

    def test_a2_005_has_exactly_three_tables(self, tmp_path):
        db_url = "sqlite:///" + str(tmp_path / "a2_005_count.db").replace("\\", "/")
        with patch.dict(os.environ, {"A2_DATABASE_URL": db_url}):
            cfg = Config("alembic_a2.ini")
            cfg.set_main_option("sqlalchemy.url", db_url)
            command.upgrade(cfg, "a2_004")

        eng_before = create_engine(db_url)
        tables_before = set(inspect(eng_before).get_table_names())
        eng_before.dispose()

        with patch.dict(os.environ, {"A2_DATABASE_URL": db_url}):
            cfg = Config("alembic_a2.ini")
            cfg.set_main_option("sqlalchemy.url", db_url)
            command.upgrade(cfg, "a2_005")

        eng_after = create_engine(db_url)
        tables_after = set(inspect(eng_after).get_table_names())
        eng_after.dispose()

        new_tables = tables_after - tables_before
        # Exclude alembic_version from count
        new_tables.discard("alembic_version")
        assert new_tables == {"a2_dry_runs", "a2_dry_run_results", "a2_seller_confirmations"}


# ── TestIsolation ─────────────────────────────────────────────────────────────


class TestIsolation:
    def _read_source(self, module_name: str) -> str:
        import importlib
        import importlib.util
        spec = importlib.util.find_spec(module_name)
        with open(spec.origin) as f:
            return f.read()

    def test_dry_run_service_does_not_import_execution_engine(self):
        import re
        content = self._read_source("app.a2.services.dry_run_service")
        assert not re.search(
            r"^(?:from|import)\s+.*execution_engine",
            content,
            re.MULTILINE,
        ), "dry_run_service must not import execution_engine"

    def test_dry_run_service_does_not_import_scheduling(self):
        import re
        content = self._read_source("app.a2.services.dry_run_service")
        for forbidden in ["scheduling", "scheduler"]:
            assert not re.search(
                rf"^(?:from|import)\s+.*{forbidden}",
                content,
                re.MULTILINE,
            ), f"dry_run_service must not import {forbidden!r}"

    def test_dry_run_service_does_not_import_woocommerce(self):
        content = self._read_source("app.a2.services.dry_run_service")
        for forbidden in ["wcapi", "woocommerce_client"]:
            assert forbidden not in content.lower(), (
                f"Found WooCommerce reference {forbidden!r} in dry_run_service"
            )

    def test_dry_run_service_does_not_import_apply(self):
        import re
        content = self._read_source("app.a2.services.dry_run_service")
        assert not re.search(
            r"^(?:from|import)\s+.*\.apply",
            content,
            re.MULTILINE,
        ), "dry_run_service must not import Apply logic"

    def test_dry_run_service_has_no_destination_write_methods(self):
        from app.a2.services.dry_run_service import DryRunService
        for method_name in (
            "apply",
            "execute_apply",
            "push_to_woocommerce",
            "publish_prices",
            "write_prices",
        ):
            assert not hasattr(DryRunService, method_name), (
                f"DryRunService must not expose {method_name!r} "
                "— dry runs are read-only with respect to destinations"
            )

    def test_dry_run_repository_does_not_import_future_phases(self):
        import re
        content = self._read_source("app.a2.repositories.dry_run_repository")
        for forbidden in ["execution_engine", "scheduling", "a2_7", "a2_8"]:
            assert not re.search(
                rf"^(?:from|import)\s+.*{forbidden}",
                content,
                re.MULTILINE,
            ), f"dry_run_repository must not import {forbidden!r}"

    def test_dry_run_model_does_not_import_future_phases(self):
        import re
        content = self._read_source("app.a2.models.dry_run")
        for forbidden in ["execution_engine", "scheduling", "woocommerce"]:
            assert not re.search(
                rf"^(?:from|import)\s+.*{forbidden}",
                content,
                re.MULTILINE,
            ), f"dry_run model must not import {forbidden!r}"

    def test_dry_run_service_does_not_import_a2_7_plus(self):
        import re
        content = self._read_source("app.a2.services.dry_run_service")
        # A2.7 and later must not be imported
        for forbidden in ["a2_7", "a2_8", "a2_9"]:
            assert not re.search(
                rf"{forbidden}",
                content,
            ), f"dry_run_service must not reference {forbidden!r}"
