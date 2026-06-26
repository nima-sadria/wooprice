"""A2.9 AI Foundation ORM models.

Isolation boundary:
- These models are NEVER imported by Rule Engine, Safety Engine, Change Set Engine,
  Dry Run Engine, Execution Engine, or Scheduling Engine.
- subject_id and related_object_id are plain strings — no FK to prior-phase tables
  (phase independence).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import A2Base

_VALID_CATEGORIES = (
    "'EXPLANATION','RISK_SUMMARY','ANOMALY','STALE_PRICE','REVIEW_PRIORITY','RULE_RECOMMENDATION'"
)
_VALID_SEVERITIES = "'INFO','LOW','MEDIUM','HIGH','CRITICAL'"


class AdvisorySession(A2Base):
    """Audit record for one advisory analysis interaction."""

    __tablename__ = "a2_advisory_sessions"
    __table_args__ = (
        CheckConstraint(
            f"category IN ({_VALID_CATEGORIES})",
            name="a2_advisory_sessions_category_check",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(100), nullable=False)
    # Plain string — no FK to prior-phase tables (phase independence)
    subject_id: Mapped[str] = mapped_column(String(36), nullable=False)
    prompt_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    response_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model_version: Mapped[str] = mapped_column(String(100), nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    insights: Mapped[list[AdvisoryInsight]] = relationship(
        "AdvisoryInsight",
        back_populates="session",
        cascade="save-update, merge",
        order_by="AdvisoryInsight.generated_at",
    )


class AdvisoryInsight(A2Base):
    """Single advisory finding produced by the AI Foundation.

    Insights are immutable once created. They are advisory only — they cannot
    be used as executable input to any component in the Trusted Execution Path.
    """

    __tablename__ = "a2_advisory_insights"
    __table_args__ = (
        CheckConstraint(
            f"category IN ({_VALID_CATEGORIES})",
            name="a2_advisory_insights_category_check",
        ),
        CheckConstraint(
            f"severity IN ({_VALID_SEVERITIES})",
            name="a2_advisory_insights_severity_check",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("a2_advisory_sessions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    summary: Mapped[str] = mapped_column(String(512), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    # Plain strings — no FK to prior-phase tables
    related_object_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    related_object_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    recommendation_trace: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    session: Mapped[AdvisorySession] = relationship(
        "AdvisorySession", back_populates="insights"
    )
