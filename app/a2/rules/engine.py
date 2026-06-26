"""
A2.3 Rule Engine — deterministic transformation of inputs into price proposals.

Responsibilities:
  - Sort rules by priority (ascending = highest priority first).
  - Skip rules whose required inputs are not all present in input_values.
  - Evaluate the first applicable rule's formula via the sandboxed AST evaluator.
  - Produce an immutable PriceProposal with a deterministic proposal_hash.
  - Record execution trace steps for audit and reproducibility.

Boundary: consumes rule definitions and input values only; produces proposals only.
No network calls. No external API calls. No randomness.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

from .base import RuleDefinition
from .formula import evaluate_formula
from .proposal import PriceProposal, compute_proposal_hash

logger = logging.getLogger(__name__)


class NoApplicableRuleError(Exception):
    """Raised when no rule can be applied to the given inputs."""


@dataclass(frozen=True)
class TraceStep:
    """Single step in a rule evaluation execution trace."""
    step_order: int
    step_name: str
    step_input_json: str
    step_output_json: str
    step_formula: str


@dataclass(frozen=True)
class ProposalEnvelope:
    """
    Output of RuleEngine.propose().

    Contains the immutable PriceProposal and the execution trace steps
    that document how the price was derived. Callers pass this to
    ProposalRepository.save() to persist both.
    """
    proposal: PriceProposal
    trace: list[TraceStep] = field(default_factory=list)


class RuleEngine:
    """
    Stateless, deterministic pricing rule engine.

    Usage::

        engine = RuleEngine()
        envelope = engine.propose(
            rules=[rule_def],
            canonical_product_id="prod-uuid",
            source_id="src-001",
            snapshot_id="snap-uuid",
            input_values={"cost": Decimal("100000")},
            currency="IDR",
        )
        proposal = envelope.proposal
        trace    = envelope.trace
    """

    def propose(
        self,
        *,
        rules: list[RuleDefinition],
        canonical_product_id: str,
        source_id: str,
        snapshot_id: str,
        input_values: dict[str, Decimal],
        currency: str,
        generated_at: datetime | None = None,
    ) -> ProposalEnvelope:
        """
        Apply the highest-priority applicable rule to produce a ProposalEnvelope.

        Rules are evaluated in ascending priority order (lower number = higher
        priority). A rule is applicable when all of its required_inputs are
        present in input_values. The first applicable rule wins.

        Args:
            rules:                 List of RuleDefinition objects to evaluate.
            canonical_product_id:  Stable product identity.
            source_id:             Source that provided the input data.
            snapshot_id:           Snapshot the input data came from.
            input_values:          Variable bindings for formula evaluation.
            currency:              ISO currency code for the proposed price.
            generated_at:          Override timestamp (for deterministic tests).

        Returns:
            ProposalEnvelope containing PriceProposal and execution trace.

        Raises:
            NoApplicableRuleError: No rule matches the provided inputs.
            ValueError:            A formula evaluation error occurred.
        """
        if not rules:
            raise NoApplicableRuleError(
                f"No rules provided for product '{canonical_product_id}'."
            )

        sorted_rules = sorted(rules, key=lambda r: (r.priority, r.rule_id))
        ts = generated_at if generated_at is not None else datetime.now(tz=timezone.utc)

        for rule in sorted_rules:
            missing = [k for k in rule.required_inputs if k not in input_values]
            if missing:
                logger.debug(
                    "Skipping rule '%s' (priority=%d): missing inputs %s",
                    rule.rule_id, rule.priority, missing,
                )
                continue

            return self._build_envelope(
                rule=rule,
                canonical_product_id=canonical_product_id,
                source_id=source_id,
                snapshot_id=snapshot_id,
                input_values=input_values,
                currency=currency,
                ts=ts,
            )

        raise NoApplicableRuleError(
            f"No applicable rule found for product '{canonical_product_id}'. "
            f"Evaluated {len(sorted_rules)} rule(s). "
            f"Available inputs: {sorted(input_values.keys())}."
        )

    def propose_all(
        self,
        *,
        rules: list[RuleDefinition],
        canonical_product_id: str,
        source_id: str,
        snapshot_id: str,
        input_values: dict[str, Decimal],
        currency: str,
        generated_at: datetime | None = None,
    ) -> list[ProposalEnvelope]:
        """
        Evaluate ALL applicable rules and return one ProposalEnvelope per applicable rule.

        Envelopes are ordered from highest to lowest priority.
        Useful for auditing or comparing competing rule outcomes.
        """
        sorted_rules = sorted(rules, key=lambda r: (r.priority, r.rule_id))
        ts = generated_at if generated_at is not None else datetime.now(tz=timezone.utc)
        envelopes: list[ProposalEnvelope] = []

        for rule in sorted_rules:
            missing = [k for k in rule.required_inputs if k not in input_values]
            if missing:
                continue

            envelopes.append(self._build_envelope(
                rule=rule,
                canonical_product_id=canonical_product_id,
                source_id=source_id,
                snapshot_id=snapshot_id,
                input_values=input_values,
                currency=currency,
                ts=ts,
            ))

        return envelopes

    # ── Internal ────────────────────────────────────────────────────────────────

    def _build_envelope(
        self,
        *,
        rule: RuleDefinition,
        canonical_product_id: str,
        source_id: str,
        snapshot_id: str,
        input_values: dict[str, Decimal],
        currency: str,
        ts: datetime,
    ) -> ProposalEnvelope:
        input_values_str = {k: str(v) for k, v in input_values.items()}

        # Step 1: capture inputs
        step1 = TraceStep(
            step_order=1,
            step_name="input_capture",
            step_input_json=json.dumps({"input_keys": sorted(input_values.keys())}),
            step_output_json=json.dumps(input_values_str),
            step_formula="(captured from caller)",
        )

        # Step 2: evaluate formula
        proposed_price = evaluate_formula(rule.formula, input_values)
        step2 = TraceStep(
            step_order=2,
            step_name="formula_evaluation",
            step_input_json=json.dumps(input_values_str),
            step_output_json=json.dumps({"proposed_price": str(proposed_price)}),
            step_formula=rule.formula,
        )

        # Step 3: compute deterministic hash
        proposal_hash = compute_proposal_hash(
            canonical_product_id=canonical_product_id,
            rule_id=rule.rule_id,
            rule_version_id=rule.version_id,
            rule_version=rule.version_number,
            proposed_price=proposed_price,
            currency=currency,
            input_values=input_values,
        )
        step3 = TraceStep(
            step_order=3,
            step_name="hash_computation",
            step_input_json=json.dumps({
                "canonical_product_id": canonical_product_id,
                "rule_id": rule.rule_id,
                "rule_version_id": rule.version_id,
                "rule_version": rule.version_number,
                "currency": currency,
            }),
            step_output_json=json.dumps({"proposal_hash": proposal_hash}),
            step_formula="SHA256(canonical_product_id, rule_id, rule_version_id, rule_version, proposed_price, currency, input_values)",
        )

        logger.info(
            "RuleEngine: proposal generated rule_id=%s version=%d "
            "product=%s price=%s %s",
            rule.rule_id, rule.version_number,
            canonical_product_id, proposed_price, currency,
        )

        proposal = PriceProposal(
            proposal_id=str(uuid4()),
            canonical_product_id=canonical_product_id,
            proposed_price=proposed_price,
            currency=currency,
            generated_at=ts,
            rule_id=rule.rule_id,
            rule_version=rule.version_number,
            rule_version_id=rule.version_id,
            source_id=source_id,
            snapshot_id=snapshot_id,
            input_values=input_values_str,
            proposal_hash=proposal_hash,
        )

        return ProposalEnvelope(proposal=proposal, trace=[step1, step2, step3])
