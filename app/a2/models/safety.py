"""A2.4 Safety Policy Engine models.

SafetyResult is NOT a Change Set entry or an applied price.
The Safety Policy Engine is a read-only evaluation gate only.
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
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import A2Base


class SafetyPolicy(A2Base):
    """Named safety policy. Versions hold immutable threshold history."""

    __tablename__ = "a2_safety_policies"
    __table_args__ = (
        CheckConstraint(
            "policy_type IN ('percentage_change','missing_zero','extra_zero','historical_anomaly')",
            name="a2_safety_policies_policy_type_check",
        ),
        CheckConstraint(
            "scope_type IN ('global','category','brand','user','channel')",
            name="a2_safety_policies_scope_type_check",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    policy_type: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(64), nullable=False, default="global")
    scope_value: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    versions: Mapped[list[PolicyVersion]] = relationship(
        "PolicyVersion",
        back_populates="policy",
        order_by="PolicyVersion.version_number",
    )


class PolicyVersion(A2Base):
    """Immutable snapshot of policy thresholds and mode. Once published, no modification allowed."""

    __tablename__ = "a2_policy_versions"
    __table_args__ = (
        CheckConstraint(
            "mode IN ('WARN','BLOCK','REQUIRE_OVERRIDE')",
            name="a2_policy_versions_mode_check",
        ),
        UniqueConstraint("policy_id", "version_number", name="uq_a2_policy_versions_policy_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    policy_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("a2_safety_policies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="WARN")
    parameters_json: Mapped[str] = mapped_column(Text, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    policy: Mapped[SafetyPolicy] = relationship("SafetyPolicy", back_populates="versions")


class SafetyResult(A2Base):
    """Structured, audit-ready output of one policy evaluation against one proposal.

    proposal_id references a2_price_proposals by convention; no FK enforced to
    preserve phase independence between A2.3 and A2.4.
    """

    __tablename__ = "a2_safety_results"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('PASS','WARN','BLOCK','REQUIRE_OVERRIDE')",
            name="a2_safety_results_outcome_check",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    proposal_id: Mapped[str] = mapped_column(String(36), nullable=False)
    policy_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("a2_policy_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    policy_name: Mapped[str] = mapped_column(String(256), nullable=False)
    policy_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    triggered_threshold: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    evaluated_value: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    override_log: Mapped[list[OverrideLog]] = relationship(
        "OverrideLog",
        back_populates="safety_result",
        cascade="all, delete-orphan",
    )


class OverrideLog(A2Base):
    """Audit trail for authorized REQUIRE_OVERRIDE decisions."""

    __tablename__ = "a2_override_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    safety_result_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("a2_safety_results.id", ondelete="CASCADE"),
        nullable=False,
    )
    authorizing_user: Mapped[str] = mapped_column(String(256), nullable=False)
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    safety_result: Mapped[SafetyResult] = relationship("SafetyResult", back_populates="override_log")
