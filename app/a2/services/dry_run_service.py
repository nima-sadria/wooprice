"""A2.6 Dry Run Engine Service — validates an immutable Change Set without writing.

The Dry Run Engine is completely read-only with respect to destination systems.
It consumes a Change Set, verifies the digest, validates each item, and produces
an advisory DryRunReport. It never writes to WooCommerce or any external channel.

Scope boundary (A2.6 only):
- Does NOT call A2.7 (Execution Engine) or any later phase.
- Does NOT call WooCommerce, Apply, or any external system.
- Does NOT execute or apply prices.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.a2.services.change_set_service import compute_change_set_digest
from ..models.dry_run import DryRun, SellerConfirmation
from ..repositories.dry_run_repository import ConfirmationNotFoundError, DryRunRepository


@dataclass
class DryRunItemInput:
    """Input record for one product within the Change Set being dry-run.

    Mirrors the fields of ChangeSetItemInput (A2.5) so that
    compute_change_set_digest can be called with DryRunItemInput objects
    via duck typing — both types expose the same attribute names.
    """

    product_id: str
    proposal_id: str
    proposal_hash: str
    safety_result_id: str
    rule_version_id: str
    proposed_price: Decimal
    current_price: Optional[Decimal] = None


@dataclass
class DryRunReport:
    """Advisory report produced by a DryRun execution.

    This report is informational only. It does not trigger execution.
    execution_eligible is advisory — the Execution Engine (A2.7) must perform
    its own independent digest verification before applying any changes.
    """

    dry_run_id: str
    change_set_id: str
    change_set_revision_id: str
    change_set_digest: str
    proposal_count: int
    blocked_count: int
    warning_count: int
    validation_result: str
    digest_verified: bool
    confirmation_status: str
    execution_eligible: bool
    summary: str
    results: list = field(default_factory=list)


def _worst_outcome(outcomes: list[str]) -> str:
    """Return the most severe outcome from a list of PASS / WARN / BLOCK values."""
    if "BLOCK" in outcomes:
        return "BLOCK"
    if "WARN" in outcomes:
        return "WARN"
    return "PASS"


class DryRunService:
    """Executes dry runs against an immutable Change Set.

    Responsibilities:
    - Verify the stored Change Set digest against the provided items.
    - Validate each item for completeness, consistency, and proposal integrity.
    - Produce an advisory DryRunReport. No destination writes occur.
    - Manage SellerConfirmation lifecycle: bind to digest, invalidate on change.
    """

    def __init__(self, db: Session) -> None:
        self._db = db
        self._repo = DryRunRepository(db)

    def execute(
        self,
        *,
        change_set_id: str,
        change_set_revision_id: str,
        stored_digest: str,
        items: list[DryRunItemInput],
        destination_channel: str,
        scope: str,
        source_snapshot_id: str,
    ) -> DryRun:
        """Execute a dry run against the given Change Set revision.

        Verifies the digest, validates all items, and persists the results.
        Returns the DryRun record. Advisory only — does not trigger execution.

        Raises ValueError if items is empty.
        """
        if not items:
            raise ValueError("A Dry Run must contain at least one item.")

        # Digest verification: recompute from items and compare with stored digest.
        # DryRunItemInput is duck-type compatible with ChangeSetItemInput.
        computed = compute_change_set_digest(
            items,  # type: ignore[arg-type]
            destination_channel,
            scope,
            source_snapshot_id,
        )
        digest_verified = computed == stored_digest

        # Destination readiness check
        destination_ok = bool(destination_channel)

        # Item-level validation
        item_results = self._validate_items(items)
        item_outcomes = [r[3] for r in item_results]

        # Overall result: worst item outcome; destination/digest failures force BLOCK
        validation_result = _worst_outcome(item_outcomes) if item_outcomes else "PASS"
        if not destination_ok or not digest_verified:
            validation_result = "BLOCK"

        blocked_count = sum(1 for o in item_outcomes if o == "BLOCK")
        if not destination_ok:
            blocked_count += 1
        warning_count = sum(1 for o in item_outcomes if o == "WARN")

        execution_eligible = validation_result in ("PASS", "WARN") and digest_verified

        summary = self._build_summary(
            validation_result=validation_result,
            digest_verified=digest_verified,
            proposal_count=len(items),
            blocked_count=blocked_count,
            warning_count=warning_count,
            destination_ok=destination_ok,
        )

        dry_run = self._repo.create(
            change_set_id=change_set_id,
            change_set_revision_id=change_set_revision_id,
            change_set_digest=stored_digest,
            digest_verified=digest_verified,
            validation_result=validation_result,
            execution_eligible=execution_eligible,
            proposal_count=len(items),
            blocked_count=blocked_count,
            warning_count=warning_count,
            summary=summary,
        )

        for product_id, proposal_id, proposal_hash, outcome, reason in item_results:
            self._repo.add_result(
                dry_run_id=dry_run.id,
                product_id=product_id,
                proposal_id=proposal_id,
                proposal_hash=proposal_hash,
                outcome=outcome,
                reason=reason,
            )

        return dry_run

    def generate_report(self, dry_run_id: str) -> DryRunReport:
        """Generate an advisory DryRunReport from a persisted DryRun.

        Raises ValueError if dry_run_id is not found.
        """
        dry_run = self._repo.get(dry_run_id)
        if dry_run is None:
            raise ValueError(f"DryRun not found: {dry_run_id!r}")

        results = self._repo.list_results(dry_run_id)
        conf = self._repo.latest_confirmation(dry_run_id)

        if conf is None:
            confirmation_status = "NONE"
        elif conf.is_valid:
            confirmation_status = "CONFIRMED"
        else:
            confirmation_status = "INVALID"

        return DryRunReport(
            dry_run_id=dry_run.id,
            change_set_id=dry_run.change_set_id,
            change_set_revision_id=dry_run.change_set_revision_id,
            change_set_digest=dry_run.change_set_digest,
            proposal_count=dry_run.proposal_count,
            blocked_count=dry_run.blocked_count,
            warning_count=dry_run.warning_count,
            validation_result=dry_run.validation_result,
            digest_verified=dry_run.digest_verified,
            confirmation_status=confirmation_status,
            execution_eligible=dry_run.execution_eligible,
            summary=dry_run.summary,
            results=results,
        )

    def confirm(self, dry_run_id: str, confirmed_by: str) -> SellerConfirmation:
        """Record a seller confirmation bound to the DryRun's Change Set digest.

        Raises ValueError if dry_run_id is not found.
        """
        dry_run = self._repo.get(dry_run_id)
        if dry_run is None:
            raise ValueError(f"DryRun not found: {dry_run_id!r}")
        return self._repo.record_confirmation(
            dry_run_id=dry_run_id,
            change_set_digest=dry_run.change_set_digest,
            confirmed_by=confirmed_by,
        )

    def invalidate_confirmation(
        self, confirmation_id: str, reason: str
    ) -> SellerConfirmation:
        """Explicitly invalidate a SellerConfirmation with the given reason.

        Raises ConfirmationNotFoundError if the confirmation is not found.
        """
        return self._repo.invalidate_confirmation(confirmation_id, reason)

    def invalidate_if_digest_changed(
        self,
        confirmation_id: str,
        current_digest: str,
    ) -> Optional[SellerConfirmation]:
        """Invalidate a confirmation when the current Change Set digest has changed.

        Returns the invalidated SellerConfirmation if invalidation occurred, or
        None if the digests match (no action taken).

        This covers all invalidation scenarios from the A2.6 architecture spec:
        any change to source snapshot, proposal digest, rule version, safety
        result, destination channel, scope, or the Change Set digest directly
        produces a different digest, so a single comparison covers all cases.

        Raises ConfirmationNotFoundError if the confirmation is not found.
        """
        conf = self._db.get(SellerConfirmation, confirmation_id)
        if conf is None:
            raise ConfirmationNotFoundError(
                f"SellerConfirmation not found: {confirmation_id!r}"
            )
        if conf.change_set_digest == current_digest:
            return None
        return self._repo.invalidate_confirmation(
            confirmation_id,
            reason=(
                f"Change Set digest mismatch: confirmation was bound to digest "
                f"{conf.change_set_digest!r} but the current revision has digest "
                f"{current_digest!r}."
            ),
        )

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _validate_items(
        self, items: list[DryRunItemInput]
    ) -> list[tuple]:
        """Validate items. Return (product_id, proposal_id, proposal_hash, outcome, reason) per item."""
        seen: set[str] = set()
        results = []
        for item in items:
            if not item.proposal_hash:
                outcome = "BLOCK"
                reason = "Proposal hash is missing — proposal integrity cannot be verified"
            elif not item.safety_result_id:
                outcome = "WARN"
                reason = "Safety result is not bound — safety evaluation cannot be confirmed"
            elif not item.rule_version_id:
                outcome = "WARN"
                reason = "Rule version is not bound — rule provenance cannot be confirmed"
            elif item.product_id in seen:
                outcome = "WARN"
                reason = (
                    f"Duplicate product ID {item.product_id!r} "
                    "— consistency check failed"
                )
            else:
                outcome = "PASS"
                reason = None
            seen.add(item.product_id)
            results.append(
                (item.product_id, item.proposal_id, item.proposal_hash, outcome, reason)
            )
        return results

    def _build_summary(
        self,
        *,
        validation_result: str,
        digest_verified: bool,
        proposal_count: int,
        blocked_count: int,
        warning_count: int,
        destination_ok: bool,
    ) -> str:
        parts = [f"Validated {proposal_count} proposal(s)."]
        if not destination_ok:
            parts.append("DESTINATION MISSING: destination_channel is empty.")
        if not digest_verified:
            parts.append(
                "DIGEST MISMATCH: stored digest does not match recomputed digest."
            )
        if blocked_count > 0:
            parts.append(f"{blocked_count} item(s) BLOCKED.")
        if warning_count > 0:
            parts.append(f"{warning_count} item(s) with warnings.")
        if validation_result == "PASS":
            parts.append("All validations passed. Execution eligible.")
        elif validation_result == "WARN":
            parts.append("Validation passed with warnings. Execution eligible.")
        else:
            parts.append("Validation failed. Not execution eligible.")
        return " ".join(parts)
