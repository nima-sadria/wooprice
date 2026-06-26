"""A2.3-R2 PricingRuleVersion ORM model.

Versions are immutable once published: publish_version() in the repository
raises ValueError on re-publish. is_current indicates the active version
and may be switched between published versions via set_current_version().
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import A2Base


class PricingRuleVersion(A2Base):
    """One immutable version of a pricing rule's formula and required inputs."""

    __tablename__ = "a2_pricing_rule_versions"
    __table_args__ = (
        UniqueConstraint(
            "rule_id", "version_number",
            name="uq_a2_pricing_rule_versions_rule_version",
        ),
    )

    version_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    rule_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("a2_pricing_rules.rule_id", ondelete="RESTRICT"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    formula: Mapped[str] = mapped_column(String(1024), nullable=False)
    required_inputs_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    rule: Mapped["PricingRule"] = relationship("PricingRule", back_populates="versions")
