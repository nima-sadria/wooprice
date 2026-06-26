"""
A2.3-R2 ProposalRepository — persist and retrieve PriceProposal records.

save() persists the proposal, its provenance record, and its execution
trace in a single flush. find_by_hash() enables deduplication: callers
should check for an existing proposal before saving a new one when the
same inputs would be evaluated multiple times.

Caller is responsible for committing the session.
"""
from __future__ import annotations

import json
from datetime import timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session, joinedload

from ..models.price_proposal import (
    ExecutionTraceRecord,
    PriceProposalRecord,
    ProposalProvenanceRecord,
)
from ..rules.engine import ProposalEnvelope
from ..rules.proposal import PriceProposal


class ProposalRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def save(self, envelope: ProposalEnvelope) -> PriceProposalRecord:
        """
        Persist a ProposalEnvelope (proposal + provenance + execution trace).

        Saves the PriceProposalRecord, one ProposalProvenanceRecord, and N
        ExecutionTraceRecord rows (one per TraceStep) in a single flush.
        """
        proposal = envelope.proposal

        record = PriceProposalRecord(
            proposal_id=proposal.proposal_id,
            canonical_product_id=proposal.canonical_product_id,
            source_id=proposal.source_id,
            snapshot_id=proposal.snapshot_id,
            rule_id=proposal.rule_id,
            rule_version_id=proposal.rule_version_id,
            rule_version_number=proposal.rule_version,
            proposed_price=float(proposal.proposed_price),
            currency=proposal.currency,
            input_values_json=json.dumps(proposal.input_values, sort_keys=True),
            proposal_hash=proposal.proposal_hash,
            generated_at=proposal.generated_at,
        )
        self._db.add(record)
        self._db.flush()

        provenance = ProposalProvenanceRecord(
            proposal_id=proposal.proposal_id,
            rule_id=proposal.rule_id,
            rule_version_id=proposal.rule_version_id,
            rule_version_number=proposal.rule_version,
            source_id=proposal.source_id,
            snapshot_id=proposal.snapshot_id,
            formula=self._find_formula_from_trace(envelope),
            input_values_json=json.dumps(proposal.input_values, sort_keys=True),
        )
        self._db.add(provenance)

        for step in envelope.trace:
            self._db.add(ExecutionTraceRecord(
                proposal_id=proposal.proposal_id,
                step_order=step.step_order,
                step_name=step.step_name,
                step_input_json=step.step_input_json,
                step_output_json=step.step_output_json,
                step_formula=step.step_formula,
            ))

        self._db.flush()
        return record

    def find_by_hash(self, proposal_hash: str) -> Optional[PriceProposal]:
        """
        Return an existing PriceProposal with this hash, or None.

        Use this before save() to implement deduplication: same inputs always
        produce the same proposal_hash, so re-evaluation with identical inputs
        returns the cached proposal without creating a duplicate record.
        """
        record = (
            self._db.query(PriceProposalRecord)
            .filter(PriceProposalRecord.proposal_hash == proposal_hash)
            .first()
        )
        if record is None:
            return None
        return self._record_to_proposal(record)

    def get(self, proposal_id: str) -> Optional[PriceProposalRecord]:
        """Return a PriceProposalRecord with provenance and trace eagerly loaded."""
        return (
            self._db.query(PriceProposalRecord)
            .options(
                joinedload(PriceProposalRecord.provenance),
                joinedload(PriceProposalRecord.trace),
            )
            .filter(PriceProposalRecord.proposal_id == proposal_id)
            .first()
        )

    def list_by_product(self, canonical_product_id: str) -> list[PriceProposal]:
        records = (
            self._db.query(PriceProposalRecord)
            .filter(PriceProposalRecord.canonical_product_id == canonical_product_id)
            .order_by(PriceProposalRecord.generated_at.desc())
            .all()
        )
        return [self._record_to_proposal(r) for r in records]

    def list_by_snapshot(self, snapshot_id: str) -> list[PriceProposal]:
        records = (
            self._db.query(PriceProposalRecord)
            .filter(PriceProposalRecord.snapshot_id == snapshot_id)
            .order_by(PriceProposalRecord.generated_at.desc())
            .all()
        )
        return [self._record_to_proposal(r) for r in records]

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _record_to_proposal(record: PriceProposalRecord) -> PriceProposal:
        generated_at = record.generated_at
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=timezone.utc)

        input_values: dict[str, str] = json.loads(record.input_values_json or "{}")

        return PriceProposal(
            proposal_id=record.proposal_id,
            canonical_product_id=record.canonical_product_id,
            proposed_price=Decimal(str(record.proposed_price)),
            currency=record.currency,
            generated_at=generated_at,
            rule_id=record.rule_id,
            rule_version=record.rule_version_number,
            rule_version_id=record.rule_version_id,
            source_id=record.source_id,
            snapshot_id=record.snapshot_id,
            input_values=input_values,
            proposal_hash=record.proposal_hash,
        )

    @staticmethod
    def _find_formula_from_trace(envelope: ProposalEnvelope) -> str:
        """Extract the formula string from the formula_evaluation trace step."""
        for step in envelope.trace:
            if step.step_name == "formula_evaluation":
                return step.step_formula
        return "(formula not recorded)"
