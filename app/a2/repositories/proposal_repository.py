"""A2.3 Proposal Repository — PriceProposal persistence and lookup."""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session, joinedload

from ..models.proposal import PriceProposal, ProposalProvenance, ExecutionTraceEntry


class ProposalRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get(self, proposal_id: str) -> Optional[PriceProposal]:
        return (
            self._db.query(PriceProposal)
            .options(
                joinedload(PriceProposal.provenance),
                joinedload(PriceProposal.trace),
            )
            .filter(PriceProposal.id == proposal_id)
            .first()
        )

    def find_by_digest(self, digest: str) -> Optional[PriceProposal]:
        """Return an existing proposal with this computation_digest, or None.

        Used by the Rule Engine to enforce determinism: same inputs → same proposal.
        """
        return (
            self._db.query(PriceProposal)
            .filter(PriceProposal.computation_digest == digest)
            .first()
        )

    def list_by_snapshot(self, source_snapshot_id: str) -> list[PriceProposal]:
        return (
            self._db.query(PriceProposal)
            .filter(PriceProposal.source_snapshot_id == source_snapshot_id)
            .all()
        )
