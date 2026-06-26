"""A2.5 Change Set Engine models.

A ChangeSet is the single authoritative record of what is proposed to change,
for which products, on which channel. Once a revision is created it is immutable;
any modification to items or bindings creates a new ChangeSetRevision.

Scope boundary (A2.5 only):
- Does NOT call A2.6 (Dry Run), A2.7 (Execution), or any later phase.
- Does NOT call WooCommerce, Apply, or any external system.
- Does NOT apply or execute prices.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import A2Base


class ChangeSet(A2Base):
    """Header record for a set of proposed price changes.

    Immutable after creation except for the state field which is updated only
    by the state machine (via ChangeSetService.transition).
    """

    __tablename__ = "a2_change_sets"
    __table_args__ = (
        CheckConstraint(
            "state IN ('DRAFT','READY','SUPERSEDED','ARCHIVED')",
            name="a2_change_sets_state_check",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    destination_channel: Mapped[str] = mapped_column(String(256), nullable=False)
    scope: Mapped[str] = mapped_column(String(512), nullable=False)
    source_snapshot_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    revisions: Mapped[list[ChangeSetRevision]] = relationship(
        "ChangeSetRevision",
        back_populates="change_set",
        order_by="ChangeSetRevision.revision_number",
        cascade="all, delete-orphan",
    )


class ChangeSetRevision(A2Base):
    """Immutable version snapshot of a ChangeSet.

    Once created, no field may be modified. A new revision is created for any
    change to items or bindings. revision_number is monotonically increasing
    within a ChangeSet.
    """

    __tablename__ = "a2_change_set_revisions"
    __table_args__ = (
        UniqueConstraint(
            "change_set_id",
            "revision_number",
            name="uq_a2_change_set_revisions_cs_revnum",
        ),
        ForeignKeyConstraint(
            ["parent_revision_id"],
            ["a2_change_set_revisions.id"],
            ondelete="RESTRICT",
            name="fk_a2_change_set_revisions_parent",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    change_set_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("a2_change_sets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_revision_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    digest: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    change_set: Mapped[ChangeSet] = relationship("ChangeSet", back_populates="revisions")
    items: Mapped[list[ChangeSetItem]] = relationship(
        "ChangeSetItem",
        back_populates="revision",
        cascade="all, delete-orphan",
        order_by="ChangeSetItem.product_id",
    )


class ChangeSetItem(A2Base):
    """Per-product row within a ChangeSetRevision.

    proposal_id references a2_price_proposals (A2.3) by convention.
    safety_result_id references a2_safety_results (A2.4) by convention.
    rule_version_id references a2_pricing_rule_versions (A2.3) by convention.
    No FK constraints enforced here to preserve phase independence.
    """

    __tablename__ = "a2_change_set_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    revision_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("a2_change_set_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id: Mapped[str] = mapped_column(String(256), nullable=False)
    proposal_id: Mapped[str] = mapped_column(String(36), nullable=False)
    proposal_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    safety_result_id: Mapped[str] = mapped_column(String(36), nullable=False)
    rule_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    proposed_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    current_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 4), nullable=True)
    delta: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    revision: Mapped[ChangeSetRevision] = relationship("ChangeSetRevision", back_populates="items")
