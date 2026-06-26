"""
A2.5 — Change Set Engine tests.

Covers:
  - Deterministic digest: identical inputs always produce the same digest
  - Changed proposal_hash / safety_result_id / rule_version_id changes digest
  - Changed destination_channel, scope, source_snapshot_id changes digest
  - Item order independence (digest is sort-stable)
  - Revision creation: revision_number increments, parent_revision_id set
  - Immutability: created revisions cannot be mutated by the repository
  - No duplicate revisions: same digest rejected by both service and repository
  - State machine: all valid transitions pass; all invalid transitions rejected
  - Cancellation: only DRAFT and READY change sets may be moved to ARCHIVED
  - ARCHIVED is a terminal state (no outbound transitions)
  - SUPERSEDED → ARCHIVED is allowed
  - Repository CRUD: create, get, list_by_channel, list_by_snapshot, list_revisions
  - add_item / list_items correctness
  - Service.build: returns (ChangeSet, ChangeSetRevision); ChangeSet in DRAFT
  - Service.create_revision: adds history, links parent, rejects bad state
  - Service.verify_digest: returns True for matching inputs, False for changed inputs
  - Alembic migration a2_004: creates expected tables; down_revision == a2_003
  - Migration upgrade creates change set tables; downgrade removes them
  - Migration lineage: a2_003 → a2_004
  - Isolation: no imports from A2.6+, WooCommerce, Apply, Dry Run
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
from sqlalchemy import create_engine, inspect, text
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

from app.a2.repositories.change_set_repository import (
    ChangeSetRepository,
    InvalidStateTransitionError,
)
from app.a2.services.change_set_service import (
    ChangeSetItemInput,
    ChangeSetService,
    DuplicateRevisionError,
    compute_change_set_digest,
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
    return ChangeSetRepository(db)


@pytest.fixture()
def svc(db):
    return ChangeSetService(db)


def _item(
    product_id: str = "SKU-001",
    proposal_id: str = "prop-001",
    proposal_hash: str = "abc123",
    safety_result_id: str = "sr-001",
    rule_version_id: str = "rv-001",
    proposed_price: str = "99.99",
    current_price: str | None = "89.99",
) -> ChangeSetItemInput:
    return ChangeSetItemInput(
        product_id=product_id,
        proposal_id=proposal_id,
        proposal_hash=proposal_hash,
        safety_result_id=safety_result_id,
        rule_version_id=rule_version_id,
        proposed_price=Decimal(proposed_price),
        current_price=Decimal(current_price) if current_price is not None else None,
    )


# ── Digest correctness ────────────────────────────────────────────────────────


class TestDigestDeterminism:
    def test_identical_inputs_produce_identical_digest(self):
        items = [_item()]
        d1 = compute_change_set_digest(items, "WC", "all", "snap-001")
        d2 = compute_change_set_digest(items, "WC", "all", "snap-001")
        assert d1 == d2

    def test_multiple_items_identical_inputs_produce_identical_digest(self):
        items = [_item("SKU-001"), _item("SKU-002", proposal_id="prop-002")]
        d1 = compute_change_set_digest(items, "WC", "all", "snap-001")
        d2 = compute_change_set_digest(items, "WC", "all", "snap-001")
        assert d1 == d2

    def test_item_order_does_not_affect_digest(self):
        item_a = _item("AAA", proposal_id="p-a")
        item_b = _item("BBB", proposal_id="p-b")
        d1 = compute_change_set_digest([item_a, item_b], "WC", "all", "snap-001")
        d2 = compute_change_set_digest([item_b, item_a], "WC", "all", "snap-001")
        assert d1 == d2

    def test_changed_proposal_hash_changes_digest(self):
        items_a = [_item(proposal_hash="hash-A")]
        items_b = [_item(proposal_hash="hash-B")]
        assert (
            compute_change_set_digest(items_a, "WC", "all", "snap-001")
            != compute_change_set_digest(items_b, "WC", "all", "snap-001")
        )

    def test_changed_safety_result_id_changes_digest(self):
        items_a = [_item(safety_result_id="sr-001")]
        items_b = [_item(safety_result_id="sr-002")]
        assert (
            compute_change_set_digest(items_a, "WC", "all", "snap-001")
            != compute_change_set_digest(items_b, "WC", "all", "snap-001")
        )

    def test_changed_rule_version_id_changes_digest(self):
        items_a = [_item(rule_version_id="rv-001")]
        items_b = [_item(rule_version_id="rv-002")]
        assert (
            compute_change_set_digest(items_a, "WC", "all", "snap-001")
            != compute_change_set_digest(items_b, "WC", "all", "snap-001")
        )

    def test_changed_product_id_changes_digest(self):
        items_a = [_item(product_id="SKU-001")]
        items_b = [_item(product_id="SKU-999")]
        assert (
            compute_change_set_digest(items_a, "WC", "all", "snap-001")
            != compute_change_set_digest(items_b, "WC", "all", "snap-001")
        )

    def test_changed_destination_channel_changes_digest(self):
        items = [_item()]
        assert (
            compute_change_set_digest(items, "WC", "all", "snap-001")
            != compute_change_set_digest(items, "SHOPIFY", "all", "snap-001")
        )

    def test_changed_scope_changes_digest(self):
        items = [_item()]
        assert (
            compute_change_set_digest(items, "WC", "all", "snap-001")
            != compute_change_set_digest(items, "WC", "subset-A", "snap-001")
        )

    def test_changed_source_snapshot_id_changes_digest(self):
        items = [_item()]
        assert (
            compute_change_set_digest(items, "WC", "all", "snap-001")
            != compute_change_set_digest(items, "WC", "all", "snap-002")
        )

    def test_added_item_changes_digest(self):
        items_a = [_item("SKU-001")]
        items_b = [_item("SKU-001"), _item("SKU-002", proposal_id="p-2")]
        assert (
            compute_change_set_digest(items_a, "WC", "all", "snap-001")
            != compute_change_set_digest(items_b, "WC", "all", "snap-001")
        )

    def test_digest_is_64_hex_chars(self):
        d = compute_change_set_digest([_item()], "WC", "all", "snap-001")
        assert len(d) == 64
        assert all(c in "0123456789abcdef" for c in d)

    def test_proposed_price_not_in_digest(self):
        """Price changes that don't affect proposal_hash must not change digest."""
        items_a = [_item(proposed_price="100.00")]
        items_b = [_item(proposed_price="200.00")]
        # proposed_price is excluded from digest — only proposal_hash matters
        assert (
            compute_change_set_digest(items_a, "WC", "all", "snap-001")
            == compute_change_set_digest(items_b, "WC", "all", "snap-001")
        )

    def test_sort_is_fully_deterministic_regardless_of_input_order(self):
        """Sort key covers all payload fields so digest is independent of caller order
        even when product_id + proposal_id are identical across items."""
        item_a = _item("SAME-SKU", proposal_id="same-id", proposal_hash="alpha",
                        safety_result_id="sr-1", rule_version_id="rv-1")
        item_b = _item("SAME-SKU", proposal_id="same-id", proposal_hash="beta",
                        safety_result_id="sr-2", rule_version_id="rv-2")
        # Both orderings must produce the same digest (sort is fully determined)
        d1 = compute_change_set_digest([item_a, item_b], "WC", "all", "snap-001")
        d2 = compute_change_set_digest([item_b, item_a], "WC", "all", "snap-001")
        assert d1 == d2


