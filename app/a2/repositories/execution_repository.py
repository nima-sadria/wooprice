"""A2.7 Execution Repository — persistence and state machine for execution records.

State machines:
  Execution: PENDING → RUNNING → SUCCEEDED | FAILED | BLOCKED | CANCELLED
             PENDING → BLOCKED (prerequisites failed before RUNNING)
             PENDING → CANCELLED
             RUNNING → BLOCKED (hard block during execution, e.g. freshness failure)
             RUNNING → CANCELLED
             Terminal: SUCCEEDED, FAILED, BLOCKED, CANCELLED

  ExecutionItem: PENDING → RUNNING → SUCCEEDED | FAILED | BLOCKED
                 PENDING → SKIPPED
                 Terminal: SUCCEEDED, FAILED, BLOCKED, SKIPPED
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from ..models.execution import Execution, ExecutionAttempt, ExecutionBatch, ExecutionItem

_VALID_EXECUTION_TRANSITIONS: dict[str, set[str]] = {
    "PENDING": {"RUNNING", "CANCELLED", "BLOCKED"},
    "RUNNING": {"SUCCEEDED", "FAILED", "BLOCKED", "CANCELLED"},
    "SUCCEEDED": set(),
    "FAILED": set(),
    "BLOCKED": set(),
    "CANCELLED": set(),
}

_VALID_ITEM_TRANSITIONS: dict[str, set[str]] = {
    "PENDING": {"RUNNING", "SKIPPED", "BLOCKED"},
    "RUNNING": {"SUCCEEDED", "FAILED", "BLOCKED"},
    "SUCCEEDED": set(),
    "FAILED": set(),
    "BLOCKED": set(),
    "SKIPPED": set(),
}

_TERMINAL_EXECUTION_STATES = frozenset({"SUCCEEDED", "FAILED", "BLOCKED", "CANCELLED"})
_TERMINAL_ITEM_STATES = frozenset({"SUCCEEDED", "FAILED", "BLOCKED", "SKIPPED"})


class InvalidExecutionStateTransitionError(Exception):
    """Raised when a requested Execution or ExecutionItem state transition is not permitted."""


class ExecutionRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    # ── Execution ──────────────────────────────────────────────────────────

    def create_execution(
        self,
        *,
        change_set_id: str,
        change_set_revision_id: str,
        change_set_digest: str,
        confirmation_id: str,
        confirmation_digest: str,
        destination_channel: str,
        scope: str,
        source_snapshot_id: str,
        idempotency_key: str,
    ) -> Execution:
        now = datetime.now(tz=timezone.utc)
        execution = Execution(
            id=str(uuid.uuid4()),
            change_set_id=change_set_id,
            change_set_revision_id=change_set_revision_id,
            change_set_digest=change_set_digest,
            confirmation_id=confirmation_id,
            confirmation_digest=confirmation_digest,
            destination_channel=destination_channel,
            scope=scope,
            source_snapshot_id=source_snapshot_id,
            idempotency_key=idempotency_key,
            status="PENDING",
            created_at=now,
        )
        self._db.add(execution)
        self._db.flush()
        return execution

    def get_execution(self, execution_id: str) -> Optional[Execution]:
        return self._db.get(Execution, execution_id)

    def transition_execution(
        self,
        execution_id: str,
        new_state: str,
        *,
        error_message: Optional[str] = None,
    ) -> Execution:
        execution = self._db.get(Execution, execution_id)
        if execution is None:
            raise ValueError(f"Execution not found: {execution_id!r}")
        allowed = _VALID_EXECUTION_TRANSITIONS.get(execution.status, set())
        if new_state not in allowed:
            raise InvalidExecutionStateTransitionError(
                f"Cannot transition Execution {execution_id!r} from {execution.status!r} "
                f"to {new_state!r}. "
                f"Allowed: {sorted(allowed) if allowed else 'none — terminal state'}."
            )
        now = datetime.now(tz=timezone.utc)
        execution.status = new_state
        if new_state == "RUNNING":
            execution.started_at = now
        if new_state in _TERMINAL_EXECUTION_STATES:
            execution.completed_at = now
        if error_message is not None:
            execution.error_message = error_message
        self._db.flush()
        return execution

    def find_by_idempotency_key(self, idempotency_key: str) -> Optional[Execution]:
        return (
            self._db.query(Execution)
            .filter(Execution.idempotency_key == idempotency_key)
            .first()
        )

    def find_stale_running(self, *, timeout_minutes: int = 30) -> list[Execution]:
        """Return RUNNING executions whose started_at is older than timeout_minutes."""
        cutoff = datetime.now(tz=timezone.utc) - timedelta(minutes=timeout_minutes)
        return (
            self._db.query(Execution)
            .filter(Execution.status == "RUNNING")
            .filter(Execution.started_at < cutoff)
            .all()
        )

    # ── ExecutionBatch ─────────────────────────────────────────────────────

    def create_batch(self, *, execution_id: str, batch_number: int) -> ExecutionBatch:
        batch = ExecutionBatch(
            id=str(uuid.uuid4()),
            execution_id=execution_id,
            batch_number=batch_number,
            status="PENDING",
            created_at=datetime.now(tz=timezone.utc),
        )
        self._db.add(batch)
        self._db.flush()
        return batch

    def update_batch_status(self, batch_id: str, status: str) -> None:
        batch = self._db.get(ExecutionBatch, batch_id)
        if batch is not None:
            batch.status = status
            self._db.flush()

    # ── ExecutionItem ──────────────────────────────────────────────────────

    def create_item(
        self,
        *,
        execution_id: str,
        batch_id: str,
        idempotency_key: str,
        product_id: str,
        proposal_id: str,
        proposal_hash: str,
        safety_result_id: str,
        rule_version_id: str,
        proposed_price: Decimal,
        current_price: Optional[Decimal] = None,
    ) -> ExecutionItem:
        now = datetime.now(tz=timezone.utc)
        item = ExecutionItem(
            id=str(uuid.uuid4()),
            execution_id=execution_id,
            batch_id=batch_id,
            idempotency_key=idempotency_key,
            product_id=product_id,
            proposal_id=proposal_id,
            proposal_hash=proposal_hash,
            safety_result_id=safety_result_id,
            rule_version_id=rule_version_id,
            proposed_price=proposed_price,
            current_price=current_price,
            status="PENDING",
            freshness_verified=False,
            created_at=now,
            updated_at=now,
        )
        self._db.add(item)
        self._db.flush()
        return item

    def get_item(self, item_id: str) -> Optional[ExecutionItem]:
        return self._db.get(ExecutionItem, item_id)

    def list_items(self, execution_id: str) -> list[ExecutionItem]:
        return (
            self._db.query(ExecutionItem)
            .filter(ExecutionItem.execution_id == execution_id)
            .order_by(ExecutionItem.created_at)
            .all()
        )

    def transition_item(
        self,
        item_id: str,
        new_state: str,
        *,
        error_message: Optional[str] = None,
    ) -> ExecutionItem:
        item = self._db.get(ExecutionItem, item_id)
        if item is None:
            raise ValueError(f"ExecutionItem not found: {item_id!r}")
        allowed = _VALID_ITEM_TRANSITIONS.get(item.status, set())
        if new_state not in allowed:
            raise InvalidExecutionStateTransitionError(
                f"Cannot transition ExecutionItem {item_id!r} from {item.status!r} "
                f"to {new_state!r}. "
                f"Allowed: {sorted(allowed) if allowed else 'none — terminal state'}."
            )
        item.status = new_state
        item.updated_at = datetime.now(tz=timezone.utc)
        if error_message is not None:
            item.error_message = error_message
        self._db.flush()
        return item

    def mark_item_freshness_verified(self, item_id: str) -> None:
        """Set freshness_verified=True on an ExecutionItem without a state transition."""
        item = self._db.get(ExecutionItem, item_id)
        if item is not None:
            item.freshness_verified = True
            self._db.flush()

    def find_stale_running_items(self, *, timeout_minutes: int = 30) -> list[ExecutionItem]:
        """Return RUNNING items whose updated_at is older than timeout_minutes."""
        cutoff = datetime.now(tz=timezone.utc) - timedelta(minutes=timeout_minutes)
        return (
            self._db.query(ExecutionItem)
            .filter(ExecutionItem.status == "RUNNING")
            .filter(ExecutionItem.updated_at < cutoff)
            .all()
        )

    # ── ExecutionAttempt ───────────────────────────────────────────────────

    def create_attempt(
        self,
        *,
        execution_item_id: str,
        attempt_number: int,
        status: str,
        adapter_name: str,
        error_message: Optional[str] = None,
    ) -> ExecutionAttempt:
        attempt = ExecutionAttempt(
            execution_item_id=execution_item_id,
            attempt_number=attempt_number,
            status=status,
            adapter_name=adapter_name,
            error_message=error_message,
            created_at=datetime.now(tz=timezone.utc),
        )
        self._db.add(attempt)
        self._db.flush()
        return attempt

    def record_attempt(
        self,
        *,
        execution_item_id: str,
        attempt_number: int,
        status: str,
        adapter_name: str,
        error_message: Optional[str] = None,
    ) -> ExecutionAttempt:
        return self.create_attempt(
            execution_item_id=execution_item_id,
            attempt_number=attempt_number,
            status=status,
            adapter_name=adapter_name,
            error_message=error_message,
        )
