"""A2.5 Change Set Repository — persistence for ChangeSet, ChangeSetRevision, ChangeSetItem."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session, joinedload

from ..models.change_set import ChangeSet, ChangeSetItem, ChangeSetRevision

# Valid state transitions for the ChangeSet state machine.
_VALID_TRANSITIONS: dict[str, set[str]] = {
    "DRAFT": {"READY", "ARCHIVED"},
    "READY": {"SUPERSEDED", "ARCHIVED"},
    "SUPERSEDED": {"ARCHIVED"},
    "ARCHIVED": set(),
}


class InvalidStateTransitionError(Exception):
    """Raised when a requested ChangeSet state transition is not permitted."""


class ChangeSetRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    # ── ChangeSet ─────────────────────────────────────────────────────────────

    def create(
        self,
        *,
        destination_channel: str,
        scope: str,
        source_snapshot_id: str,
    ) -> ChangeSet:
        """Create a new ChangeSet in DRAFT state."""
        now = datetime.now(tz=timezone.utc)
        cs = ChangeSet(
            id=str(uuid.uuid4()),
            state="DRAFT",
            destination_channel=destination_channel,
            scope=scope,
            source_snapshot_id=source_snapshot_id,
            created_at=now,
            updated_at=now,
        )
        self._db.add(cs)
        self._db.flush()
        return cs

    def get(self, change_set_id: str) -> Optional[ChangeSet]:
        return (
            self._db.query(ChangeSet)
            .options(joinedload(ChangeSet.revisions))
            .filter(ChangeSet.id == change_set_id)
            .first()
        )

    def list_by_channel(self, destination_channel: str) -> list[ChangeSet]:
        return (
            self._db.query(ChangeSet)
            .filter(ChangeSet.destination_channel == destination_channel)
            .order_by(ChangeSet.created_at.desc())
            .all()
        )

    def list_by_snapshot(self, source_snapshot_id: str) -> list[ChangeSet]:
        return (
            self._db.query(ChangeSet)
            .filter(ChangeSet.source_snapshot_id == source_snapshot_id)
            .order_by(ChangeSet.created_at.desc())
            .all()
        )

    def transition_state(self, change_set_id: str, target_state: str) -> ChangeSet:
        """Apply a validated state transition. Raises InvalidStateTransitionError if not allowed."""
        cs = self._db.get(ChangeSet, change_set_id)
        if cs is None:
            raise ValueError(f"ChangeSet not found: {change_set_id}")
        allowed = _VALID_TRANSITIONS.get(cs.state, set())
        if target_state not in allowed:
            raise InvalidStateTransitionError(
                f"Cannot transition ChangeSet {change_set_id} from {cs.state!r} to {target_state!r}. "
                f"Allowed: {sorted(allowed) if allowed else 'none (terminal state)'}."
            )
        cs.state = target_state
        cs.updated_at = datetime.now(tz=timezone.utc)
        self._db.flush()
        return cs

    # ── ChangeSetRevision ────────────────────────────────────────────────────

    def create_revision(
        self,
        *,
        change_set_id: str,
        digest: str,
        parent_revision_id: Optional[str] = None,
    ) -> ChangeSetRevision:
        """Create an immutable ChangeSetRevision. revision_number is auto-assigned."""
        existing = (
            self._db.query(ChangeSetRevision)
            .filter(ChangeSetRevision.change_set_id == change_set_id)
            .order_by(ChangeSetRevision.revision_number.desc())
            .first()
        )
        next_number = (existing.revision_number + 1) if existing else 1

        revision = ChangeSetRevision(
            id=str(uuid.uuid4()),
            change_set_id=change_set_id,
            revision_number=next_number,
            parent_revision_id=parent_revision_id,
            digest=digest,
            created_at=datetime.now(tz=timezone.utc),
        )
        self._db.add(revision)
        self._db.flush()
        return revision

    def get_revision(self, revision_id: str) -> Optional[ChangeSetRevision]:
        return (
            self._db.query(ChangeSetRevision)
            .options(joinedload(ChangeSetRevision.items))
            .filter(ChangeSetRevision.id == revision_id)
            .first()
        )

    def get_revision_by_digest(self, digest: str) -> Optional[ChangeSetRevision]:
        return (
            self._db.query(ChangeSetRevision)
            .filter(ChangeSetRevision.digest == digest)
            .first()
        )

    def list_revisions(self, change_set_id: str) -> list[ChangeSetRevision]:
        return (
            self._db.query(ChangeSetRevision)
            .filter(ChangeSetRevision.change_set_id == change_set_id)
            .order_by(ChangeSetRevision.revision_number)
            .all()
        )

    # ── ChangeSetItem ────────────────────────────────────────────────────────

    def add_item(
        self,
        *,
        revision_id: str,
        product_id: str,
        proposal_id: str,
        proposal_hash: str,
        safety_result_id: str,
        rule_version_id: str,
        proposed_price: Decimal,
        current_price: Optional[Decimal] = None,
    ) -> ChangeSetItem:
        delta = (proposed_price - current_price) if current_price is not None else None
        item = ChangeSetItem(
            revision_id=revision_id,
            product_id=product_id,
            proposal_id=proposal_id,
            proposal_hash=proposal_hash,
            safety_result_id=safety_result_id,
            rule_version_id=rule_version_id,
            proposed_price=proposed_price,
            current_price=current_price,
            delta=delta,
            created_at=datetime.now(tz=timezone.utc),
        )
        self._db.add(item)
        self._db.flush()
        return item

    def list_items(self, revision_id: str) -> list[ChangeSetItem]:
        return (
            self._db.query(ChangeSetItem)
            .filter(ChangeSetItem.revision_id == revision_id)
            .order_by(ChangeSetItem.product_id)
            .all()
        )
