"""A2.3 Rule Repository — rule definition and version persistence.

Published versions are immutable: publish_version() enforces this by
raising ValueError when called on an already-published version.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session, joinedload

from ..models.rule import RuleDefinition, RuleVersion


class RuleRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    # ── Rule Definitions ────────────────────────────────────────────────────

    def create_definition(
        self,
        *,
        rule_type: str,
        display_name: str,
        priority: int = 100,
    ) -> RuleDefinition:
        now = datetime.now(tz=timezone.utc)
        defn = RuleDefinition(
            id=str(uuid.uuid4()),
            rule_type=rule_type,
            display_name=display_name,
            priority=priority,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        self._db.add(defn)
        self._db.flush()
        return defn

    def get_definition(self, rule_id: str) -> Optional[RuleDefinition]:
        return self._db.get(RuleDefinition, rule_id)

    def get_active_rules_by_priority(self) -> list[RuleDefinition]:
        """Return all active rules ordered by priority descending (highest first)."""
        return (
            self._db.query(RuleDefinition)
            .filter(RuleDefinition.is_active.is_(True))
            .order_by(RuleDefinition.priority.desc())
            .all()
        )

    # ── Rule Versions ────────────────────────────────────────────────────────

    def create_version(self, rule_id: str, parameters_json: str) -> RuleVersion:
        """Create a new draft version. version_number auto-increments within the rule."""
        existing = (
            self._db.query(RuleVersion)
            .filter(RuleVersion.rule_id == rule_id)
            .order_by(RuleVersion.version_number.desc())
            .first()
        )
        next_number = (existing.version_number + 1) if existing else 1
        now = datetime.now(tz=timezone.utc)
        version = RuleVersion(
            id=str(uuid.uuid4()),
            rule_id=rule_id,
            version_number=next_number,
            parameters_json=parameters_json,
            is_published=False,
            published_at=None,
            created_at=now,
        )
        self._db.add(version)
        self._db.flush()
        return version

    def publish_version(self, version_id: str) -> RuleVersion:
        """Publish a draft version. Raises ValueError if already published."""
        version = self._db.get(RuleVersion, version_id)
        if version is None:
            raise ValueError(f"RuleVersion not found: {version_id}")
        if version.is_published:
            raise ValueError(
                f"RuleVersion {version_id} (v{version.version_number}) is already published. "
                "Create a new version to change parameters."
            )
        version.is_published = True
        version.published_at = datetime.now(tz=timezone.utc)
        self._db.flush()
        return version

    def get_published_version(self, version_id: str) -> Optional[RuleVersion]:
        """Return a published version with its rule loaded, or None."""
        return (
            self._db.query(RuleVersion)
            .options(joinedload(RuleVersion.rule))
            .filter(
                RuleVersion.id == version_id,
                RuleVersion.is_published.is_(True),
            )
            .first()
        )

    def get_latest_published_version(self, rule_id: str) -> Optional[RuleVersion]:
        """Return the highest version_number published version for a rule."""
        return (
            self._db.query(RuleVersion)
            .filter(
                RuleVersion.rule_id == rule_id,
                RuleVersion.is_published.is_(True),
            )
            .order_by(RuleVersion.version_number.desc())
            .first()
        )

    def list_versions(self, rule_id: str) -> list[RuleVersion]:
        return (
            self._db.query(RuleVersion)
            .filter(RuleVersion.rule_id == rule_id)
            .order_by(RuleVersion.version_number)
            .all()
        )
