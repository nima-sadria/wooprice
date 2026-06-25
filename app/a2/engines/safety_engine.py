"""A2.4 Safety Policy Engine — read-only evaluation gate.

Evaluates Price Proposals against configurable safety policies.
Produces structured SafetyResult records; never creates Change Sets,
modifies prices, or writes to any destination.

Scope boundary (A2.4 only):
- Does NOT call A2.5 (Change Set Engine) or any later phase.
- Does NOT call WooCommerce, Nextcloud, or any external system.
- Does NOT apply, execute, or approve prices.

Default installation policy mode: WARN (non-blocking).
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from ..models.safety import OverrideLog, PolicyVersion, SafetyResult
from ..repositories.safety_repository import SafetyRepository


@dataclass
class EvaluationContext:
    """Input to the Safety Policy Engine for a single proposal evaluation."""

    proposal_id: str
    input_cost: Decimal
    proposed_price: Decimal
    currency: str
    category: Optional[str] = None
    brand: Optional[str] = None
    user_id: Optional[str] = None
    channel_id: Optional[str] = None


@dataclass
class EvaluationReport:
    """Aggregate output of evaluating a proposal against all active policies."""

    proposal_id: str
    results: list[SafetyResult] = field(default_factory=list)

    @property
    def is_blocked(self) -> bool:
        return any(r.outcome == "BLOCK" for r in self.results)

    @property
    def requires_override(self) -> bool:
        return any(r.outcome == "REQUIRE_OVERRIDE" for r in self.results)

    @property
    def has_warnings(self) -> bool:
        return any(r.outcome == "WARN" for r in self.results)

    @property
    def all_pass(self) -> bool:
        return all(r.outcome == "PASS" for r in self.results)


class SafetyEngine:
    """
    Evaluates a PriceProposal against a list of published PolicyVersions.

    The engine is stateless with respect to pricing decisions:
    - It never modifies a proposal.
    - It never creates a Change Set.
    - It never calls external systems.
    - Override decisions require explicit caller action via record_override().
    """

    def __init__(self, db: Session) -> None:
        self._db = db
        self._repo = SafetyRepository(db)

    def evaluate(
        self,
        context: EvaluationContext,
        policy_versions: list[PolicyVersion],
    ) -> EvaluationReport:
        """Evaluate context against all provided policy versions.

        Returns an EvaluationReport containing one SafetyResult per version.
        All results are persisted to the A2 store before returning.
        """
        now = datetime.now(tz=timezone.utc)
        results: list[SafetyResult] = []

        for version in policy_versions:
            result = self._evaluate_one(context, version, now)
            self._db.add(result)
            results.append(result)

        self._db.flush()
        return EvaluationReport(proposal_id=context.proposal_id, results=results)

    def record_override(
        self,
        safety_result_id: str,
        authorizing_user: str,
        justification: str,
    ) -> OverrideLog:
        """Record an authorized override for a REQUIRE_OVERRIDE safety result.

        Raises ValueError if the result does not exist or is not REQUIRE_OVERRIDE.
        """
        result = self._db.get(SafetyResult, safety_result_id)
        if result is None:
            raise ValueError(f"SafetyResult not found: {safety_result_id}")
        if result.outcome != "REQUIRE_OVERRIDE":
            raise ValueError(
                f"SafetyResult {safety_result_id} has outcome {result.outcome!r}. "
                "Only REQUIRE_OVERRIDE results may be overridden."
            )
        log = OverrideLog(
            safety_result_id=safety_result_id,
            authorizing_user=authorizing_user,
            justification=justification,
            created_at=datetime.now(tz=timezone.utc),
        )
        self._db.add(log)
        self._db.flush()
        return log

    # ── Internal evaluation dispatch ─────────────────────────────────────────

    def _evaluate_one(
        self,
        context: EvaluationContext,
        version: PolicyVersion,
        now: datetime,
    ) -> SafetyResult:
        policy_type = version.policy.policy_type

        if policy_type == "percentage_change":
            triggered, threshold_str, value_str = self._eval_percentage_change(context, version)
        elif policy_type == "missing_zero":
            triggered, threshold_str, value_str = self._eval_missing_zero(context, version)
        elif policy_type == "extra_zero":
            triggered, threshold_str, value_str = self._eval_extra_zero(context, version)
        elif policy_type == "historical_anomaly":
            triggered, threshold_str, value_str = self._eval_historical_anomaly(context, version)
        else:
            raise ValueError(f"Unknown policy_type: {policy_type!r}")

        outcome = version.mode if triggered else "PASS"

        return SafetyResult(
            id=str(uuid.uuid4()),
            proposal_id=context.proposal_id,
            policy_version_id=version.id,
            policy_name=version.policy.display_name,
            policy_mode=version.mode,
            outcome=outcome,
            triggered_threshold=threshold_str if triggered else None,
            evaluated_value=value_str,
            created_at=now,
        )

    def _eval_percentage_change(
        self,
        context: EvaluationContext,
        version: PolicyVersion,
    ) -> tuple[bool, Optional[str], str]:
        """Evaluate margin = (proposed - cost) / cost × 100 against configured bounds."""
        params = json.loads(version.parameters_json)
        cost = context.input_cost
        proposed = context.proposed_price

        if cost == Decimal("0"):
            return False, None, "margin_pct=N/A"

        margin_pct = (proposed - cost) / cost * Decimal("100")
        value_str = f"margin_pct={margin_pct:.4f}"

        min_margin = params.get("min_margin_pct")
        max_margin = params.get("max_margin_pct")

        if min_margin is not None and margin_pct < Decimal(str(min_margin)):
            return True, f"min_margin_pct={min_margin}", value_str
        if max_margin is not None and margin_pct > Decimal(str(max_margin)):
            return True, f"max_margin_pct={max_margin}", value_str

        return False, None, value_str

    def _eval_missing_zero(
        self,
        context: EvaluationContext,
        version: PolicyVersion,
    ) -> tuple[bool, Optional[str], str]:
        """Detect proposed price suspiciously low (possible dropped zero)."""
        params = json.loads(version.parameters_json)
        cost = context.input_cost
        proposed = context.proposed_price

        if cost == Decimal("0"):
            return False, None, f"proposed={proposed}"

        min_ratio = Decimal(str(params["min_price_to_cost_ratio"]))
        actual_ratio = proposed / cost
        value_str = f"price_to_cost_ratio={actual_ratio:.4f}"

        if actual_ratio < min_ratio:
            return True, f"min_price_to_cost_ratio={min_ratio}", value_str
        return False, None, value_str

    def _eval_extra_zero(
        self,
        context: EvaluationContext,
        version: PolicyVersion,
    ) -> tuple[bool, Optional[str], str]:
        """Detect proposed price suspiciously high (possible extra zero)."""
        params = json.loads(version.parameters_json)
        cost = context.input_cost
        proposed = context.proposed_price

        if cost == Decimal("0"):
            return False, None, f"proposed={proposed}"

        max_ratio = Decimal(str(params["max_price_to_cost_ratio"]))
        actual_ratio = proposed / cost
        value_str = f"price_to_cost_ratio={actual_ratio:.4f}"

        if actual_ratio > max_ratio:
            return True, f"max_price_to_cost_ratio={max_ratio}", value_str
        return False, None, value_str

    def _eval_historical_anomaly(
        self,
        context: EvaluationContext,
        version: PolicyVersion,
    ) -> tuple[bool, Optional[str], str]:
        """Detect deviation from a stored reference price beyond a configured threshold."""
        params = json.loads(version.parameters_json)
        proposed = context.proposed_price
        reference = Decimal(str(params["reference_price"]))
        max_deviation = Decimal(str(params["max_deviation_pct"]))

        if reference == Decimal("0"):
            return False, None, f"proposed={proposed}"

        deviation_pct = abs(proposed - reference) / reference * Decimal("100")
        value_str = f"deviation_pct={deviation_pct:.4f}"

        if deviation_pct > max_deviation:
            return True, f"max_deviation_pct={max_deviation}", value_str
        return False, None, value_str
