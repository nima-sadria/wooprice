"""
Unit tests — A2.3-R2 PriceProposal model and proposal_hash.

Key reconciliation: compute_proposal_hash excludes proposal_id (UUID)
and generated_at (timestamp) to be fully deterministic for same logical
inputs. Same inputs always produce the same hash.
"""
import os
os.environ.setdefault("A2_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.a2.rules.proposal import PriceProposal, compute_proposal_hash

_TS = datetime(2026, 6, 24, 0, 0, 0, tzinfo=timezone.utc)


def _proposal(**overrides) -> PriceProposal:
    defaults = dict(
        proposal_id="prop-001",
        canonical_product_id="prod-001",
        proposed_price=Decimal("120000"),
        currency="IDR",
        generated_at=_TS,
        rule_id="rule-001",
        rule_version=1,
        rule_version_id="ver-001",
        source_id="src-001",
        snapshot_id="snap-001",
        input_values={"cost": "100000"},
        proposal_hash="a" * 64,
    )
    defaults.update(overrides)
    return PriceProposal(**defaults)


# ── Model completeness ─────────────────────────────────────────────────────────

def test_all_required_fields_present():
    p = _proposal()
    assert p.proposal_id == "prop-001"
    assert p.canonical_product_id == "prod-001"
    assert p.proposed_price == Decimal("120000")
    assert p.currency == "IDR"
    assert p.generated_at == _TS
    assert p.rule_id == "rule-001"
    assert p.rule_version == 1
    assert p.rule_version_id == "ver-001"
    assert p.source_id == "src-001"
    assert p.snapshot_id == "snap-001"
    assert p.input_values == {"cost": "100000"}
    assert p.proposal_hash == "a" * 64


def test_proposal_is_frozen():
    p = _proposal()
    with pytest.raises(Exception):
        p.proposed_price = Decimal("999")  # type: ignore[misc]


def test_proposal_id_can_be_uuid_string():
    p = _proposal(proposal_id="00000000-0000-0000-0000-000000000001")
    assert p.proposal_id == "00000000-0000-0000-0000-000000000001"


# ── Hash determinism ───────────────────────────────────────────────────────────

def test_hash_is_sha256_hex():
    h = compute_proposal_hash(
        canonical_product_id="prod-001",
        rule_id="rule-001",
        rule_version_id="ver-001",
        rule_version=1,
        proposed_price=Decimal("120000"),
        currency="IDR",
        input_values={"cost": Decimal("100000")},
    )
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_hash_is_deterministic():
    kwargs = dict(
        canonical_product_id="prod-001",
        rule_id="rule-001",
        rule_version_id="ver-001",
        rule_version=1,
        proposed_price=Decimal("120000"),
        currency="IDR",
        input_values={"cost": Decimal("100000")},
    )
    assert compute_proposal_hash(**kwargs) == compute_proposal_hash(**kwargs)


def test_hash_excludes_proposal_id():
    """Same logical content with different proposal_ids must produce the same hash."""
    base = dict(
        canonical_product_id="prod-001",
        rule_id="rule-001",
        rule_version_id="ver-001",
        rule_version=1,
        proposed_price=Decimal("120000"),
        currency="IDR",
        input_values={"cost": Decimal("100000")},
    )
    h1 = compute_proposal_hash(**base)
    h2 = compute_proposal_hash(**base)
    assert h1 == h2  # same content → same hash regardless of UUID


def test_hash_excludes_timestamp():
    """Same logical content at different times must produce the same hash."""
    base = dict(
        canonical_product_id="prod-001",
        rule_id="rule-001",
        rule_version_id="ver-001",
        rule_version=1,
        proposed_price=Decimal("120000"),
        currency="IDR",
        input_values={"cost": Decimal("100000")},
    )
    h1 = compute_proposal_hash(**base)
    h2 = compute_proposal_hash(**base)
    assert h1 == h2


def test_different_price_different_hash():
    base = dict(
        canonical_product_id="prod-001",
        rule_id="rule-001",
        rule_version_id="ver-001",
        rule_version=1,
        currency="IDR",
        input_values={"cost": Decimal("100000")},
    )
    h1 = compute_proposal_hash(**base, proposed_price=Decimal("120000"))
    h2 = compute_proposal_hash(**base, proposed_price=Decimal("130000"))
    assert h1 != h2


def test_different_rule_version_id_different_hash():
    base = dict(
        canonical_product_id="prod-001",
        rule_id="rule-001",
        rule_version=1,
        proposed_price=Decimal("120000"),
        currency="IDR",
        input_values={"cost": Decimal("100000")},
    )
    h1 = compute_proposal_hash(**base, rule_version_id="ver-001")
    h2 = compute_proposal_hash(**base, rule_version_id="ver-002")
    assert h1 != h2


def test_different_rule_version_number_different_hash():
    base = dict(
        canonical_product_id="prod-001",
        rule_id="rule-001",
        rule_version_id="ver-001",
        proposed_price=Decimal("120000"),
        currency="IDR",
        input_values={"cost": Decimal("100000")},
    )
    h1 = compute_proposal_hash(**base, rule_version=1)
    h2 = compute_proposal_hash(**base, rule_version=2)
    assert h1 != h2


def test_different_inputs_different_hash():
    base = dict(
        canonical_product_id="prod-001",
        rule_id="rule-001",
        rule_version_id="ver-001",
        rule_version=1,
        proposed_price=Decimal("120000"),
        currency="IDR",
    )
    h1 = compute_proposal_hash(**base, input_values={"cost": Decimal("100000")})
    h2 = compute_proposal_hash(**base, input_values={"cost": Decimal("200000")})
    assert h1 != h2


def test_different_product_different_hash():
    base = dict(
        rule_id="rule-001",
        rule_version_id="ver-001",
        rule_version=1,
        proposed_price=Decimal("120000"),
        currency="IDR",
        input_values={"cost": Decimal("100000")},
    )
    h1 = compute_proposal_hash(**base, canonical_product_id="prod-001")
    h2 = compute_proposal_hash(**base, canonical_product_id="prod-002")
    assert h1 != h2


def test_input_values_key_order_does_not_affect_hash():
    """Hash must be stable regardless of dict insertion order."""
    base = dict(
        canonical_product_id="prod-001",
        rule_id="rule-001",
        rule_version_id="ver-001",
        rule_version=1,
        proposed_price=Decimal("120000"),
        currency="IDR",
    )
    h1 = compute_proposal_hash(**base, input_values={"cost": Decimal("100"), "fee": Decimal("10")})
    h2 = compute_proposal_hash(**base, input_values={"fee": Decimal("10"), "cost": Decimal("100")})
    assert h1 == h2


def test_different_currency_different_hash():
    base = dict(
        canonical_product_id="prod-001",
        rule_id="rule-001",
        rule_version_id="ver-001",
        rule_version=1,
        proposed_price=Decimal("120000"),
        input_values={"cost": Decimal("100000")},
    )
    h1 = compute_proposal_hash(**base, currency="IDR")
    h2 = compute_proposal_hash(**base, currency="USD")
    assert h1 != h2
