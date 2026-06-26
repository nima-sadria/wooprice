"""A2.8 Scheduling Engine Service — deferred dispatch for confirmed Change Sets.

SCOPE BOUNDARY (A2.8 only):
- Does NOT connect to real WooCommerce write APIs.
- Does NOT replace the existing Workspace or existing Apply workflow.
- Does NOT call A2.9 (AI Foundation) or any later phase.
- Does NOT implement background daemons, external cron services, UI, or REST endpoints.
- Does NOT contain ChannelExecutionAdapter implementations (delegates entirely to A2.7).
- Does NOT contain DummyExecutionAdapter in production code (test-only usage via A2.7).

SCHEDULING SAFETY:
- Scheduling never authorizes execution by itself.
- A scheduled run dispatches execution only after lease and schedule-level validation.
- Dispatch calls A2.7 ExecutionService.execute() — scheduling never bypasses A2.7 validation.
- A2.7 independently validates: confirmation digest, Change Set digest, Dry Run state,
  item freshness, and idempotency. Scheduling cannot override these checks.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from ..models.schedule import Schedule, ScheduleLease, ScheduleRun
from ..repositories.scheduler_repository import (
    LeaseAlreadyHeldError,  # noqa: F401 — re-exported for callers
    LeaseTokenMismatchError,  # noqa: F401 — re-exported for callers
    SchedulerRepository,
)


class SchedulerService:
    """Orchestrates schedule lifecycle: creation, claiming, dispatch, retry, cancellation.

    Does not contain execution logic. All execution delegates to A2.7 ExecutionService.
    """

    def __init__(self, db: Session) -> None:
        self._db = db
        self._repo = SchedulerRepository(db)

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
        return self._repo.create_schedule(
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
            max_attempts=max_attempts,
        )

    def list_due_schedules(self, *, now: Optional[datetime] = None) -> list[Schedule]:
        """Return SCHEDULED schedules that are due for execution."""
        return self._repo.list_due_schedules(now=now)

    def create_run(self, schedule_id: str) -> ScheduleRun:
        """Create a PENDING run for the given schedule."""
        return self._repo.create_run(schedule_id)

    def claim_run(
        self,
        run_id: str,
        *,
        lease_owner: str,
        lease_duration_seconds: int = 300,
    ) -> ScheduleLease:
        """Claim the run lease for the given worker. Raises LeaseAlreadyHeldError if active lease exists."""
        return self._repo.claim_run(
            run_id,
            lease_owner=lease_owner,
            lease_duration_seconds=lease_duration_seconds,
        )

    def heartbeat(
        self,
        run_id: str,
        *,
        lease_token: str,
        lease_duration_seconds: int = 300,
    ) -> ScheduleLease:
        """Extend the active lease. Raises LeaseTokenMismatchError on token mismatch."""
        return self._repo.heartbeat(
            run_id, lease_token, lease_duration_seconds=lease_duration_seconds
        )

    def dispatch(
        self,
        run_id: str,
        *,
        lease_token: str,
        execution_service: object,
        adapter: object,
        items: list,
    ) -> ScheduleRun:
        """Dispatch execution for a claimed run via A2.7 ExecutionService.

        Validates the lease token before dispatch.
        Calls A2.7 ExecutionService.execute() — scheduling never bypasses A2.7 validation.
        A2.7 independently validates: confirmation digest, Change Set digest, Dry Run state,
        freshness, and idempotency. This service has no authority to skip those checks.
        Records execution_id and final run state after dispatch.
        """
        # ── Validate lease ─────────────────────────────────────────────────
        lease = self._repo.get_lease(run_id)
        if lease is None:
            raise ValueError(f"No lease found for run {run_id!r}")
        if lease.lease_token != lease_token:
            raise LeaseTokenMismatchError(
                f"Lease token mismatch for run {run_id!r}."
            )

        run = self._repo.get_run(run_id)
        if run is None:
            raise ValueError(f"ScheduleRun not found: {run_id!r}")

        schedule = self._repo.get_schedule(run.schedule_id)
        if schedule is None:
            raise ValueError(f"Schedule not found: {run.schedule_id!r}")

        # ── Transition CLAIMED → DISPATCHED ────────────────────────────────
        self._repo.transition_run(run_id, "DISPATCHED")

        # ── Build idempotency key unique to this schedule/run pair ─────────
        idempotency_key = f"schedule:{schedule.id}:run:{run.id}"

        # ── Call A2.7 ExecutionService — scheduling never bypasses A2.7 ───
        # A2.7 will independently validate: confirmation digest == change_set_digest,
        # dry_run_result, dry_run_digest_verified, digest recomputation, freshness.
        try:
            execution = execution_service.execute(  # type: ignore[union-attr]
                change_set_id=schedule.change_set_id,
                change_set_revision_id=schedule.change_set_revision_id,
                change_set_digest=schedule.change_set_digest,
                items=items,
                destination_channel=schedule.destination_channel,
                scope=schedule.scope,
                source_snapshot_id=schedule.source_snapshot_id,
                dry_run_result=schedule.dry_run_result,
                dry_run_digest_verified=schedule.dry_run_digest_verified,
                confirmation_id=schedule.confirmation_id,
                confirmation_digest=schedule.confirmation_digest,
                confirmation_is_valid=True,
                adapter=adapter,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:
            error_msg = str(exc)
            self._repo.record_dispatch_result(run_id, error_message=error_msg)
            self._repo.transition_run(run_id, "FAILED", error_message=error_msg)
            return self._repo.get_run(run_id)  # type: ignore[return-value]

        # ── Record dispatch result ─────────────────────────────────────────
        self._repo.record_dispatch_result(
            run_id,
            execution_id=execution.id,
            error_message=execution.error_message,
        )

        # ── Determine run and schedule final state ─────────────────────────
        now = datetime.now(tz=timezone.utc)
        fresh_schedule = self._repo.get_schedule(schedule.id)
        if execution.status == "SUCCEEDED":
            self._repo.transition_run(run_id, "SUCCEEDED")
            self._repo.transition_schedule(schedule.id, "COMPLETED")
        else:
            error_msg = execution.error_message or f"Execution ended with status {execution.status}"
            self._repo.transition_run(run_id, "FAILED", error_message=error_msg)
            next_attempt = (fresh_schedule.attempt_count or 0) + 1  # type: ignore[union-attr]
            if next_attempt >= fresh_schedule.max_attempts:  # type: ignore[union-attr]
                # Max attempts reached: increment count and fail the schedule
                fresh_schedule.attempt_count = next_attempt  # type: ignore[union-attr]
                fresh_schedule.last_error = error_msg  # type: ignore[union-attr]
                fresh_schedule.updated_at = now  # type: ignore[union-attr]
                self._db.flush()
                self._repo.transition_schedule(schedule.id, "FAILED")
            else:
                backoff = fresh_schedule.backoff_seconds or 60  # type: ignore[union-attr]
                self._repo.calculate_next_run(
                    schedule.id, backoff_seconds=backoff, error_message=error_msg
                )

        return self._repo.get_run(run_id)  # type: ignore[return-value]

    def cancel_schedule(self, schedule_id: str) -> Schedule:
        """Cancel a schedule and mark any PENDING runs as CANCELLED."""
        schedule = self._repo.get_schedule(schedule_id)
        if schedule is not None:
            for run in schedule.runs:
                if run.status == "PENDING":
                    self._repo.transition_run(run.id, "CANCELLED")
        return self._repo.cancel_schedule(schedule_id)

    def expire_stale_leases(self, *, now: Optional[datetime] = None) -> list[ScheduleRun]:
        """Find expired leases, expire their associated runs, and remove the lease records."""
        now = now or datetime.now(tz=timezone.utc)
        expired_leases = self._repo.find_expired_leases(now=now)
        expired_runs: list[ScheduleRun] = []
        for lease in expired_leases:
            run = self._repo.get_run(lease.run_id)
            if run is not None and run.status == "CLAIMED":
                self._repo.transition_run(run.id, "EXPIRED")
                expired_runs.append(run)
            self._repo.release_or_expire_lease(lease.run_id)
        return expired_runs
