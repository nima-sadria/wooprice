"""A2.7 Execution Engine Service — controlled execution of confirmed, immutable Change Sets.

SCOPE BOUNDARY (A2.7 only):
- Does NOT connect to real WooCommerce write APIs. Uses DummyExecutionAdapter only.
- Does NOT replace the existing Workspace or existing Apply workflow.
- Does NOT call A2.8 (Scheduling Engine) or any later phase.
- Does NOT implement background jobs, schedulers, AI, UI, or REST endpoints.

EXECUTION PREREQUISITES (all must pass before any item is written):
  1. SellerConfirmation is_valid must be True.
  2. Confirmation digest must equal Change Set digest (binding integrity).
  3. Dry Run validation_result must not be BLOCK.
  4. Dry Run digest_verified must be True.
  5. Independent digest recomputation from items must match stored Change Set digest.

EXECUTION SAFETY:
- Idempotency: same idempotency_key returns the existing Execution without re-executing.
- Freshness verification per item via adapter.verify_freshness() before any write.
- Freshness failure hard-blocks the item (BLOCKED) and the overall execution (BLOCKED).
- Retry on transient failures only; permanent failures go directly to FAILED.
- Terminal states (SUCCEEDED, FAILED, BLOCKED, CANCELLED) are immutable.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.a2.services.change_set_service import compute_change_set_digest
from ..models.execution import Execution
from ..repositories.execution_repository import ExecutionRepository


# ── Input / Result dataclasses ─────────────────────────────────────────────────


@dataclass
class ExecutionItemInput:
    """Input record for one product within the Change Set to be executed.

    Mirrors ChangeSetItemInput (A2.5) field names so that compute_change_set_digest
    can be called with ExecutionItemInput objects via duck typing.
    """

    product_id: str
    proposal_id: str
    proposal_hash: str
    safety_result_id: str
    rule_version_id: str
    proposed_price: Decimal
    current_price: Optional[Decimal] = None


@dataclass
class FreshnessContext:
    """Context passed to the adapter for live destination freshness verification."""

    product_id: str
    proposal_id: str
    proposal_hash: str
    proposed_price: Decimal
    current_price: Optional[Decimal]
    destination_channel: str
    change_set_digest: str
    confirmation_digest: str


@dataclass
class FreshnessResult:
    """Result of adapter.verify_freshness()."""

    verified: bool
    reason: Optional[str] = None


@dataclass
class ExecuteItemResult:
    """Result of adapter.execute_item()."""

    success: bool
    is_transient_failure: bool = False
    reason: Optional[str] = None


@dataclass
class ExecutionReport:
    """Summary report for a completed or in-progress Execution."""

    execution_id: str
    change_set_id: str
    change_set_revision_id: str
    change_set_digest: str
    confirmation_id: str
    destination_channel: str
    status: str
    idempotency_key: str
    total_items: int
    succeeded_count: int
    failed_count: int
    blocked_count: int
    skipped_count: int
    error_message: Optional[str] = None
    items: list = field(default_factory=list)


# ── Adapter interface ──────────────────────────────────────────────────────────


class ChannelExecutionAdapter(ABC):
    """Abstract interface for destination channel adapters.

    Each implementation targets one destination channel (WooCommerce, Shopify, etc.).
    A2.7 ships only DummyExecutionAdapter — no real write adapters in this phase.
    """

    @abstractmethod
    def verify_freshness(self, context: FreshnessContext) -> FreshnessResult:
        """Check live destination state before writing.

        Must return verified=False if the destination price or stock has changed
        since the Change Set was created. A False result hard-blocks the item.
        """

    @abstractmethod
    def execute_item(self, context: FreshnessContext) -> ExecuteItemResult:
        """Write the proposed price to the destination channel.

        Must be idempotent: calling with the same context after a SUCCEEDED result
        must return success=True without duplicating the write.
        """


# ── Dummy adapter (test/simulation only — no network calls) ───────────────────


class DummyExecutionAdapter(ChannelExecutionAdapter):
    """Simulates execution outcomes in-memory. No network calls, no WooCommerce writes.

    Configurable scenarios:
      - freshness_verified=False: verify_freshness always returns False (freshness block)
      - execute_success=False: execute_item always returns permanent failure
      - transient_fail_times=N: execute_item fails transiently for the first N attempts
        per product, then succeeds
      - permanent_failure=True: execute_item always fails permanently (no retry benefit)

    Idempotency: once a product succeeds, subsequent execute_item calls for that
    product return success=True immediately (simulates idempotent re-attempt).
    """

    def __init__(
        self,
        *,
        freshness_verified: bool = True,
        execute_success: bool = True,
        transient_fail_times: int = 0,
        permanent_failure: bool = False,
    ) -> None:
        self._freshness_ok = freshness_verified
        self._execute_success = execute_success
        self._transient_fail_times = transient_fail_times
        self._permanent_failure = permanent_failure
        self._attempt_counts: dict[str, int] = {}
        self._succeeded_products: dict[str, bool] = {}

    def verify_freshness(self, context: FreshnessContext) -> FreshnessResult:
        if not self._freshness_ok:
            return FreshnessResult(verified=False, reason="Simulated freshness failure")
        return FreshnessResult(verified=True)

    def execute_item(self, context: FreshnessContext) -> ExecuteItemResult:
        product_id = context.product_id

        # Idempotency: already succeeded for this product
        if self._succeeded_products.get(product_id):
            return ExecuteItemResult(success=True, reason="Idempotent retry — already succeeded")

        if self._permanent_failure:
            return ExecuteItemResult(
                success=False, is_transient_failure=False, reason="Simulated permanent failure"
            )

        attempt = self._attempt_counts.get(product_id, 0) + 1
        self._attempt_counts[product_id] = attempt

        if attempt <= self._transient_fail_times:
            return ExecuteItemResult(
                success=False,
                is_transient_failure=True,
                reason=f"Simulated transient failure (attempt {attempt})",
            )

        if not self._execute_success:
            return ExecuteItemResult(
                success=False, is_transient_failure=False, reason="Simulated execution failure"
            )

        self._succeeded_products[product_id] = True
        return ExecuteItemResult(success=True)


# ── Execution Service ──────────────────────────────────────────────────────────


class ExecutionService:
    """Orchestrates controlled execution of a confirmed, immutable Change Set.

    This service does NOT connect to real WooCommerce APIs. All writes go through
    the ChannelExecutionAdapter interface, which in A2.7 is DummyExecutionAdapter only.
    """

    def __init__(self, db: Session) -> None:
        self._db = db
        self._repo = ExecutionRepository(db)

    def execute(
        self,
        *,
        change_set_id: str,
        change_set_revision_id: str,
        change_set_digest: str,
        items: list[ExecutionItemInput],
        destination_channel: str,
        scope: str,
        source_snapshot_id: str,
        dry_run_result: str,
        dry_run_digest_verified: bool,
        confirmation_id: str,
        confirmation_digest: str,
        confirmation_is_valid: bool,
        adapter: ChannelExecutionAdapter,
        idempotency_key: str,
        max_attempts: int = 3,
    ) -> Execution:
        """Execute a confirmed Change Set through the adapter.

        Returns the Execution record. Status will be:
          - BLOCKED: a prerequisite failed or a freshness check failed
          - FAILED:  some items failed (permanent or retry-exhausted)
          - SUCCEEDED: all items executed successfully

        If idempotency_key matches an existing Execution, that Execution is returned
        immediately without creating a new record or re-executing any items.
        """
        # ── 1. Idempotency check ───────────────────────────────────────────
        existing = self._repo.find_by_idempotency_key(idempotency_key)
        if existing is not None:
            return existing

        # ── 2. Create execution in PENDING ─────────────────────────────────
        execution = self._repo.create_execution(
            change_set_id=change_set_id,
            change_set_revision_id=change_set_revision_id,
            change_set_digest=change_set_digest,
            confirmation_id=confirmation_id,
            confirmation_digest=confirmation_digest,
            destination_channel=destination_channel,
            scope=scope,
            source_snapshot_id=source_snapshot_id,
            idempotency_key=idempotency_key,
        )

        # ── 3. Validate prerequisites ──────────────────────────────────────
        block_reason = self._validate_prerequisites(
            change_set_digest=change_set_digest,
            items=items,
            destination_channel=destination_channel,
            scope=scope,
            source_snapshot_id=source_snapshot_id,
            dry_run_result=dry_run_result,
            dry_run_digest_verified=dry_run_digest_verified,
            confirmation_is_valid=confirmation_is_valid,
            confirmation_digest=confirmation_digest,
        )
        if block_reason is not None:
            self._repo.transition_execution(
                execution.id, "BLOCKED", error_message=block_reason
            )
            return self._repo.get_execution(execution.id)  # type: ignore[return-value]

        # ── 4. Transition to RUNNING ───────────────────────────────────────
        self._repo.transition_execution(execution.id, "RUNNING")

        # ── 5. Create batch ────────────────────────────────────────────────
        batch = self._repo.create_batch(execution_id=execution.id, batch_number=1)

        # ── 6. Process items ───────────────────────────────────────────────
        adapter_name = type(adapter).__name__

        for item_input in items:
            item_idempotency_key = f"{idempotency_key}:{item_input.product_id}"
            item = self._repo.create_item(
                execution_id=execution.id,
                batch_id=batch.id,
                idempotency_key=item_idempotency_key,
                product_id=item_input.product_id,
                proposal_id=item_input.proposal_id,
                proposal_hash=item_input.proposal_hash,
                safety_result_id=item_input.safety_result_id,
                rule_version_id=item_input.rule_version_id,
                proposed_price=item_input.proposed_price,
                current_price=item_input.current_price,
            )
            self._repo.transition_item(item.id, "RUNNING")

            freshness_ctx = FreshnessContext(
                product_id=item_input.product_id,
                proposal_id=item_input.proposal_id,
                proposal_hash=item_input.proposal_hash,
                proposed_price=item_input.proposed_price,
                current_price=item_input.current_price,
                destination_channel=destination_channel,
                change_set_digest=change_set_digest,
                confirmation_digest=confirmation_digest,
            )

            # ── Freshness verification (hard block on failure) ─────────────
            freshness_result = adapter.verify_freshness(freshness_ctx)
            if not freshness_result.verified:
                self._repo.record_attempt(
                    execution_item_id=item.id,
                    attempt_number=1,
                    status="BLOCKED",
                    adapter_name=adapter_name,
                    error_message=freshness_result.reason,
                )
                self._repo.transition_item(
                    item.id, "BLOCKED", error_message=freshness_result.reason
                )
                continue

            # Freshness passed — mark the flag directly (item remains RUNNING)
            self._repo.mark_item_freshness_verified(item.id)

            # ── Execute with retry ─────────────────────────────────────────
            item_final_state = "FAILED"
            item_error: Optional[str] = f"Max attempts ({max_attempts}) exhausted"

            for attempt_num in range(1, max_attempts + 1):
                result = adapter.execute_item(freshness_ctx)
                attempt_status = "SUCCEEDED" if result.success else "FAILED"
                self._repo.record_attempt(
                    execution_item_id=item.id,
                    attempt_number=attempt_num,
                    status=attempt_status,
                    adapter_name=adapter_name,
                    error_message=result.reason,
                )
                if result.success:
                    item_final_state = "SUCCEEDED"
                    item_error = None
                    break
                if not result.is_transient_failure:
                    item_final_state = "FAILED"
                    item_error = result.reason
                    break
                # Transient failure — retry

            self._repo.transition_item(item.id, item_final_state, error_message=item_error)

        # ── 7. Determine overall execution final state ─────────────────────
        finished_items = self._repo.list_items(execution.id)
        if any(i.status == "BLOCKED" for i in finished_items):
            final_execution_state = "BLOCKED"
        elif any(i.status == "FAILED" for i in finished_items):
            final_execution_state = "FAILED"
        else:
            final_execution_state = "SUCCEEDED"

        self._repo.update_batch_status(batch.id, final_execution_state)
        self._repo.transition_execution(execution.id, final_execution_state)
        return self._repo.get_execution(execution.id)  # type: ignore[return-value]

    def cancel(self, execution_id: str) -> Execution:
        """Cancel a PENDING or RUNNING execution."""
        self._repo.transition_execution(execution_id, "CANCELLED")
        return self._repo.get_execution(execution_id)  # type: ignore[return-value]

    def get_report(self, execution_id: str) -> ExecutionReport:
        """Build a summary report for the given execution."""
        execution = self._repo.get_execution(execution_id)
        if execution is None:
            raise ValueError(f"Execution not found: {execution_id!r}")
        items = self._repo.list_items(execution_id)
        return ExecutionReport(
            execution_id=execution.id,
            change_set_id=execution.change_set_id,
            change_set_revision_id=execution.change_set_revision_id,
            change_set_digest=execution.change_set_digest,
            confirmation_id=execution.confirmation_id,
            destination_channel=execution.destination_channel,
            status=execution.status,
            idempotency_key=execution.idempotency_key,
            total_items=len(items),
            succeeded_count=sum(1 for i in items if i.status == "SUCCEEDED"),
            failed_count=sum(1 for i in items if i.status == "FAILED"),
            blocked_count=sum(1 for i in items if i.status == "BLOCKED"),
            skipped_count=sum(1 for i in items if i.status == "SKIPPED"),
            error_message=execution.error_message,
            items=items,
        )

    # ── Private helpers ────────────────────────────────────────────────────

    def _validate_prerequisites(
        self,
        *,
        change_set_digest: str,
        items: list[ExecutionItemInput],
        destination_channel: str,
        scope: str,
        source_snapshot_id: str,
        dry_run_result: str,
        dry_run_digest_verified: bool,
        confirmation_is_valid: bool,
        confirmation_digest: str,
    ) -> Optional[str]:
        """Return a block reason string if any prerequisite fails; None if all pass."""

        if not confirmation_is_valid:
            return (
                "SellerConfirmation is invalid — the Change Set may have changed since "
                "confirmation was recorded. A new Dry Run and confirmation are required."
            )

        if confirmation_digest != change_set_digest:
            return (
                f"Confirmation digest mismatch: confirmation was bound to "
                f"{confirmation_digest!r} but current Change Set digest is "
                f"{change_set_digest!r}. A new Dry Run and confirmation are required."
            )

        if dry_run_result == "BLOCK":
            return (
                "Dry Run validation result is BLOCK — execution is not permitted. "
                "Resolve all blocking issues and re-run the Dry Run."
            )

        if not dry_run_digest_verified:
            return (
                "Dry Run did not verify the Change Set digest (digest_verified=False). "
                "The Change Set may have been modified after the Dry Run. "
                "A new Dry Run is required."
            )

        # Independent digest re-verification using A2.5's compute_change_set_digest
        computed = compute_change_set_digest(
            items,  # type: ignore[arg-type]  — duck-type compatible
            destination_channel,
            scope,
            source_snapshot_id,
        )
        if computed != change_set_digest:
            return (
                f"Change Set digest integrity failure: provided digest "
                f"{change_set_digest!r} does not match recomputed digest "
                f"{computed!r}. The item set may have been tampered with."
            )

        return None
