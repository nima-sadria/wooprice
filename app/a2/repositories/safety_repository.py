"""A2.4 Safety Repository — policy definition, version, and result persistence."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session, joinedload

from ..models.safety import OverrideLog, PolicyVersion, SafetyPolicy, SafetyResult


class SafetyRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    # ── SafetyPolicy ──────────────────────────────────────────────────────────

    def create_policy(
        self,
        *,
        policy_type: str,
        display_name: str,
        scope_type: str = "global",
        scope_value: Optional[str] = None,
    ) -> SafetyPolicy:
        now = datetime.now(tz=timezone.utc)
        policy = SafetyPolicy(
            id=str(uuid.uuid4()),
            policy_type=policy_type,
            display_name=display_name,
            scope_type=scope_type,
            scope_value=scope_value,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        self._db.add(policy)
        self._db.flush()
        return policy

    def get_policy(self, policy_id: str) -> Optional[SafetyPolicy]:
        return self._db.get(SafetyPolicy, policy_id)

    def list_active_policies(self) -> list[SafetyPolicy]:
        return (
            self._db.query(SafetyPolicy)
            .filter(SafetyPolicy.is_active.is_(True))
            .all()
        )

    # ── PolicyVersion ─────────────────────────────────────────────────────────

    def create_version(
        self,
        policy_id: str,
        parameters_json: str,
        mode: str = "WARN",
    ) -> PolicyVersion:
        existing = (
            self._db.query(PolicyVersion)
            .filter(PolicyVersion.policy_id == policy_id)
            .order_by(PolicyVersion.version_number.desc())
            .first()
        )
        next_number = (existing.version_number + 1) if existing else 1
        now = datetime.now(tz=timezone.utc)
        version = PolicyVersion(
            id=str(uuid.uuid4()),
            policy_id=policy_id,
            version_number=next_number,
            mode=mode,
            parameters_json=parameters_json,
            is_published=False,
            published_at=None,
            created_at=now,
        )
        self._db.add(version)
        self._db.flush()
        return version

    def publish_version(self, version_id: str) -> PolicyVersion:
        version = self._db.get(PolicyVersion, version_id)
        if version is None:
            raise ValueError(f"PolicyVersion not found: {version_id}")
        if version.is_published:
            raise ValueError(
                f"PolicyVersion {version_id} (v{version.version_number}) is already published. "
                "Create a new version to change thresholds."
            )
        version.is_published = True
        version.published_at = datetime.now(tz=timezone.utc)
        self._db.flush()
        return version

    def get_published_version(self, version_id: str) -> Optional[PolicyVersion]:
        return (
            self._db.query(PolicyVersion)
            .options(joinedload(PolicyVersion.policy))
            .filter(
                PolicyVersion.id == version_id,
                PolicyVersion.is_published.is_(True),
            )
            .first()
        )

    def get_active_published_versions(self) -> list[PolicyVersion]:
        """Return all published versions for active policies, with policy eagerly loaded."""
        return (
            self._db.query(PolicyVersion)
            .join(PolicyVersion.policy)
            .options(joinedload(PolicyVersion.policy))
            .filter(
                PolicyVersion.is_published.is_(True),
                SafetyPolicy.is_active.is_(True),
            )
            .all()
        )

    def get_published_versions_for_scope(
        self,
        scope_type: str,
        scope_value: Optional[str] = None,
    ) -> list[PolicyVersion]:
        """Return published versions for active policies matching scope_type and scope_value."""
        q = (
            self._db.query(PolicyVersion)
            .join(PolicyVersion.policy)
            .options(joinedload(PolicyVersion.policy))
            .filter(
                PolicyVersion.is_published.is_(True),
                SafetyPolicy.is_active.is_(True),
                SafetyPolicy.scope_type == scope_type,
            )
        )
        if scope_value is not None:
            q = q.filter(SafetyPolicy.scope_value == scope_value)
        return q.all()

    def list_versions(self, policy_id: str) -> list[PolicyVersion]:
        return (
            self._db.query(PolicyVersion)
            .filter(PolicyVersion.policy_id == policy_id)
            .order_by(PolicyVersion.version_number)
            .all()
        )

    # ── SafetyResult ──────────────────────────────────────────────────────────

    def get_result(self, result_id: str) -> Optional[SafetyResult]:
        return (
            self._db.query(SafetyResult)
            .options(joinedload(SafetyResult.override_log))
            .filter(SafetyResult.id == result_id)
            .first()
        )

    def list_results_for_proposal(self, proposal_id: str) -> list[SafetyResult]:
        return (
            self._db.query(SafetyResult)
            .filter(SafetyResult.proposal_id == proposal_id)
            .all()
        )

    def proposal_is_blocked(self, proposal_id: str) -> bool:
        """True if any SafetyResult for this proposal has outcome BLOCK."""
        return (
            self._db.query(SafetyResult)
            .filter(
                SafetyResult.proposal_id == proposal_id,
                SafetyResult.outcome == "BLOCK",
            )
            .first()
        ) is not None

    def proposal_requires_override(self, proposal_id: str) -> bool:
        """True if any REQUIRE_OVERRIDE result for this proposal has no override log entry."""
        results = (
            self._db.query(SafetyResult)
            .options(joinedload(SafetyResult.override_log))
            .filter(
                SafetyResult.proposal_id == proposal_id,
                SafetyResult.outcome == "REQUIRE_OVERRIDE",
            )
            .all()
        )
        return any(not r.override_log for r in results)