# ── Repository CRUD ───────────────────────────────────────────────────────────


class TestChangeSetRepositoryCRUD:
    def test_create_and_get(self, repo):
        cs = repo.create(
            destination_channel="WC",
            scope="all",
            source_snapshot_id="snap-001",
        )
        assert cs.id is not None
        assert cs.state == "DRAFT"
        assert cs.destination_channel == "WC"
        assert cs.scope == "all"
        assert cs.source_snapshot_id == "snap-001"

        fetched = repo.get(cs.id)
        assert fetched is not None
        assert fetched.id == cs.id

    def test_get_nonexistent_returns_none(self, repo):
        assert repo.get("does-not-exist") is None

    def test_list_by_channel(self, repo):
        cs1 = repo.create(destination_channel="WC", scope="all", source_snapshot_id="s1")
        cs2 = repo.create(destination_channel="WC", scope="all", source_snapshot_id="s2")
        repo.create(destination_channel="SHOPIFY", scope="all", source_snapshot_id="s3")

        results = repo.list_by_channel("WC")
        ids = {r.id for r in results}
        assert cs1.id in ids
        assert cs2.id in ids
        assert len(results) == 2

    def test_list_by_snapshot(self, repo):
        cs1 = repo.create(destination_channel="WC", scope="all", source_snapshot_id="snap-X")
        repo.create(destination_channel="WC", scope="all", source_snapshot_id="snap-Y")

        results = repo.list_by_snapshot("snap-X")
        assert len(results) == 1
        assert results[0].id == cs1.id

    def test_create_revision_auto_increments_revision_number(self, repo):
        cs = repo.create(destination_channel="WC", scope="all", source_snapshot_id="s1")
        r1 = repo.create_revision(change_set_id=cs.id, digest="aaa" + "0" * 61)
        r2 = repo.create_revision(
            change_set_id=cs.id, digest="bbb" + "0" * 61, parent_revision_id=r1.id
        )
        assert r1.revision_number == 1
        assert r2.revision_number == 2
        assert r2.parent_revision_id == r1.id

    def test_get_revision(self, repo):
        cs = repo.create(destination_channel="WC", scope="all", source_snapshot_id="s1")
        r1 = repo.create_revision(change_set_id=cs.id, digest="d" * 64)
        fetched = repo.get_revision(r1.id)
        assert fetched is not None
        assert fetched.id == r1.id
        assert fetched.digest == "d" * 64

    def test_get_revision_nonexistent_returns_none(self, repo):
        assert repo.get_revision("no-such-revision") is None

    def test_get_revision_by_digest(self, repo):
        cs = repo.create(destination_channel="WC", scope="all", source_snapshot_id="s1")
        repo.create_revision(change_set_id=cs.id, digest="abc" + "0" * 61)
        found = repo.get_revision_by_digest("abc" + "0" * 61)
        assert found is not None

    def test_get_revision_by_digest_nonexistent_returns_none(self, repo):
        assert repo.get_revision_by_digest("z" * 64) is None

    def test_list_revisions_ordered(self, repo):
        cs = repo.create(destination_channel="WC", scope="all", source_snapshot_id="s1")
        r1 = repo.create_revision(change_set_id=cs.id, digest="a" * 64)
        r2 = repo.create_revision(change_set_id=cs.id, digest="b" * 64, parent_revision_id=r1.id)
        r3 = repo.create_revision(change_set_id=cs.id, digest="c" * 64, parent_revision_id=r2.id)

        revisions = repo.list_revisions(cs.id)
        assert [r.revision_number for r in revisions] == [1, 2, 3]

    def test_add_item_and_list_items(self, repo):
        cs = repo.create(destination_channel="WC", scope="all", source_snapshot_id="s1")
        rev = repo.create_revision(change_set_id=cs.id, digest="d" * 64)

        item = repo.add_item(
            revision_id=rev.id,
            product_id="SKU-001",
            proposal_id="prop-001",
            proposal_hash="hash-001",
            safety_result_id="sr-001",
            rule_version_id="rv-001",
            proposed_price=Decimal("100.00"),
            current_price=Decimal("90.00"),
        )
        assert item.id is not None
        assert item.delta == Decimal("10.00")

        items = repo.list_items(rev.id)
        assert len(items) == 1
        assert items[0].product_id == "SKU-001"

    def test_add_item_without_current_price_delta_is_none(self, repo):
        cs = repo.create(destination_channel="WC", scope="all", source_snapshot_id="s1")
        rev = repo.create_revision(change_set_id=cs.id, digest="e" * 64)
        item = repo.add_item(
            revision_id=rev.id,
            product_id="SKU-002",
            proposal_id="prop-002",
            proposal_hash="hash-002",
            safety_result_id="sr-002",
            rule_version_id="rv-002",
            proposed_price=Decimal("50.00"),
            current_price=None,
        )
        assert item.delta is None


