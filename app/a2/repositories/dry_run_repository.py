"""A2.6 Dry Run Repository — persistence for DryRun, DryRunResult, SellerConfirmation."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from ..models.dry_run import DryRun, DryRunResult, SellerConfirmation


class ConfirmationNotFoundError(Exception):
    """Raised when a requested SellerConfirmation does not exist."""


class DryRunRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    # ── DryRun ────────────────────────────────────────────────────────────────

    def create(
        self,
        *,
        change_set_id: str,
        change_set_revision_id: str,
        change_set_digest: str,
        digest_verified: bool,
        validation_result: str,
        execution_eligible: bool,
        proposal_count: int,
        blocked_count: int,
        warning_count: int,
        summary: str,
    ) -> DryRun:
        dry_run = DryRun(
            id=str(uuid.uuid4()),
            change_set_id=change_set_id,
            change_set_revision_id=change_set_revision_id,
            change_set_digest=change_set_digest,
            digest_verified=digest_verified,
            validation_result=validation_result,
            execution_eligible=execution_eligible,
            proposal_count=proposal_count,
            blocked_count=blocked_count,
            warning_count=warning_count,
            summary=summary,
            created_at=datetime.now(tz=timezone.utc),
        )
        self._db.add(dry_run)
        self._db.flush()
        return dry_run

    def get(self, dry_run_id: str) -> Optional[DryRun]:
        return self._db.get(DryRun, dry_run_id)

    def list(self, change_set_id: Optional[str] = None) -> list[DryRun]:
        q = self._db.query(DryRun)
        if change_set_id is not None:
            q = q.filter(DryRun.change_set_id == change_set_id)
        return q.order_by(DryRun.created_at.desc()).all()

    # ── DryRunResult ─────────────────────────────────────────────────────────

    def add_result(
        self,
        *,
        dry_run_id: str,
        product_id: str,
        proposal_id: str,
        proposal_hash: str,
        outcome: str,
        reason: Optional[str] = None,
    ) -> DryRunResult:
        result = DryRunResult(
            dry_run_id=dry_run_id,
            product_id=product_id,
            proposal_id=proposal_id,
            proposal_hash=proposal_hash,
            outcome=outcome,
            reason=reason,
            created_at=datetime.now(tz=timezone.utc),
        )
        self._db.add(result)
        self._db.flush()
        return result

    def list_results(self, dry_run_id: str) -> list[DryRunResult]:
        return (
            self._db.query(DryRunResult)
            .filter(DryRunResult.dry_run_id == dry_run_id)
            .order_by(DryRunResult.id)
            .all()
        )

    # ── SellerConfirmation ───────────────────────────────────────────────────

    def record_confirmation(
        self,
        *,
        dry_run_id: str,
        change_set_digest: str,
        confirmed_by: str,
    ) -> SellerConfirmation:
        conf = SellerConfirmation(
            id=str(uuid.uuid4()),
            dry_run_id=dry_run_id,
            change_set_digest=change_set_digest,
            confirmed_by=confirmed_by,
            is_valid=True,
            invalidated_at=None,
            invalidation_reason=None,
            created_at=datetime.now(tz=timezone.utc),
        )
        self._db.add(conf)
        self._db.flush()
        return conf

    def invalidate_confirmation(
        self,
        confirmation_id: str,
        reason: str,
    ) -> SellerConfirmation:
        conf = self._db.get(SellerConfirmation, confirmation_id)
        if conf is None:
            raise ConfirmationNotFoundError(
                f"SellerConfirmation not found: {confirmation_id!r}"
            )
        conf.is_valid = False
        conf.invalidated_at = datetime.now(tz=timezone.utc)
        conf.invalidation_reason = reason
        self._db.flush()
        return conf

    def latest_confirmation(self, dry_run_id: str) -> Optional[SellerConfirmation]:
        return (
            self._db.query(SellerConfirmation)
            .filter(SellerConfirmation.dry_run_id == dry_run_id)
            .order_by(SellerConfirmation.created_at.desc())
            .first()
        )
