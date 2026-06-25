"""A2.3 PriceProposal, ProposalProvenance, and ExecutionTraceEntry models.

PriceProposal is NOT a Final Applied Price. It is the output of the Rule Engine
and requires Safety Policy evaluation (A2.4), Change Set creation (A2.5),
Dry Run (A2.6), and Owner-approved execution (A2.7) before any price is applied.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import A2Base


class PriceProposal(A2Base):
    """Output of Rule Engine evaluation for a single source row.

    computation_digest is a SHA-256 of (rule_version_id + input_cost + currency + parameters_json).
    Identical inputs to the same published rule version always produce the same digest.
    """

    __tablename__ = "a2_price_proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    rule_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("a2_rule_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_snapshot_id: Mapped[str] = mapped_column(String(36), nullable=False)
    input_cost: Mapped[float] = mapped_column(Float, nullable=False)
    proposed_price: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    computation_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    provenance: Mapped[list[ProposalProvenance]] = relationship(
        "ProposalProvenance",
        back_populates="proposal",
        cascade="all, delete-orphan",
    )
    trace: Mapped[list[ExecutionTraceEntry]] = relationship(
        "ExecutionTraceEntry",
        back_populates="proposal",
        order_by="ExecutionTraceEntry.step_order",
        cascade="all, delete-orphan",
    )


class ProposalProvenance(A2Base):
    """Links a PriceProposal back to its source row.

    Stores all input fields used, enabling full reproducibility:
    given source_row_ref + source_snapshot_id + rule_version_id, any
    proposal can be re-derived deterministically at any future time.
    """

    __tablename__ = "a2_proposal_provenance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    proposal_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("a2_price_proposals.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_row_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    input_fields_json: Mapped[str] = mapped_column(Text, nullable=False)

    proposal: Mapped[PriceProposal] = relationship("PriceProposal", back_populates="provenance")


class ExecutionTraceEntry(A2Base):
    """Step-by-step audit record of formula evaluation for a PriceProposal.

    Every step name, input, output, and formula string is recorded so any
    proposal can be fully explained without re-running the computation.
    """

    __tablename__ = "a2_execution_traces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    proposal_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("a2_price_proposals.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    step_name: Mapped[str] = mapped_column(String(100), nullable=False)
    step_input_json: Mapped[str] = mapped_column(Text, nullable=False)
    step_output_json: Mapped[str] = mapped_column(Text, nullable=False)
    step_formula: Mapped[str] = mapped_column(String(500), nullable=False)

    proposal: Mapped[PriceProposal] = relationship("PriceProposal", back_populates="trace")