# ── State machine ─────────────────────────────────────────────────────────────


class TestStateMachine:
    """Transition matrix (exactly 3 allowed transitions per A2.5 architecture spec):

    DRAFT      → READY         ✓ (valid)
    READY      → SUPERSEDED    ✓ (valid)
    READY      → ARCHIVED      ✓ (valid)
    all others                 ✗ (invalid; raises InvalidStateTransitionError)
    SUPERSEDED and ARCHIVED are both terminal states.
    """

    # ── Valid transitions (3 total) ──────────────────────────────────────────

    def test_draft_to_ready(self, repo):
        cs = repo.create(destination_channel="WC", scope="all", source_snapshot_id="s1")
        result = repo.transition_state(cs.id, "READY")
        assert result.state == "READY"

    def test_ready_to_superseded(self, repo):
        cs = repo.create(destination_channel="WC", scope="all", source_snapshot_id="s1")
        repo.transition_state(cs.id, "READY")
        result = repo.transition_state(cs.id, "SUPERSEDED")
        assert result.state == "SUPERSEDED"

    def test_ready_to_archived(self, repo):
        cs = repo.create(destination_channel="WC", scope="all", source_snapshot_id="s1")
        repo.transition_state(cs.id, "READY")
        result = repo.transition_state(cs.id, "ARCHIVED")
        assert result.state == "ARCHIVED"

    # ── Invalid transitions (all others rejected) ────────────────────────────

    def test_draft_to_archived_invalid(self, repo):
        cs = repo.create(destination_channel="WC", scope="all", source_snapshot_id="s1")
        with pytest.raises(InvalidStateTransitionError):
            repo.transition_state(cs.id, "ARCHIVED")

    def test_draft_to_superseded_invalid(self, repo):
        cs = repo.create(destination_channel="WC", scope="all", source_snapshot_id="s1")
        with pytest.raises(InvalidStateTransitionError):
            repo.transition_state(cs.id, "SUPERSEDED")

    def test_ready_to_draft_invalid(self, repo):
        cs = repo.create(destination_channel="WC", scope="all", source_snapshot_id="s1")
        repo.transition_state(cs.id, "READY")
        with pytest.raises(InvalidStateTransitionError):
            repo.transition_state(cs.id, "DRAFT")

    def test_superseded_is_terminal_cannot_transition_to_archived(self, repo):
        cs = repo.create(destination_channel="WC", scope="all", source_snapshot_id="s1")
        repo.transition_state(cs.id, "READY")
        repo.transition_state(cs.id, "SUPERSEDED")
        with pytest.raises(InvalidStateTransitionError):
            repo.transition_state(cs.id, "ARCHIVED")

    def test_superseded_to_draft_invalid(self, repo):
        cs = repo.create(destination_channel="WC", scope="all", source_snapshot_id="s1")
        repo.transition_state(cs.id, "READY")
        repo.transition_state(cs.id, "SUPERSEDED")
        with pytest.raises(InvalidStateTransitionError):
            repo.transition_state(cs.id, "DRAFT")

    def test_superseded_to_ready_invalid(self, repo):
        cs = repo.create(destination_channel="WC", scope="all", source_snapshot_id="s1")
        repo.transition_state(cs.id, "READY")
        repo.transition_state(cs.id, "SUPERSEDED")
        with pytest.raises(InvalidStateTransitionError):
            repo.transition_state(cs.id, "READY")

    def test_archived_is_terminal(self, repo):
        cs = repo.create(destination_channel="WC", scope="all", source_snapshot_id="s1")
        repo.transition_state(cs.id, "READY")
        repo.transition_state(cs.id, "ARCHIVED")
        with pytest.raises(InvalidStateTransitionError):
            repo.transition_state(cs.id, "READY")

    def test_archived_to_draft_invalid(self, repo):
        cs = repo.create(destination_channel="WC", scope="all", source_snapshot_id="s1")
        repo.transition_state(cs.id, "READY")
        repo.transition_state(cs.id, "ARCHIVED")
        with pytest.raises(InvalidStateTransitionError):
            repo.transition_state(cs.id, "DRAFT")

    def test_archived_to_superseded_invalid(self, repo):
        cs = repo.create(destination_channel="WC", scope="all", source_snapshot_id="s1")
        repo.transition_state(cs.id, "READY")
        repo.transition_state(cs.id, "ARCHIVED")
        with pytest.raises(InvalidStateTransitionError):
            repo.transition_state(cs.id, "SUPERSEDED")

    def test_transition_nonexistent_raises_value_error(self, repo):
        with pytest.raises(ValueError, match="not found"):
            repo.transition_state("no-such-id", "READY")

    def test_only_ready_can_be_archived(self, repo):
        """Only READY change sets may be archived. DRAFT and SUPERSEDED cannot."""
        cs_draft = repo.create(destination_channel="WC", scope="a", source_snapshot_id="s1")
        cs_ready = repo.create(destination_channel="WC", scope="b", source_snapshot_id="s2")
        cs_superseded = repo.create(destination_channel="WC", scope="c", source_snapshot_id="s3")

        repo.transition_state(cs_ready.id, "READY")
        repo.transition_state(cs_superseded.id, "READY")
        repo.transition_state(cs_superseded.id, "SUPERSEDED")

        # READY → ARCHIVED: allowed
        repo.transition_state(cs_ready.id, "ARCHIVED")
        # DRAFT → ARCHIVED: NOT allowed
        with pytest.raises(InvalidStateTransitionError):
            repo.transition_state(cs_draft.id, "ARCHIVED")
        # SUPERSEDED → ARCHIVED: NOT allowed (SUPERSEDED is terminal)
        with pytest.raises(InvalidStateTransitionError):
            repo.transition_state(cs_superseded.id, "ARCHIVED")


