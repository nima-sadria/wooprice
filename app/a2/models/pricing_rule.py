"""A2.3-R2 PricingRule ORM model."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import A2Base
from ..rules.base import RuleType


class PricingRule(A2Base):
    """Versioned pricing rule definition stored in the A2 database."""

    __tablename__ = "a2_pricing_rules"
    __table_args__ = (
        CheckConstraint(
            "rule_type IN ('cost_plus', 'fx_based', 'fee_based', 'formula', 'competition')",
            name="a2_pricing_rules_rule_type_check",
        ),
    )

    rule_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    rule_name: Mapped[str] = mapped_column(String(256), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(64), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    versions: Mapped[list["PricingRuleVersion"]] = relationship(
        "PricingRuleVersion",
        back_populates="rule",
        order_by="PricingRuleVersion.version_number",
    )
