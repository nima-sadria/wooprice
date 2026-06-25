"""A2.3 Formula Engine — deterministic, reproducible price calculation.

Primary model: Cost + Profit → Proposed Sell Price
  proposed_price = cost × (1 + profit_margin_pct / 100)

Future-ready: competitor_reference is declared but not evaluated here.
Collection of competitor prices requires Owner approval of a dedicated adapter.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, field_validator

_ROUNDING_MAP = {
    "round_half_up": ROUND_HALF_UP,
    "ceil": ROUND_CEILING,
    "floor": ROUND_FLOOR,
}


class CostPlusProfitParameters(BaseModel):
    """Immutable parameters for the Cost + Profit formula.

    Stored as JSON in RuleVersion.parameters_json.
    Validated on deserialisation — invalid parameters cannot produce a proposal.
    """

    profit_margin_pct: float
    currency: str
    rounding_mode: Literal["round_half_up", "ceil", "floor"] = "round_half_up"
    decimal_places: int = 0

    @field_validator("profit_margin_pct")
    @classmethod
    def _margin_range(cls, v: float) -> float:
        if v < -100 or v > 10_000:
            raise ValueError("profit_margin_pct must be between -100 and 10000")
        return v

    @field_validator("decimal_places")
    @classmethod
    def _dp_range(cls, v: int) -> int:
        if v < 0 or v > 6:
            raise ValueError("decimal_places must be between 0 and 6")
        return v


@dataclass(frozen=True)
class TraceStep:
    step_name: str
    step_input_json: str
    step_output_json: str
    step_formula: str


@dataclass(frozen=True)
class FormulaResult:
    proposed_price: Decimal
    currency: str
    trace: list[TraceStep] = field(default_factory=list)


def _quantize(value: Decimal, rounding_mode: str, decimal_places: int) -> Decimal:
    quantize_to = Decimal(10) ** -decimal_places
    return value.quantize(quantize_to, rounding=_ROUNDING_MAP[rounding_mode])


class CostPlusProfitFormula:
    """Evaluates proposed_price = cost × (1 + profit_margin_pct / 100) deterministically.

    All arithmetic is done with Decimal to avoid floating-point drift.
    The same parameters + cost always produce the same proposed_price.
    """

    def __init__(self, parameters: CostPlusProfitParameters) -> None:
        self._p = parameters

    def evaluate(self, cost: Decimal) -> FormulaResult:
        if cost <= Decimal("0"):
            raise ValueError(f"cost must be positive; got {cost!r}")

        margin = Decimal(str(self._p.profit_margin_pct))
        factor = Decimal("1") + margin / Decimal("100")
        raw = cost * factor
        proposed = _quantize(raw, self._p.rounding_mode, self._p.decimal_places)

        trace = [
            TraceStep(
                step_name="margin_factor",
                step_input_json=json.dumps({"profit_margin_pct": self._p.profit_margin_pct}),
                step_output_json=json.dumps({"factor": str(factor)}),
                step_formula=f"factor = 1 + {self._p.profit_margin_pct} / 100",
            ),
            TraceStep(
                step_name="raw_price",
                step_input_json=json.dumps({"cost": str(cost), "factor": str(factor)}),
                step_output_json=json.dumps({"raw": str(raw)}),
                step_formula="raw = cost × factor",
            ),
            TraceStep(
                step_name="rounding",
                step_input_json=json.dumps(
                    {"raw": str(raw), "mode": self._p.rounding_mode, "decimal_places": self._p.decimal_places}
                ),
                step_output_json=json.dumps({"proposed_price": str(proposed)}),
                step_formula=f"proposed = round(raw, dp={self._p.decimal_places}, mode={self._p.rounding_mode})",
            ),
        ]

        return FormulaResult(proposed_price=proposed, currency=self._p.currency, trace=trace)