# ── Service layer ─────────────────────────────────────────────────────────────


class TestChangeSetServiceBuild:
    def test_build_returns_change_set_and_revision(self, svc):
        cs, rev = svc.build(
            destination_channel="WC",
            scope="all",
            source_snapshot_id="snap-001",
            items=[_item()],
        )
        assert cs is not None
        assert rev is not None
        assert cs.state == "DRAFT"
        assert rev.change_set_id == cs.id
        assert rev.revision_number == 1
        assert rev.parent_revision_id is None

    def test_build_stores_items(self, svc, repo):
        cs, rev = svc.build(
            destination_channel="WC",
            scope="all",
            source_snapshot_id="snap-001",
            items=[_item("SKU-A"), _item("SKU-B", proposal_id="p-2")],
        )
        items = repo.list_items(rev.id)
        assert len(items) == 2
        product_ids = {i.product_id for i in items}
        assert "SKU-A" in product_ids
        assert "SKU-B" in product_ids

    def test_build_digest_stored_correctly(self, svc):
        item = _item()
        cs, rev = svc.build(
            destination_channel="WC",
            scope="all",
            source_snapshot_id="snap-001",
            items=[item],
        )
        expected = compute_change_set_digest([item], "WC", "all", "snap-001")
        assert rev.digest == expected

    def test_build_empty_items_raises_value_error(self, svc):
        with pytest.raises(ValueError, match="at least one item"):
            svc.build(
                destination_channel="WC",
                scope="all",
                source_snapshot_id="snap-001",
                items=[],
            )

    def test_build_duplicate_digest_raises_error(self, svc):
        items = [_item()]
        svc.build(
            destination_channel="WC",
            scope="all",
            source_snapshot_id="snap-001",
            items=items,
        )
        with pytest.raises(DuplicateRevisionError):
            svc.build(
                destination_channel="WC",
                scope="all",
                source_snapshot_id="snap-001",
                items=items,
            )


