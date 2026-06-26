"""A2.6 Dry Run Engine models.

DryRun, DryRunResult, and SellerConfirmation are completely read-only with
respect to destination systems. No WooCommerce write operations occur here.

Scope boundary (A2.6 only):
- Does NOT call A2.7 (Execution Engine) or any later phase.
- Does NOT call WooCommerce, Apply, or any external system.
- Does NOT execute or apply prices.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import A2Base


class DryRun(A2Base):
    """Header record for one dry-run execution against a Change Set revision.

    Records all validation outcomes and whether execution is eligible.
    Advisory only — does not trigger execution.
    """

    __tablename__ = "a2_dry_runs"
    __table_args__ = (
        CheckConstraint(
            "validation_result IN ('PASS','WARN','BLOCK')",
            name="a2_dry_runs_validation_result_check",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    change_set_id: Mapped[str] = mapped_column(String(36), nullable=False)
    change_set_revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    change_set_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    digest_verified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    validation_result: Mapped[str] = mapped_column(String(20), nullable=False)
    execution_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    proposal_count: Mapped[int] = mapped_column(Integer, nullable=False)
    blocked_count: Mapped[int] = mapped_column(Integer, nullable=False)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    results: Mapped[list[DryRunResult]] = relationship(
        "DryRunResult",
        back_populates="dry_run",
        cascade="all, delete-orphan",
        order_by="DryRunResult.id",
    )
    confirmations: Mapped[list[SellerConfirmation]] = relationship(
        "SellerConfirmation",
        back_populates="dry_run",
        cascade="save-update, merge",
        order_by="SellerConfirmation.created_at",
    )


class DryRunResult(A2Base):
    """Per-item validation result within a DryRun."""

    __tablename__ = "a2_dry_run_results"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('PASS','WARN','BLOCK')",
            name="a2_dry_run_results_outcome_check",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dry_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("a2_dry_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id: Mapped[str] = mapped_column(String(256), nullable=False)
    proposal_id: Mapped[str] = mapped_column(String(36), nullable=False)
    proposal_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    dry_run: Mapped[DryRun] = relationship("DryRun", back_populates="results")


class SellerConfirmation(A2Base):
    """Seller confirmation bound to a specific Change Set digest.

    Becomes invalid (is_valid=False) if the Change Set digest changes after
    confirmation — i.e., any change to proposals, safety results, rule
    versions, destination channel, scope, or source snapshot.
    """

    __tablename__ = "a2_seller_confirmations"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    dry_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("a2_dry_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    change_set_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    confirmed_by: Mapped[str] = mapped_column(String(256), nullable=False)
    is_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    invalidated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    invalidation_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    dry_run: Mapped[DryRun] = relationship("DryRun", back_populates="confirmations")
