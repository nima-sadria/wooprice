"""
A2.3 rule engine base types.

RuleDefinition is the runtime representation of a versioned pricing rule.
It is source-agnostic: the same type covers rules loaded from the database
and rules constructed directly in tests.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class RuleType(str, Enum):
    COST_PLUS = "cost_plus"
    FX_BASED = "fx_based"
    FEE_BASED = "fee_based"
    FORMULA = "formula"
    COMPETITION = "competition"

    @classmethod
    def values(cls) -> list[str]:
        return [m.value for m in cls]


# Canonical set of required inputs per rule type.
# The engine uses these to skip rules whose inputs are not all present.
RULE_TYPE_REQUIRED_INPUTS: dict[str, list[str]] = {
    RuleType.COST_PLUS.value:   ["cost"],
    RuleType.FX_BASED.value:    ["cost", "fx_rate"],
    RuleType.FEE_BASED.value:   ["cost", "fee"],
    RuleType.FORMULA.value:     [],   # formula-specific; populated from formula itself
    RuleType.COMPETITION.value: ["competitor_price"],
}


@dataclass(frozen=True)
class RuleDefinition:
    """
    Runtime representation of a single versioned pricing rule.

    Produced by RuleRepository.to_definition() or constructed directly.
    Immutable so the engine can cache and reuse without defensive copying.
    """

    rule_id: str
    rule_name: str
    rule_type: str
    priority: int
    version_id: str
    version_number: int
    formula: str
    required_inputs: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.rule_type not in RuleType.values():
            raise ValueError(
                f"Unknown rule_type '{self.rule_type}'. "
                f"Allowed: {RuleType.values()}"
            )