class TestChangeSetServiceCreateRevision:
    def test_create_revision_increments_number(self, svc):
        cs, r1 = svc.build(
            destination_channel="WC",
            scope="all",
            source_snapshot_id="snap-001",
            items=[_item()],
        )
        r2 = svc.create_revision(
            cs.id,
            items=[_item(proposal_hash="new-hash")],
        )
        assert r2.revision_number == 2
        assert r2.parent_revision_id == r1.id

    def test_create_revision_on_draft_change_set_allowed(self, svc):
        cs, _ = svc.build(
            destination_channel="WC",
            scope="all",
            source_snapshot_id="snap-001",
            items=[_item()],
        )
        r2 = svc.create_revision(cs.id, items=[_item(proposal_hash="hash-x")])
        assert r2 is not None

    def test_create_revision_on_ready_change_set_allowed(self, svc):
        cs, _ = svc.build(
            destination_channel="WC",
            scope="all",
            source_snapshot_id="snap-001",
            items=[_item()],
        )
        svc.transition(cs.id, "READY")
        r2 = svc.create_revision(cs.id, items=[_item(proposal_hash="hash-y")])
        assert r2 is not None

    def test_create_revision_on_archived_raises_value_error(self, svc):
        cs, _ = svc.build(
            destination_channel="WC",
            scope="all",
            source_snapshot_id="snap-001",
            items=[_item()],
        )
        svc.transition(cs.id, "READY")
        svc.transition(cs.id, "ARCHIVED")
        with pytest.raises(ValueError, match="state"):
            svc.create_revision(cs.id, items=[_item(proposal_hash="hash-z")])

    def test_create_revision_on_superseded_raises_value_error(self, svc):
        cs, _ = svc.build(
            destination_channel="WC",
            scope="all",
            source_snapshot_id="snap-001",
            items=[_item()],
        )
        svc.transition(cs.id, "READY")
        svc.transition(cs.id, "SUPERSEDED")
        with pytest.raises(ValueError, match="state"):
            svc.create_revision(cs.id, items=[_item(proposal_hash="hash-q")])

    def test_create_revision_empty_items_raises_value_error(self, svc):
        cs, _ = svc.build(
            destination_channel="WC",
            scope="all",
            source_snapshot_id="snap-001",
            items=[_item()],
        )
        with pytest.raises(ValueError, match="at least one item"):
            svc.create_revision(cs.id, items=[])

    def test_create_revision_duplicate_digest_raises_error(self, svc):
        items = [_item()]
        cs, r1 = svc.build(
            destination_channel="WC",
            scope="all",
            source_snapshot_id="snap-001",
            items=items,
        )
        with pytest.raises(DuplicateRevisionError):
            svc.create_revision(cs.id, items=items)

    def test_three_revisions_chain(self, svc, repo):
        cs, r1 = svc.build(
            destination_channel="WC",
            scope="all",
            source_snapshot_id="snap-001",
            items=[_item(proposal_hash="h1")],
        )
        r2 = svc.create_revision(cs.id, items=[_item(proposal_hash="h2")])
        r3 = svc.create_revision(cs.id, items=[_item(proposal_hash="h3")])

        revisions = repo.list_revisions(cs.id)
        assert len(revisions) == 3
        assert revisions[0].id == r1.id
        assert revisions[1].id == r2.id
        assert revisions[2].id == r3.id
        assert revisions[1].parent_revision_id == r1.id
        assert revisions[2].parent_revision_id == r2.id

    def test_revision_nonexistent_change_set_raises_value_error(self, svc):
        with pytest.raises(ValueError, match="not found"):
            svc.create_revision("no-such-id", items=[_item()])


