"""A2.8 Scheduling Engine models.

Scope boundary (A2.8 only):
- Does NOT call A2.9 (AI Foundation) or any later phase.
- Does NOT connect to real WooCommerce write APIs.
- Does NOT replace the existing Workspace or existing Apply workflow.
- IDs referencing prior-phase entities (Change Set, Confirmation, Dry Run) are
  stored as plain strings — no foreign keys to prior-phase tables (phase independence).
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


class Schedule(A2Base):
    """A deferred execution plan for a confirmed, immutable Change Set."""

    __tablename__ = "a2_schedules"
    __table_args__ = (
        CheckConstraint(
            "status IN ('SCHEDULED','PAUSED','CANCELLED','COMPLETED','FAILED')",
            name="a2_schedules_status_check",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # Phase independence: no FK to prior-phase tables
    change_set_id: Mapped[str] = mapped_column(String(36), nullable=False)
    change_set_revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    change_set_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    confirmation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    confirmation_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    dry_run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    dry_run_result: Mapped[str] = mapped_column(String(20), nullable=False)
    dry_run_digest_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    destination_channel: Mapped[str] = mapped_column(String(256), nullable=False)
    scope: Mapped[str] = mapped_column(String(512), nullable=False)
    source_snapshot_id: Mapped[str] = mapped_column(String(36), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="SCHEDULED")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    backoff_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    runs: Mapped[list[ScheduleRun]] = relationship(
        "ScheduleRun",
        back_populates="schedule",
        cascade="save-update, merge",
        order_by="ScheduleRun.created_at",
    )


class ScheduleRun(A2Base):
    """One execution attempt for a Schedule."""

    __tablename__ = "a2_schedule_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','CLAIMED','DISPATCHED','SUCCEEDED','FAILED','CANCELLED','EXPIRED')",
            name="a2_schedule_runs_status_check",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    schedule_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("a2_schedules.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    # Plain string — no FK to a2_executions (phase independence)
    execution_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    schedule: Mapped[Schedule] = relationship("Schedule", back_populates="runs")
    lease: Mapped[Optional[ScheduleLease]] = relationship(
        "ScheduleLease",
        back_populates="run",
        uselist=False,
        cascade="save-update, merge",
    )


class ScheduleLease(A2Base):
    """Ownership record for one run at a time. Enforces single-executor guarantee."""

    __tablename__ = "a2_schedule_leases"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_a2_schedule_leases_run_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("a2_schedule_runs.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    lease_owner: Mapped[str] = mapped_column(String(256), nullable=False)
    lease_token: Mapped[str] = mapped_column(String(36), nullable=False)
    lease_acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    run: Mapped[ScheduleRun] = relationship("ScheduleRun", back_populates="lease")
