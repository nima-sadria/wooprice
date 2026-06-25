"""A2.3 Rule Definition and Version models.

RuleVersion is immutable once published — the repository enforces this.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import A2Base


class RuleDefinition(A2Base):
    """Named pricing rule. Versions hold the immutable parameter history."""

    __tablename__ = "a2_rule_definitions"
    __table_args__ = (
        CheckConstraint(
            "rule_type IN ('cost_plus_profit', 'competitor_reference')",
            name="a2_rule_definitions_rule_type_check",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    rule_type: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    versions: Mapped[list[RuleVersion]] = relationship(
        "RuleVersion",
        back_populates="rule",
        order_by="RuleVersion.version_number",
    )


class RuleVersion(A2Base):
    """Immutable snapshot of rule parameters. Once is_published is True, no modification is allowed."""

    __tablename__ = "a2_rule_versions"
    __table_args__ = (
        UniqueConstraint("rule_id", "version_number", name="uq_a2_rule_versions_rule_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    rule_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("a2_rule_definitions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    parameters_json: Mapped[str] = mapped_column(Text, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    rule: Mapped[RuleDefinition] = relationship("RuleDefinition", back_populates="versions")