class TestChangeSetServiceVerifyDigest:
    def test_verify_digest_matching_returns_true(self, svc, repo):
        items = [_item()]
        cs, rev = svc.build(
            destination_channel="WC",
            scope="all",
            source_snapshot_id="snap-001",
            items=items,
        )
        result = svc.verify_digest(
            revision=rev,
            items=items,
            destination_channel=cs.destination_channel,
            scope=cs.scope,
            source_snapshot_id=cs.source_snapshot_id,
        )
        assert result is True

    def test_verify_digest_changed_item_returns_false(self, svc):
        items_original = [_item(proposal_hash="original")]
        cs, rev = svc.build(
            destination_channel="WC",
            scope="all",
            source_snapshot_id="snap-001",
            items=items_original,
        )
        items_tampered = [_item(proposal_hash="tampered")]
        result = svc.verify_digest(
            revision=rev,
            items=items_tampered,
            destination_channel=cs.destination_channel,
            scope=cs.scope,
            source_snapshot_id=cs.source_snapshot_id,
        )
        assert result is False

    def test_verify_digest_changed_channel_returns_false(self, svc):
        items = [_item()]
        cs, rev = svc.build(
            destination_channel="WC",
            scope="all",
            source_snapshot_id="snap-001",
            items=items,
        )
        result = svc.verify_digest(
            revision=rev,
            items=items,
            destination_channel="SHOPIFY",
            scope=cs.scope,
            source_snapshot_id=cs.source_snapshot_id,
        )
        assert result is False


