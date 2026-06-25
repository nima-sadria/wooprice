"""A2.3 Rule Engine — evaluates published RuleVersions against source inputs.

Outputs: PriceProposal (NOT a Final Applied Price).
Never writes to WooCommerce or any external destination.
Never bypasses Safety Policy Engine (A2.4), Change Set Engine (A2.5),
Dry Run Engine (A2.6), or Execution Engine (A2.7).

Determinism guarantee:
  Identical (rule_version_id, cost, currency) → identical computation_digest
  → identical PriceProposal. The engine returns the existing proposal when a
  matching digest is already stored.

Reproducibility guarantee:
  Given stored (rule_version_id, source_snapshot_id, ProposalProvenance.input_fields_json),
  any proposal can be re-derived from stored provenance at any future time.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from ..models.proposal import ExecutionTraceEntry, PriceProposal, ProposalProvenance
from ..repositories.proposal_repository import ProposalRepository
from ..repositories.rule_repository import RuleRepository
from .formula import CostPlusProfitFormula, CostPlusProfitParameters


@dataclass
class RuleInput:
    """Input to the Rule Engine for a single product row."""

    cost: Decimal
    currency: str
    source_row_ref: str
    source_snapshot_id: str
    input_fields: dict


@dataclass
class RuleEvaluationResult:
    """Output of a single rule evaluation."""

    proposal: PriceProposal
    proposal_id: str
    was_cached: bool


def _compute_digest(rule_version_id: str, cost: Decimal, currency: str, parameters_json: str) -> str:
    """Deterministic SHA-256 over all inputs. Identical inputs → identical digest."""
    payload = json.dumps(
        {
            "rule_version_id": rule_version_id,
            "input_cost": str(cost),
            "currency": currency,
            "parameters_json": parameters_json,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


class RuleEngine:
    """
    Evaluates a published RuleVersion against a RuleInput.

    Scope boundary (A2.3 only):
    - Reads rules and writes proposals to the A2 PostgreSQL store.
    - Does NOT call WooCommerce, Nextcloud, or any external system.
    - Does NOT perform Safety Policy evaluation (A2.4).
    - Does NOT create Change Sets (A2.5).
    - Does NOT perform Dry Runs (A2.6).
    - Does NOT execute/apply prices (A2.7).
    """

    def __init__(self, db: Session) -> None:
        self._db = db
        self._rule_repo = RuleRepository(db)
        self._proposal_repo = ProposalRepository(db)

    def evaluate(self, rule_version_id: str, rule_input: RuleInput) -> RuleEvaluationResult:
        """Evaluate a published rule version against the given input.

        Returns the existing proposal when the same inputs have been evaluated
        before (determinism guarantee). Otherwise creates and persists a new proposal.

        Raises:
            ValueError: if rule_version_id does not correspond to a published version.
            ValueError: if cost is zero or negative.
            NotImplementedError: if rule_type is not yet fully implemented (competitor_reference).
        """
        version = self._rule_repo.get_published_version(rule_version_id)
        if version is None:
            raise ValueError(
                f"RuleVersion '{rule_version_id}' not found or not published. "
                "Only published versions may be used for evaluation."
            )

        digest = _compute_digest(
            rule_version_id=rule_version_id,
            cost=rule_input.cost,
            currency=rule_input.currency,
            parameters_json=version.parameters_json,
        )

        existing = self._proposal_repo.find_by_digest(digest)
        if existing is not None:
            return RuleEvaluationResult(
                proposal=existing,
                proposal_id=existing.id,
                was_cached=True,
            )

        formula_result = self._dispatch(version, rule_input)

        now = datetime.now(tz=timezone.utc)
        proposal = PriceProposal(
            id=str(uuid.uuid4()),
            rule_version_id=rule_version_id,
            source_snapshot_id=rule_input.source_snapshot_id,
            input_cost=float(rule_input.cost),
            proposed_price=float(formula_result.proposed_price),
            currency=formula_result.currency,
            computation_digest=digest,
            created_at=now,
        )
        self._db.add(proposal)
        self._db.flush()

        provenance = ProposalProvenance(
            proposal_id=proposal.id,
            source_row_ref=rule_input.source_row_ref,
            input_fields_json=json.dumps(rule_input.input_fields, sort_keys=True, default=str),
        )
        self._db.add(provenance)

        for i, step in enumerate(formula_result.trace):
            entry = ExecutionTraceEntry(
                proposal_id=proposal.id,
                step_order=i,
                step_name=step.step_name,
                step_input_json=step.step_input_json,
                step_output_json=step.step_output_json,
                step_formula=step.step_formula,
            )
            self._db.add(entry)

        self._db.flush()
        return RuleEvaluationResult(
            proposal=proposal,
            proposal_id=proposal.id,
            was_cached=False,
        )

    def _dispatch(self, version, rule_input: RuleInput):
        rule_type = version.rule.rule_type
        if rule_type == "cost_plus_profit":
            params = CostPlusProfitParameters.model_validate_json(version.parameters_json)
            return CostPlusProfitFormula(params).evaluate(rule_input.cost)
        elif rule_type == "competitor_reference":
            raise NotImplementedError(
                "competitor_reference is future-ready input support in A2.3. "
                "The collection mechanism requires explicit Owner approval of a dedicated source adapter."
            )
        else:
            raise ValueError(f"Unknown rule_type: {rule_type!r}")
