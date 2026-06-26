"""A2.5 Change Set Service — builds and manages immutable Change Sets.

Computes deterministic SHA-256 digests from proposal bindings, safety bindings,
rule version bindings, and destination metadata. All revisions are immutable;
any change to items or bindings requires a new ChangeSetRevision.

Scope boundary (A2.5 only):
- Does NOT call A2.6 (Dry Run Engine) or any later phase.
- Does NOT call WooCommerce, Apply, Dry Run, or any external system.
- Does NOT execute or apply prices.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from ..models.change_set import ChangeSet, ChangeSetRevision
from ..repositories.change_set_repository import ChangeSetRepository, InvalidStateTransitionError


@dataclass
class ChangeSetItemInput:
    """Input record for one product's proposed change within a Change Set."""

    product_id: str
    proposal_id: str
    proposal_hash: str
    safety_result_id: str
    rule_version_id: str
    proposed_price: Decimal
    current_price: Optional[Decimal] = None


def compute_change_set_digest(
    items: list[ChangeSetItemInput],
    destination_channel: str,
    scope: str,
    source_snapshot_id: str,
) -> str:
    """Compute a deterministic SHA-256 digest for a set of Change Set items.

    The digest covers all items (sorted by product_id then proposal_id for
    stability) and all binding metadata. UUID fields and timestamps are excluded
    so that identical logical inputs always produce identical digests.
    """
    sorted_items = sorted(
        items,
        key=lambda i: (i.product_id, i.proposal_id, i.proposal_hash, i.safety_result_id, i.rule_version_id),
    )
    payload = {
        "destination_channel": destination_channel,
        "scope": scope,
        "source_snapshot_id": source_snapshot_id,
        "items": [
            {
                "product_id": item.product_id,
                "proposal_hash": item.proposal_hash,
                "safety_result_id": item.safety_result_id,
                "rule_version_id": item.rule_version_id,
            }
            for item in sorted_items
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


class DuplicateRevisionError(Exception):
    """Raised when a new revision would produce a digest identical to an existing one."""


class ChangeSetService:
    """Builds and manages Change Sets and their immutable revisions.

    The service enforces:
    - Digest determinism: identical inputs always produce the same digest.
    - Revision immutability: created revisions are never modified.
    - No duplicate revisions: a digest already present is rejected.
    - State machine: transitions are validated before being applied.
    """

    def __init__(self, db: Session) -> None:
        self._db = db
        self._repo = ChangeSetRepository(db)

    def build(
        self,
        *,
        destination_channel: str,
        scope: str,
        source_snapshot_id: str,
        items: list[ChangeSetItemInput],
    ) -> tuple[ChangeSet, ChangeSetRevision]:
        """Create a new ChangeSet in DRAFT state with its first revision.

        Returns (ChangeSet, ChangeSetRevision). The ChangeSet is in DRAFT state;
        call transition(change_set_id, 'READY') to mark it finalized.
        """
        if not items:
            raise ValueError("A Change Set must contain at least one item.")

        digest = compute_change_set_digest(
            items=items,
            destination_channel=destination_channel,
            scope=scope,
            source_snapshot_id=source_snapshot_id,
        )

        existing = self._repo.get_revision_by_digest(digest)
        if existing is not None:
            raise DuplicateRevisionError(
                f"A revision with digest {digest!r} already exists "
                f"(revision_id={existing.id!r}). Identical inputs produce identical digests."
            )

        cs = self._repo.create(
            destination_channel=destination_channel,
            scope=scope,
            source_snapshot_id=source_snapshot_id,
        )
        revision = self._repo.create_revision(
            change_set_id=cs.id,
            digest=digest,
            parent_revision_id=None,
        )
        self._persist_items(revision.id, items)
        return cs, revision

    def create_revision(
        self,
        change_set_id: str,
        items: list[ChangeSetItemInput],
    ) -> ChangeSetRevision:
        """Add a new revision to an existing ChangeSet.

        The ChangeSet must be in DRAFT or READY state. Creates a new revision
        with an incremented revision_number and the previous revision as parent.
        Raises DuplicateRevisionError if the new digest matches any existing revision.
        Raises ValueError if the ChangeSet cannot accept new revisions.
        """
        cs = self._repo.get(change_set_id)
        if cs is None:
            raise ValueError(f"ChangeSet not found: {change_set_id}")
        if cs.state not in ("DRAFT", "READY"):
            raise ValueError(
                f"Cannot add a revision to ChangeSet {change_set_id} in state {cs.state!r}. "
                "Revisions can only be added to DRAFT or READY change sets."
            )
        if not items:
            raise ValueError("A Change Set revision must contain at least one item.")

        digest = compute_change_set_digest(
            items=items,
            destination_channel=cs.destination_channel,
            scope=cs.scope,
            source_snapshot_id=cs.source_snapshot_id,
        )

        existing = self._repo.get_revision_by_digest(digest)
        if existing is not None:
            raise DuplicateRevisionError(
                f"A revision with digest {digest!r} already exists "
                f"(revision_id={existing.id!r}). Identical inputs produce identical digests."
            )

        existing_revisions = self._repo.list_revisions(change_set_id)
        parent_id = existing_revisions[-1].id if existing_revisions else None

        revision = self._repo.create_revision(
            change_set_id=change_set_id,
            digest=digest,
            parent_revision_id=parent_id,
        )
        self._persist_items(revision.id, items)
        return revision

    def transition(self, change_set_id: str, target_state: str) -> ChangeSet:
        """Transition a ChangeSet to a new state via the state machine.

        Valid transitions (exactly three; per A2.5 architecture spec):
          DRAFT  → READY
          READY  → SUPERSEDED
          READY  → ARCHIVED
        SUPERSEDED and ARCHIVED are both terminal states.

        Raises InvalidStateTransitionError for any other transition.
        """
        return self._repo.transition_state(change_set_id, target_state)

    def verify_digest(
        self,
        revision: ChangeSetRevision,
        items: list[ChangeSetItemInput],
        destination_channel: str,
        scope: str,
        source_snapshot_id: str,
    ) -> bool:
        """Return True if recomputing the digest from items matches the stored digest."""
        computed = compute_change_set_digest(
            items=items,
            destination_channel=destination_channel,
            scope=scope,
            source_snapshot_id=source_snapshot_id,
        )
        return computed == revision.digest

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _persist_items(
        self,
        revision_id: str,
        items: list[ChangeSetItemInput],
    ) -> None:
        for item in items:
            self._repo.add_item(
                revision_id=revision_id,
                product_id=item.product_id,
                proposal_id=item.proposal_id,
                proposal_hash=item.proposal_hash,
                safety_result_id=item.safety_result_id,
                rule_version_id=item.rule_version_id,
                proposed_price=item.proposed_price,
                current_price=item.current_price,
            )