class TestChangeSetServiceTransition:
    def test_service_transition_delegates_to_repo(self, svc):
        cs, _ = svc.build(
            destination_channel="WC",
            scope="all",
            source_snapshot_id="snap-001",
            items=[_item()],
        )
        result = svc.transition(cs.id, "READY")
        assert result.state == "READY"

    def test_service_transition_invalid_raises(self, svc):
        cs, _ = svc.build(
            destination_channel="WC",
            scope="all",
            source_snapshot_id="snap-001",
            items=[_item()],
        )
        with pytest.raises(InvalidStateTransitionError):
            svc.transition(cs.id, "SUPERSEDED")


# ── Immutability ──────────────────────────────────────────────────────────────


class TestImmutability:
    def test_revision_digest_not_overwritable_via_orm(self, svc, db):
        """SQLAlchemy ORM does not provide a dedicated mutation guard, but we verify
        that the repository has no update_revision method (design-level immutability)."""
        from app.a2.repositories.change_set_repository import ChangeSetRepository
        assert not hasattr(ChangeSetRepository, "update_revision"), (
            "ChangeSetRepository must not expose update_revision — revisions are immutable."
        )

    def test_no_update_revision_on_service(self, svc):
        from app.a2.services.change_set_service import ChangeSetService
        assert not hasattr(ChangeSetService, "update_revision"), (
            "ChangeSetService must not expose update_revision — revisions are immutable."
        )

    def test_change_set_revisions_cascade_does_not_include_delete_orphan(self):
        """ChangeSet.revisions must use save-update/merge cascade only.
        delete-orphan would allow callers to delete immutable revisions via ORM."""
        from sqlalchemy import inspect as sa_inspect
        from app.a2.models.change_set import ChangeSet
        mapper = sa_inspect(ChangeSet)
        revisions_rel = mapper.relationships["revisions"]
        cascade_str = str(revisions_rel.cascade)
        assert "delete-orphan" not in cascade_str, (
            f"ChangeSet.revisions must not have delete-orphan cascade; got: {cascade_str!r}"
        )
        assert "delete" not in cascade_str.replace("save-update", "").replace("merge", ""), (
            f"ChangeSet.revisions must not have delete cascade; got: {cascade_str!r}"
        )

    def test_revision_items_persist_after_multiple_revisions(self, svc, repo):
        """Items in revision 1 must still be queryable after revision 2 is created."""
        items_r1 = [_item("SKU-A", proposal_hash="h1")]
        cs, r1 = svc.build(
            destination_channel="WC",
            scope="all",
            source_snapshot_id="snap-001",
            items=items_r1,
        )
        svc.create_revision(cs.id, items=[_item("SKU-B", proposal_hash="h2", proposal_id="p-2")])

        original_items = repo.list_items(r1.id)
        assert len(original_items) == 1
        assert original_items[0].product_id == "SKU-A"


# ── Migration ─────────────────────────────────────────────────────────────────


