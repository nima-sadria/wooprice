"""A2.8 Scheduler Repository — persistence and state machine for scheduling records.

State machines:
  Schedule: SCHEDULED → PAUSED | CANCELLED | COMPLETED | FAILED
            PAUSED    → SCHEDULED | CANCELLED
            Terminal: CANCELLED, COMPLETED, FAILED

  ScheduleRun: PENDING    → CLAIMED | CANCELLED | EXPIRED
               CLAIMED    → DISPATCHED | FAILED | CANCELLED | EXPIRED
               DISPATCHED → SUCCEEDED | FAILED
               Terminal: SUCCEEDED, FAILED, CANCELLED, EXPIRED
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from ..models.schedule import Schedule, ScheduleLease, ScheduleRun

_VALID_SCHEDULE_TRANSITIONS: dict[str, set[str]] = {
    "SCHEDULED": {"PAUSED", "CANCELLED", "COMPLETED", "FAILED"},
    "PAUSED": {"SCHEDULED", "CANCELLED"},
    "CANCELLED": set(),
    "COMPLETED": set(),
    "FAILED": set(),
}

_VALID_RUN_TRANSITIONS: dict[str, set[str]] = {
    "PENDING": {"CLAIMED", "CANCELLED", "EXPIRED"},
    "CLAIMED": {"DISPATCHED", "FAILED", "CANCELLED", "EXPIRED"},
    "DISPATCHED": {"SUCCEEDED", "FAILED"},
    "SUCCEEDED": set(),
    "FAILED": set(),
    "CANCELLED": set(),
    "EXPIRED": set(),
}

_TERMINAL_SCHEDULE_STATES = frozenset({"CANCELLED", "COMPLETED", "FAILED"})
_TERMINAL_RUN_STATES = frozenset({"SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED"})


class InvalidScheduleStateTransitionError(Exception):
    """Raised when a requested Schedule or ScheduleRun state transition is not allowed."""


class LeaseAlreadyHeldError(Exception):
    """Raised when a run already has an active (non-expired) lease."""


class LeaseTokenMismatchError(Exception):
    """Raised when the provided lease token does not match the active lease."""


class SchedulerRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    # ── Schedule ───────────────────────────────────────────────────────────

    def create_schedule(
        self,
        *,
        change_set_id: str,
        change_set_revision_id: str,
        change_set_digest: str,
        confirmation_id: str,
        confirmation_digest: str,
        dry_run_id: str,
        dry_run_result: str,
        dry_run_digest_verified: bool,
        destination_channel: str,
        scope: str,
        source_snapshot_id: str,
        scheduled_at: datetime,
        max_attempts: int = 3,
    ) -> Schedule:
        now = datetime.now(tz=timezone.utc)
        schedule = Schedule(
            id=str(uuid.uuid4()),
            change_set_id=change_set_id,
            change_set_revision_id=change_set_revision_id,
            change_set_digest=change_set_digest,
            confirmation_id=confirmation_id,
            confirmation_digest=confirmation_digest,
            dry_run_id=dry_run_id,
            dry_run_result=dry_run_result,
            dry_run_digest_verified=dry_run_digest_verified,
            destination_channel=destination_channel,
            scope=scope,
            source_snapshot_id=source_snapshot_id,
            scheduled_at=scheduled_at,
            status="SCHEDULED",
            max_attempts=max_attempts,
            attempt_count=0,
            created_at=now,
            updated_at=now,
        )
        self._db.add(schedule)
        self._db.flush()
        return schedule

    def get_schedule(self, schedule_id: str) -> Optional[Schedule]:
        return self._db.get(Schedule, schedule_id)

    def list_due_schedules(self, *, now: Optional[datetime] = None) -> list[Schedule]:
        """Return SCHEDULED schedules whose due time has arrived."""
        now = now or datetime.now(tz=timezone.utc)
        return (
            self._db.query(Schedule)
            .filter(Schedule.status == "SCHEDULED")
            .filter(
                or_(
                    and_(Schedule.next_run_at != None, Schedule.next_run_at <= now),  # noqa: E711
                    and_(Schedule.next_run_at == None, Schedule.scheduled_at <= now),  # noqa: E711
                )
            )
            .all()
        )

    def transition_schedule(
        self,
        schedule_id: str,
        new_state: str,
        *,
        error_message: Optional[str] = None,
    ) -> Schedule:
        schedule = self._db.get(Schedule, schedule_id)
        if schedule is None:
            raise ValueError(f"Schedule not found: {schedule_id!r}")
        allowed = _VALID_SCHEDULE_TRANSITIONS.get(schedule.status, set())
        if new_state not in allowed:
            raise InvalidScheduleStateTransitionError(
                f"Cannot transition Schedule {schedule_id!r} from {schedule.status!r} "
                f"to {new_state!r}. "
                f"Allowed: {sorted(allowed) if allowed else 'none — terminal state'}."
            )
        schedule.status = new_state
        schedule.updated_at = datetime.now(tz=timezone.utc)
        if error_message is not None:
            schedule.last_error = error_message
        self._db.flush()
        return schedule

    def cancel_schedule(self, schedule_id: str) -> Schedule:
        return self.transition_schedule(schedule_id, "CANCELLED")

    def calculate_next_run(
        self,
        schedule_id: str,
        *,
        backoff_seconds: int,
        error_message: Optional[str] = None,
    ) -> Schedule:
        """Increment attempt_count and schedule next_run_at for retry."""
        schedule = self._db.get(Schedule, schedule_id)
        if schedule is None:
            raise ValueError(f"Schedule not found: {schedule_id!r}")
        now = datetime.now(tz=timezone.utc)
        schedule.attempt_count = (schedule.attempt_count or 0) + 1
        schedule.backoff_seconds = backoff_seconds
        schedule.next_run_at = now + timedelta(seconds=backoff_seconds)
        if error_message is not None:
            schedule.last_error = error_message
        schedule.updated_at = now
        self._db.flush()
        return schedule

    # ── ScheduleRun ────────────────────────────────────────────────────────

    def create_run(self, schedule_id: str) -> ScheduleRun:
        now = datetime.now(tz=timezone.utc)
        run = ScheduleRun(
            id=str(uuid.uuid4()),
            schedule_id=schedule_id,
            status="PENDING",
            created_at=now,
            updated_at=now,
        )
        self._db.add(run)
        self._db.flush()
        return run

    def get_run(self, run_id: str) -> Optional[ScheduleRun]:
        return self._db.get(ScheduleRun, run_id)

    def transition_run(
        self,
        run_id: str,
        new_state: str,
        *,
        error_message: Optional[str] = None,
    ) -> ScheduleRun:
        run = self._db.get(ScheduleRun, run_id)
        if run is None:
            raise ValueError(f"ScheduleRun not found: {run_id!r}")
        allowed = _VALID_RUN_TRANSITIONS.get(run.status, set())
        if new_state not in allowed:
            raise InvalidScheduleStateTransitionError(
                f"Cannot transition ScheduleRun {run_id!r} from {run.status!r} "
                f"to {new_state!r}. "
                f"Allowed: {sorted(allowed) if allowed else 'none — terminal state'}."
            )
        run.status = new_state
        run.updated_at = datetime.now(tz=timezone.utc)
        if error_message is not None:
            run.error_message = error_message
        self._db.flush()
        return run

    def record_dispatch_result(
        self,
        run_id: str,
        *,
        execution_id: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> ScheduleRun:
        run = self._db.get(ScheduleRun, run_id)
        if run is None:
            raise ValueError(f"ScheduleRun not found: {run_id!r}")
        if execution_id is not None:
            run.execution_id = execution_id
        if error_message is not None:
            run.error_message = error_message
        run.updated_at = datetime.now(tz=timezone.utc)
        self._db.flush()
        return run

    # ── ScheduleLease ──────────────────────────────────────────────────────

    def claim_run(
        self,
        run_id: str,
        *,
        lease_owner: str,
        lease_duration_seconds: int = 300,
    ) -> ScheduleLease:
        """Acquire the lease for run_id.

        Reclaims an expired lease (updates the existing record with a new owner/token).
        Raises LeaseAlreadyHeldError if an active (non-expired) lease exists.
        Transitions run PENDING → CLAIMED on first acquisition.
        """
        now = datetime.now(tz=timezone.utc)
        lease_token = str(uuid.uuid4())
        expires = now + timedelta(seconds=lease_duration_seconds)

        existing = (
            self._db.query(ScheduleLease)
            .filter(ScheduleLease.run_id == run_id)
            .first()
        )

        if existing is not None:
            if existing.lease_expires_at > now:
                raise LeaseAlreadyHeldError(
                    f"Run {run_id!r} already has an active lease "
                    f"(owner={existing.lease_owner!r}, expires={existing.lease_expires_at})."
                )
            # Expired lease: reclaim by updating in place
            existing.lease_owner = lease_owner
            existing.lease_token = lease_token
            existing.lease_acquired_at = now
            existing.lease_expires_at = expires
            existing.heartbeat_at = now
            self._db.flush()
            return existing

        # No existing lease: create new and transition run PENDING → CLAIMED
        lease = ScheduleLease(
            id=str(uuid.uuid4()),
            run_id=run_id,
            lease_owner=lease_owner,
            lease_token=lease_token,
            lease_acquired_at=now,
            lease_expires_at=expires,
            heartbeat_at=now,
            created_at=now,
        )
        self._db.add(lease)
        self._db.flush()
        self.transition_run(run_id, "CLAIMED")
        return lease

    def get_lease(self, run_id: str) -> Optional[ScheduleLease]:
        return (
            self._db.query(ScheduleLease)
            .filter(ScheduleLease.run_id == run_id)
            .first()
        )

    def heartbeat(
        self,
        run_id: str,
        lease_token: str,
        *,
        lease_duration_seconds: int = 300,
    ) -> ScheduleLease:
        """Extend the active lease. Fails on token mismatch or missing lease."""
        lease = self.get_lease(run_id)
        if lease is None:
            raise ValueError(f"No lease found for run {run_id!r}")
        if lease.lease_token != lease_token:
            raise LeaseTokenMismatchError(
                f"Lease token mismatch for run {run_id!r}."
            )
        now = datetime.now(tz=timezone.utc)
        lease.lease_expires_at = now + timedelta(seconds=lease_duration_seconds)
        lease.heartbeat_at = now
        self._db.flush()
        return lease

    def release_or_expire_lease(
        self,
        run_id: str,
        *,
        lease_token: Optional[str] = None,
    ) -> None:
        """Remove a lease record. If lease_token provided, validates it first."""
        lease = self.get_lease(run_id)
        if lease is None:
            return
        if lease_token is not None and lease.lease_token != lease_token:
            raise LeaseTokenMismatchError(
                f"Lease token mismatch for run {run_id!r} during release."
            )
        self._db.delete(lease)
        self._db.flush()

    def find_expired_leases(self, *, now: Optional[datetime] = None) -> list[ScheduleLease]:
        """Return leases whose lease_expires_at is in the past."""
        now = now or datetime.now(tz=timezone.utc)
        return (
            self._db.query(ScheduleLease)
            .filter(ScheduleLease.lease_expires_at < now)
            .all()
        )
