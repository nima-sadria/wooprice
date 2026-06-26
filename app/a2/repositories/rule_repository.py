"""
A2.3-R2 RuleRepository — create, retrieve, and version pricing rules.

publish_version() enforces immutability: once a version is published,
it cannot be republished. set_current_version() switches the active
version among already-published versions only.

Caller is responsible for committing the session.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from ..models.pricing_rule import PricingRule
from ..models.pricing_rule_version import PricingRuleVersion
from ..rules.base import RuleDefinition, RuleType


class RuleRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    # ── Rule CRUD ─────────────────────────────────────────────────────────────

    def create_rule(
        self,
        *,
        rule_name: str,
        rule_type: str,
        priority: int,
    ) -> PricingRule:
        if rule_type not in RuleType.values():
            raise ValueError(
                f"Unknown rule_type '{rule_type}'. Allowed: {RuleType.values()}"
            )
        now = datetime.now(tz=timezone.utc)
        rule = PricingRule(
            rule_id=str(uuid.uuid4()),
            rule_name=rule_name,
            rule_type=rule_type,
            priority=priority,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        self._db.add(rule)
        self._db.flush()
        return rule

    def get_rule(self, rule_id: str) -> Optional[PricingRule]:
        return self._db.get(PricingRule, rule_id)

    def list_active_rules(self) -> list[PricingRule]:
        return (
            self._db.query(PricingRule)
            .filter(PricingRule.is_active.is_(True))
            .order_by(PricingRule.priority)
            .all()
        )

    def deactivate_rule(self, rule_id: str) -> bool:
        rule = self._db.get(PricingRule, rule_id)
        if rule is None:
            return False
        rule.is_active = False
        rule.updated_at = datetime.now(tz=timezone.utc)
        self._db.flush()
        return True

    # ── Version management ────────────────────────────────────────────────────

    def create_version(
        self,
        *,
        rule_id: str,
        formula: str,
        required_inputs: list[str],
    ) -> PricingRuleVersion:
        existing = self.list_versions(rule_id)
        next_number = max((v.version_number for v in existing), default=0) + 1

        version = PricingRuleVersion(
            version_id=str(uuid.uuid4()),
            rule_id=rule_id,
            version_number=next_number,
            formula=formula,
            required_inputs_json=json.dumps(sorted(required_inputs)),
            is_published=False,
            published_at=None,
            is_current=False,
            created_at=datetime.now(tz=timezone.utc),
        )
        self._db.add(version)
        self._db.flush()
        return version

    def publish_version(self, version_id: str) -> PricingRuleVersion:
        """
        Publish a draft version, making it immutable and setting it as current.

        Raises ValueError if the version does not exist or is already published.
        Once published, a version's formula and required_inputs cannot change;
        create a new version instead.
        """
        version = self._db.get(PricingRuleVersion, version_id)
        if version is None:
            raise ValueError(f"PricingRuleVersion not found: {version_id}")
        if version.is_published:
            raise ValueError(
                f"PricingRuleVersion {version_id} (v{version.version_number}) "
                "is already published. Create a new version to change parameters."
            )
        version.is_published = True
        version.published_at = datetime.now(tz=timezone.utc)

        # Set as current, clearing is_current on siblings
        siblings = (
            self._db.query(PricingRuleVersion)
            .filter(PricingRuleVersion.rule_id == version.rule_id)
            .all()
        )
        for sibling in siblings:
            sibling.is_current = sibling.version_id == version_id
        self._db.flush()
        return version

    def set_current_version(self, version_id: str) -> bool:
        """
        Switch the active version to version_id.

        Only published versions may be made current.
        Returns False if the version does not exist or is not published.
        """
        target = self._db.get(PricingRuleVersion, version_id)
        if target is None or not target.is_published:
            return False

        siblings = (
            self._db.query(PricingRuleVersion)
            .filter(PricingRuleVersion.rule_id == target.rule_id)
            .all()
        )
        for sibling in siblings:
            sibling.is_current = sibling.version_id == version_id
        self._db.flush()
        return True

    def get_current_version(self, rule_id: str) -> Optional[PricingRuleVersion]:
        return (
            self._db.query(PricingRuleVersion)
            .filter(
                PricingRuleVersion.rule_id == rule_id,
                PricingRuleVersion.is_current.is_(True),
            )
            .first()
        )

    def get_version(self, version_id: str) -> Optional[PricingRuleVersion]:
        return self._db.get(PricingRuleVersion, version_id)

    def list_versions(self, rule_id: str) -> list[PricingRuleVersion]:
        return (
            self._db.query(PricingRuleVersion)
            .filter(PricingRuleVersion.rule_id == rule_id)
            .order_by(PricingRuleVersion.version_number)
            .all()
        )

    # ── Convenience: load active rules as RuleDefinition objects ─────────────

    def load_active_definitions(self) -> list[RuleDefinition]:
        """Return RuleDefinition for every active rule that has a current published version."""
        rules = self.list_active_rules()
        definitions: list[RuleDefinition] = []
        for rule in rules:
            version = self.get_current_version(rule.rule_id)
            if version is None or not version.is_published:
                continue
            required_inputs = json.loads(version.required_inputs_json or "[]")
            definitions.append(
                RuleDefinition(
                    rule_id=rule.rule_id,
                    rule_name=rule.rule_name,
                    rule_type=rule.rule_type,
                    priority=rule.priority,
                    version_id=version.version_id,
                    version_number=version.version_number,
                    formula=version.formula,
                    required_inputs=required_inputs,
                )
            )
        return definitions