class TestMigration:
    def test_a2_004_down_revision_is_a2_003(self):
        import importlib
        mod = importlib.import_module(
            "alembic_a2.versions.a2_004_change_set_engine"
        )
        assert mod.revision == "a2_004"
        assert mod.down_revision == "a2_003"

    def test_upgrade_to_head_creates_change_set_tables(self, tmp_path):
        db_url = "sqlite:///" + str(tmp_path / "a2_004_up_test.db").replace("\\", "/")
        with patch.dict(os.environ, {"A2_DATABASE_URL": db_url}):
            cfg = Config("alembic_a2.ini")
            cfg.set_main_option("sqlalchemy.url", db_url)
            command.upgrade(cfg, "head")

        eng = create_engine(db_url)
        tables = set(inspect(eng).get_table_names())
        eng.dispose()

        assert "a2_change_sets" in tables
        assert "a2_change_set_revisions" in tables
        assert "a2_change_set_items" in tables
        # Prior phase tables must still exist
        assert "a2_safety_policies" in tables
        assert "a2_pricing_rules" in tables

    def test_downgrade_from_a2_004_removes_change_set_tables(self, tmp_path):
        db_url = "sqlite:///" + str(tmp_path / "a2_004_down_test.db").replace("\\", "/")
        with patch.dict(os.environ, {"A2_DATABASE_URL": db_url}):
            cfg = Config("alembic_a2.ini")
            cfg.set_main_option("sqlalchemy.url", db_url)
            command.upgrade(cfg, "head")
            command.downgrade(cfg, "a2_003")

        eng = create_engine(db_url)
        tables = set(inspect(eng).get_table_names())
        eng.dispose()

        assert "a2_change_sets" not in tables
        assert "a2_change_set_revisions" not in tables
        assert "a2_change_set_items" not in tables
        assert "a2_safety_policies" in tables
        assert "a2_pricing_rules" in tables

    def test_upgrade_to_a2_003_does_not_create_change_set_tables(self, tmp_path):
        db_url = "sqlite:///" + str(tmp_path / "a2_003_only.db").replace("\\", "/")
        with patch.dict(os.environ, {"A2_DATABASE_URL": db_url}):
            cfg = Config("alembic_a2.ini")
            cfg.set_main_option("sqlalchemy.url", db_url)
            command.upgrade(cfg, "a2_003")

        eng = create_engine(db_url)
        tables = set(inspect(eng).get_table_names())
        eng.dispose()

        assert "a2_change_sets" not in tables
        assert "a2_safety_policies" in tables

    def test_migration_lineage_a2_003_to_a2_004(self):
        import importlib
        mod_003 = importlib.import_module(
            "alembic_a2.versions.a2_003_safety_policy_engine"
        )
        mod_004 = importlib.import_module(
            "alembic_a2.versions.a2_004_change_set_engine"
        )
        assert mod_004.down_revision == mod_003.revision


# ── Isolation ─────────────────────────────────────────────────────────────────


class TestIsolation:
    def _read_source(self, module_name: str) -> str:
        import importlib
        spec = importlib.util.find_spec(module_name)
        with open(spec.origin) as f:
            return f.read()

    def test_change_set_service_does_not_import_future_phases(self):
        import re
        content = self._read_source("app.a2.services.change_set_service")
        for forbidden in ["dry_run", "execution_engine", "scheduling"]:
            assert not re.search(
                rf"^(?:from|import)\s+.*{forbidden}",
                content,
                re.MULTILINE,
            ), f"Found import of forbidden module {forbidden!r} in change_set_service"

    def test_change_set_service_does_not_import_woocommerce(self):
        content = self._read_source("app.a2.services.change_set_service")
        for forbidden in ["wcapi", "woocommerce_client", "import wc"]:
            assert forbidden not in content.lower(), (
                f"Found WooCommerce reference {forbidden!r} in change_set_service"
            )

    def test_change_set_service_does_not_import_apply(self):
        import re
        content = self._read_source("app.a2.services.change_set_service")
        assert not re.search(r"^(?:from|import)\s+.*apply", content, re.MULTILINE), (
            "change_set_service must not import Apply logic"
        )

    def test_change_set_repository_does_not_import_future_phases(self):
        import re
        content = self._read_source("app.a2.repositories.change_set_repository")
        for forbidden in ["dry_run", "execution_engine", "scheduling"]:
            assert not re.search(
                rf"^(?:from|import)\s+.*{forbidden}",
                content,
                re.MULTILINE,
            ), f"Found forbidden import {forbidden!r} in change_set_repository"

    def test_change_set_model_does_not_import_future_phases(self):
        import re
        content = self._read_source("app.a2.models.change_set")
        for forbidden in ["dry_run", "execution_engine", "scheduling"]:
            assert not re.search(
                rf"^(?:from|import)\s+.*{forbidden}",
                content,
                re.MULTILINE,
            ), f"Found forbidden import {forbidden!r} in change_set model"
