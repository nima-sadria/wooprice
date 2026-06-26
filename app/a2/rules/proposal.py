"""
A2.3 PriceProposal — immutable output of the rule engine.

proposal_hash is a deterministic SHA-256 of proposal content fields.
It explicitly EXCLUDES proposal_id (UUID) and generated_at (timestamp)
so that identical logical inputs always produce the same hash regardless
of when or how many times the engine is called. This enables deduplication
and reproducibility verification.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel


class PriceProposal(BaseModel):
    """Immutable price proposal produced by the Rule Engine."""

    model_config = {"frozen": True}

    proposal_id: str
    canonical_product_id: str
    proposed_price: Decimal
    currency: str
    generated_at: datetime
    rule_id: str
    rule_version: int
    rule_version_id: str
    source_id: str
    snapshot_id: str
    input_values: dict[str, str]
    proposal_hash: str


def compute_proposal_hash(
    *,
    canonical_product_id: str,
    rule_id: str,
    rule_version_id: str,
    rule_version: int,
    proposed_price: Decimal,
    currency: str,
    input_values: dict[str, Any],
) -> str:
    """
    Compute a deterministic SHA-256 hash of a proposal's logical content.

    Deliberately excludes proposal_id (UUID) and generated_at (timestamp)
    so that the same inputs always produce the same hash — enabling
    deduplication and reproducibility verification across calls and time.
    """
    payload: dict[str, Any] = {
        "canonical_product_id": canonical_product_id,
        "rule_id": rule_id,
        "rule_version_id": rule_version_id,
        "rule_version": rule_version,
        "proposed_price": str(proposed_price),
        "currency": currency,
        "input_values": {k: str(v) for k, v in sorted(input_values.items())},
    }
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode()).hexdigest()
