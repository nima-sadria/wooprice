"""A2.7 Execution Engine models.

Scope boundary (A2.7 only):
- Does NOT call A2.8 (Scheduling Engine) or any later phase.
- Does NOT call WooCommerce write APIs, Apply, or any external system.
- Does NOT replace the existing Workspace or existing Apply workflow.
- IDs referencing prior-phase entities (Change Set, Dry Run, Confirmation) are
  stored as plain strings — no foreign keys to prior-phase tables (phase independence).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import A2Base


class Execution(A2Base):
    """Header record for one controlled execution run against an immutable Change Set revision."""

    __tablename__ = "a2_executions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','RUNNING','SUCCEEDED','FAILED','BLOCKED','CANCELLED')",
            name="a2_executions_status_check",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # Phase independence: no FK to a2_change_sets or any prior-phase table
    change_set_id: Mapped[str] = mapped_column(String(36), nullable=False)
    change_set_revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    change_set_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    # Phase independence: no FK to a2_seller_confirmations
    confirmation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    confirmation_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    destination_channel: Mapped[str] = mapped_column(String(256), nullable=False)
    scope: Mapped[str] = mapped_column(String(512), nullable=False)
    source_snapshot_id: Mapped[str] = mapped_column(String(36), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    batches: Mapped[list[ExecutionBatch]] = relationship(
        "ExecutionBatch",
        back_populates="execution",
        cascade="save-update, merge",
        order_by="ExecutionBatch.batch_number",
    )
    items: Mapped[list[ExecutionItem]] = relationship(
        "ExecutionItem",
        back_populates="execution",
        cascade="save-update, merge",
        order_by="ExecutionItem.created_at",
    )


class ExecutionBatch(A2Base):
    """A logical batch of ExecutionItems within one Execution."""

    __tablename__ = "a2_execution_batches"
    __table_args__ = (
        UniqueConstraint("execution_id", "batch_number", name="uq_a2_execution_batches_exec_num"),
        CheckConstraint(
            "status IN ('PENDING','RUNNING','SUCCEEDED','FAILED','BLOCKED','CANCELLED')",
            name="a2_execution_batches_status_check",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    execution_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("a2_executions.id", ondelete="RESTRICT"), nullable=False
    )
    batch_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    execution: Mapped[Execution] = relationship("Execution", back_populates="batches")
    items: Mapped[list[ExecutionItem]] = relationship(
        "ExecutionItem",
        back_populates="batch",
        cascade="save-update, merge",
        order_by="ExecutionItem.created_at",
    )


class ExecutionItem(A2Base):
    """Per-item execution record: one product-level write attempt within a batch."""

    __tablename__ = "a2_execution_items"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','RUNNING','SUCCEEDED','FAILED','BLOCKED','SKIPPED')",
            name="a2_execution_items_status_check",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    execution_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("a2_executions.id", ondelete="RESTRICT"), nullable=False
    )
    batch_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("a2_execution_batches.id", ondelete="RESTRICT"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)
    product_id: Mapped[str] = mapped_column(String(256), nullable=False)
    proposal_id: Mapped[str] = mapped_column(String(36), nullable=False)
    proposal_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    safety_result_id: Mapped[str] = mapped_column(String(36), nullable=False)
    rule_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    proposed_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    current_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 4), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    freshness_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    execution: Mapped[Execution] = relationship("Execution", back_populates="items")
    batch: Mapped[ExecutionBatch] = relationship("ExecutionBatch", back_populates="items")
    attempts: Mapped[list[ExecutionAttempt]] = relationship(
        "ExecutionAttempt",
        back_populates="item",
        cascade="all, delete-orphan",
        order_by="ExecutionAttempt.attempt_number",
    )


class ExecutionAttempt(A2Base):
    """Immutable record of one adapter call for an ExecutionItem."""

    __tablename__ = "a2_execution_attempts"
    __table_args__ = (
        UniqueConstraint("execution_item_id", "attempt_number", name="uq_a2_execution_attempts_item_num"),
        CheckConstraint(
            "status IN ('SUCCEEDED','FAILED','BLOCKED')",
            name="a2_execution_attempts_status_check",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    execution_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("a2_execution_items.id", ondelete="CASCADE"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    adapter_name: Mapped[str] = mapped_column(String(256), nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    item: Mapped[ExecutionItem] = relationship("ExecutionItem", back_populates="attempts")
