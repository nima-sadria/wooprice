"""A2.9 AI Foundation — AdvisoryService.

Isolation boundary:
- Never triggers execution, scheduling, dry run, confirmation, or any destination write.
- The only output objects produced are AdvisoryInsight records.
- No executable domain objects (PriceProposal, ChangeSet, DryRunResult, Schedule,
  ExecutionPlan, ApplyCommand) are ever produced.
- No external AI API calls in this phase (foundation scaffolding only).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy.orm import Session

from .models import AdvisoryInsight
from .repository import AdvisoryRepository

_MODEL_VERSION = "a2.9-rule-based-v1"

# Thresholds used by rule-based classifiers (no external AI API in this phase)
_ANOMALY_PRICE_CHANGE_HIGH_PCT = 50.0
_STALE_PRICE_HIGH_HOURS = 48
_STALE_PRICE_MEDIUM_HOURS = 24


@dataclass
class AdvisoryContext:
    """Input context for one advisory analysis request."""

    subject_type: str
    subject_id: str
    data: dict[str, Any] = field(default_factory=dict)


class AdvisoryService:
    """Orchestrates advisory insight generation.

    Responsibilities:
    - generate explanations for pricing proposals, rule outcomes, safety results
    - generate risk summaries
    - classify anomalies
    - detect stale prices
    - assign review priorities
    - generate non-binding rule recommendations
    - build AdvisoryInsight objects and persist them

    No execution, no mutation, no writes outside A2 advisory tables.
    """

    def __init__(self, db: Session) -> None:
        self._db = db
        self._repo = AdvisoryRepository(db)

    # ── Public API ─────────────────────────────────────────────────────────────

    def generate_explanation(self, context: AdvisoryContext) -> AdvisoryInsight:
        """Explain a pricing proposal, rule outcome, or safety result."""
        data = context.data
        rule_type = data.get("rule_type", "unknown")
        proposed_price = data.get("proposed_price")
        current_price = data.get("current_price")
        currency = data.get("currency", "USD")

        change_desc = ""
        if proposed_price is not None and current_price is not None:
            try:
                delta = float(proposed_price) - float(current_price)
                pct = (delta / float(current_price) * 100) if float(current_price) != 0 else 0.0
                change_desc = (
                    f" Proposed price {proposed_price} {currency} is a "
                    f"{pct:+.1f}% change from current {current_price} {currency}."
                )
            except (TypeError, ValueError):
                pass

        summary = f"Explanation for {context.subject_type} {context.subject_id}."
        explanation = (
            f"The {rule_type} rule produced this pricing proposal for "
            f"{context.subject_type} {context.subject_id}.{change_desc}"
        )
        trace = f"rule_type={rule_type};subject={context.subject_type}:{context.subject_id}"

        return self._create_insight(
            context=context,
            category="EXPLANATION",
            severity="INFO",
            confidence=0.95,
            summary=summary,
            explanation=explanation,
            evidence=json.dumps({"rule_type": rule_type, "data_keys": list(data.keys())}),
            recommendation_trace=trace,
        )

    def generate_risk_summary(self, context: AdvisoryContext) -> AdvisoryInsight:
        """Summarize risks associated with a Change Set or proposal."""
        data = context.data
        safety_result = data.get("safety_result", "UNKNOWN")
        risk_factors: list[str] = []

        severity = "INFO"
        confidence = 0.80

        if safety_result == "BLOCK":
            risk_factors.append("Safety policy blocked this proposal.")
            severity = "HIGH"
            confidence = 0.99
        elif safety_result == "WARN":
            risk_factors.append("Safety policy issued a warning.")
            severity = "MEDIUM"
            confidence = 0.90

        price_change_pct = data.get("price_change_pct")
        if price_change_pct is not None:
            try:
                pct = float(price_change_pct)
                if abs(pct) > _ANOMALY_PRICE_CHANGE_HIGH_PCT:
                    risk_factors.append(
                        f"Price change of {pct:+.1f}% exceeds {_ANOMALY_PRICE_CHANGE_HIGH_PCT}% threshold."
                    )
                    if severity == "INFO":
                        severity = "MEDIUM"
            except (TypeError, ValueError):
                pass

        if not risk_factors:
            risk_factors.append("No significant risk factors detected.")

        summary = f"Risk summary for {context.subject_type} {context.subject_id}."
        explanation = " ".join(risk_factors)
        trace = f"safety_result={safety_result};subject={context.subject_type}:{context.subject_id}"

        return self._create_insight(
            context=context,
            category="RISK_SUMMARY",
            severity=severity,
            confidence=confidence,
            summary=summary,
            explanation=explanation,
            evidence=json.dumps({"safety_result": safety_result, "risk_factors": risk_factors}),
            recommendation_trace=trace,
        )

    def detect_anomaly(self, context: AdvisoryContext) -> AdvisoryInsight:
        """Detect possible anomalies in pricing proposals."""
        data = context.data
        proposed_price = data.get("proposed_price")
        current_price = data.get("current_price")

        severity = "INFO"
        confidence = 0.70
        anomaly_signals: list[str] = []

        if proposed_price is not None:
            try:
                pp = float(proposed_price)
                if pp <= 0:
                    anomaly_signals.append(
                        f"Proposed price {proposed_price} is zero or negative — likely an error."
                    )
                    severity = "CRITICAL"
                    confidence = 0.99
                elif current_price is not None:
                    cp = float(current_price)
                    if cp != 0:
                        pct = abs((pp - cp) / cp * 100)
                        if pct > _ANOMALY_PRICE_CHANGE_HIGH_PCT:
                            anomaly_signals.append(
                                f"Price change of {pct:.1f}% from {current_price} to "
                                f"{proposed_price} exceeds {_ANOMALY_PRICE_CHANGE_HIGH_PCT}% threshold."
                            )
                            severity = "HIGH"
                            confidence = 0.85
            except (TypeError, ValueError):
                pass

        if not anomaly_signals:
            anomaly_signals.append("No anomaly detected in proposed price.")

        summary = f"Anomaly analysis for {context.subject_type} {context.subject_id}."
        explanation = " ".join(anomaly_signals)
        trace = (
            f"anomaly_check;proposed_price={proposed_price};"
            f"current_price={current_price};"
            f"subject={context.subject_type}:{context.subject_id}"
        )

        return self._create_insight(
            context=context,
            category="ANOMALY",
            severity=severity,
            confidence=confidence,
            summary=summary,
            explanation=explanation,
            evidence=json.dumps(
                {
                    "proposed_price": str(proposed_price) if proposed_price is not None else None,
                    "current_price": str(current_price) if current_price is not None else None,
                    "signals": anomaly_signals,
                }
            ),
            recommendation_trace=trace,
        )

    def detect_stale_price(self, context: AdvisoryContext) -> AdvisoryInsight:
        """Highlight stale prices relative to source data age."""
        data = context.data
        source_age_hours = data.get("source_age_hours")

        severity = "INFO"
        confidence = 0.75
        staleness_desc = "Source data freshness is within acceptable range."

        if source_age_hours is not None:
            try:
                age = float(source_age_hours)
                if age > _STALE_PRICE_HIGH_HOURS:
                    staleness_desc = (
                        f"Source data is {age:.1f} hours old — exceeds "
                        f"{_STALE_PRICE_HIGH_HOURS}h threshold. Price may be stale."
                    )
                    severity = "HIGH"
                    confidence = 0.90
                elif age > _STALE_PRICE_MEDIUM_HOURS:
                    staleness_desc = (
                        f"Source data is {age:.1f} hours old — exceeds "
                        f"{_STALE_PRICE_MEDIUM_HOURS}h threshold. Review recommended."
                    )
                    severity = "MEDIUM"
                    confidence = 0.80
            except (TypeError, ValueError):
                pass

        summary = f"Stale price check for {context.subject_type} {context.subject_id}."
        trace = (
            f"stale_check;source_age_hours={source_age_hours};"
            f"subject={context.subject_type}:{context.subject_id}"
        )

        return self._create_insight(
            context=context,
            category="STALE_PRICE",
            severity=severity,
            confidence=confidence,
            summary=summary,
            explanation=staleness_desc,
            evidence=json.dumps({"source_age_hours": source_age_hours}),
            recommendation_trace=trace,
        )

    def assign_review_priority(self, context: AdvisoryContext) -> AdvisoryInsight:
        """Assign a human review priority score to a proposal or Change Set."""
        data = context.data
        safety_result = data.get("safety_result", "PASS")
        price_change_pct = data.get("price_change_pct", 0.0)
        has_anomaly = data.get("has_anomaly", False)

        score = 0
        reasons: list[str] = []

        if safety_result == "BLOCK":
            score += 40
            reasons.append("Safety policy blocked.")
        elif safety_result == "WARN":
            score += 20
            reasons.append("Safety policy warning.")

        try:
            pct = abs(float(price_change_pct))
            if pct > 50:
                score += 30
                reasons.append(f"Price change {pct:.1f}% exceeds 50%.")
            elif pct > 20:
                score += 15
                reasons.append(f"Price change {pct:.1f}% exceeds 20%.")
        except (TypeError, ValueError):
            pass

        if has_anomaly:
            score += 20
            reasons.append("Anomaly detected.")

        if score >= 50:
            severity = "HIGH"
            confidence = 0.92
            priority_label = "HIGH"
        elif score >= 20:
            severity = "MEDIUM"
            confidence = 0.85
            priority_label = "MEDIUM"
        else:
            severity = "INFO"
            confidence = 0.80
            priority_label = "LOW"

        summary = (
            f"Review priority {priority_label} (score={score}) for "
            f"{context.subject_type} {context.subject_id}."
        )
        explanation = (
            f"Priority score {score}/100: {'; '.join(reasons) if reasons else 'no significant factors'}."
        )
        trace = (
            f"priority_score={score};priority={priority_label};"
            f"subject={context.subject_type}:{context.subject_id}"
        )

        return self._create_insight(
            context=context,
            category="REVIEW_PRIORITY",
            severity=severity,
            confidence=confidence,
            summary=summary,
            explanation=explanation,
            evidence=json.dumps({"score": score, "reasons": reasons}),
            recommendation_trace=trace,
        )

    def generate_rule_recommendation(self, context: AdvisoryContext) -> AdvisoryInsight:
        """Generate a non-binding rule recommendation for Owner review.

        The recommendation is advisory only. It cannot create, modify, or publish
        any rule. Rule publication requires the standard Owner-approval workflow
        via A2.3 (Transformation Rule Engine).
        """
        data = context.data
        pattern_description = data.get("pattern_description", "unspecified pattern")
        suggested_rule_type = data.get("suggested_rule_type", "formula")

        summary = (
            f"Non-binding rule recommendation for {context.subject_type} "
            f"{context.subject_id}."
        )
        explanation = (
            f"Advisory suggestion: a {suggested_rule_type} rule may be applicable "
            f"based on observed pattern: {pattern_description}. "
            f"This recommendation is non-binding. Owner must explicitly authorize "
            f"and publish any rule via the A2.3 Rule Engine workflow."
        )
        trace = (
            f"rule_recommendation;suggested_type={suggested_rule_type};"
            f"subject={context.subject_type}:{context.subject_id}"
        )

        return self._create_insight(
            context=context,
            category="RULE_RECOMMENDATION",
            severity="LOW",
            confidence=0.65,
            summary=summary,
            explanation=explanation,
            evidence=json.dumps(
                {
                    "suggested_rule_type": suggested_rule_type,
                    "pattern_description": pattern_description,
                    "non_binding": True,
                    "requires_owner_approval": True,
                }
            ),
            recommendation_trace=trace,
        )

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _create_insight(
        self,
        *,
        context: AdvisoryContext,
        category: str,
        severity: str,
        confidence: float,
        summary: str,
        explanation: str,
        evidence: str,
        recommendation_trace: Optional[str] = None,
    ) -> AdvisoryInsight:
        session = self._repo.create_session(
            category=category,
            subject_type=context.subject_type,
            subject_id=context.subject_id,
            model_version=_MODEL_VERSION,
        )
        return self._repo.store_insight(
            session_id=session.id,
            category=category,
            severity=severity,
            confidence=confidence,
            summary=summary,
            explanation=explanation,
            evidence=evidence,
            related_object_type=context.subject_type,
            related_object_id=context.subject_id,
            recommendation_trace=recommendation_trace,
        )
