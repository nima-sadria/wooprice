"""Project 7.3B — IRR price validation tests.

Verifies that normal Iranian Rial prices (5M / 50M / 500M IRR) do not trigger
the validation_extremely_high advisory warning, that the threshold is exactly
10 trillion IRR, and that the warning fires correctly above that boundary.

Advisory warning must remain non-blocking when block_enabled=False.
"""
import os
import sys
from types import SimpleNamespace

os.environ.setdefault("NEXTCLOUD_URL", "http://example.invalid")
os.environ.setdefault("NEXTCLOUD_USER", "x")
os.environ.setdefault("NEXTCLOUD_PASSWORD", "x")
os.environ.setdefault("NEXTCLOUD_FILE_PATH", "/x.xlsx")
os.environ.setdefault("WC_URL", "http://example.invalid")
os.environ.setdefault("WC_KEY", "x")
os.environ.setdefault("WC_SECRET", "x")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.validation import PRICE_EXTREMELY_HIGH, ValidationLevel, validate_price  # noqa: E402
from app.main import _compute_dry_run_summary  # noqa: E402


# ── Threshold contract ─────────────────────────────────────────────────────────

def test_threshold_is_exactly_10_trillion_irr():
    """The constant must equal exactly 10,000,000,000,000 (10 trillion IRR)."""
    assert PRICE_EXTREMELY_HIGH == 10_000_000_000_000, (
        f"PRICE_EXTREMELY_HIGH must be 10_000_000_000_000, got {PRICE_EXTREMELY_HIGH}"
    )


# ── Normal IRR prices — no warning expected ────────────────────────────────────

def test_5_million_irr_no_extremely_high_warning():
    """5,000,000 IRR (≈ $4 USD) must not trigger validation_extremely_high."""
    results = validate_price(1, "5000000", None)
    assert not any(r.rule == "extremely_high" for r in results), (
        f"5M IRR must not trigger extremely_high; got rules: {[r.rule for r in results]}"
    )


def test_50_million_irr_no_extremely_high_warning():
    """50,000,000 IRR (≈ $41 USD) must not trigger validation_extremely_high."""
    results = validate_price(1, "50000000", None)
    assert not any(r.rule == "extremely_high" for r in results), (
        f"50M IRR must not trigger extremely_high; got rules: {[r.rule for r in results]}"
    )


def test_500_million_irr_no_extremely_high_warning():
    """500,000,000 IRR (≈ $406 USD) must not trigger validation_extremely_high."""
    results = validate_price(1, "500000000", None)
    assert not any(r.rule == "extremely_high" for r in results), (
        f"500M IRR must not trigger extremely_high; got rules: {[r.rule for r in results]}"
    )


def test_9_billion_irr_no_extremely_high_warning():
    """9,600,000,000 IRR (≈ $7,800 USD high-end product) must not trigger extremely_high."""
    results = validate_price(1, "9600000000", None)
    assert not any(r.rule == "extremely_high" for r in results), (
        f"9.6B IRR must not trigger extremely_high; got rules: {[r.rule for r in results]}"
    )


# ── Boundary tests ─────────────────────────────────────────────────────────────

def test_exactly_10_trillion_irr_no_warning():
    """Exactly 10,000,000,000,000 IRR must NOT trigger extremely_high (boundary is exclusive)."""
    results = validate_price(1, "10000000000000", None)
    assert not any(r.rule == "extremely_high" for r in results), (
        f"Exactly 10T IRR must not trigger extremely_high (> threshold, not >= ); "
        f"got rules: {[r.rule for r in results]}"
    )


def test_just_above_10_trillion_irr_triggers_advisory_warning():
    """10,000,000,000,001 IRR (one unit above threshold) must trigger advisory warning."""
    results = validate_price(1, "10000000000001", None)
    assert any(r.rule == "extremely_high" and r.level == ValidationLevel.warning for r in results), (
        f"10T+1 IRR must trigger extremely_high warning; got rules: {[r.rule for r in results]}"
    )


def test_20_trillion_irr_triggers_advisory_warning():
    """20,000,000,000,000 IRR must trigger the advisory extremely_high warning."""
    results = validate_price(1, "20000000000000", None)
    assert any(r.rule == "extremely_high" and r.level == ValidationLevel.warning for r in results), (
        f"20T IRR must trigger extremely_high; got rules: {[r.rule for r in results]}"
    )


# ── Advisory warning is non-blocking ──────────────────────────────────────────

def test_extremely_high_warning_is_not_critical():
    """The extremely_high rule must fire as WARNING, never CRITICAL."""
    results = validate_price(1, "20000000000000", None)
    levels = {r.level for r in results if r.rule == "extremely_high"}
    assert ValidationLevel.critical not in levels, (
        f"extremely_high must never be critical; got levels: {levels}"
    )
    assert ValidationLevel.warning in levels


def test_dry_run_not_blocked_by_extremely_high_when_block_disabled():
    """Dry run must not be blocked when only the extremely_high warning fires and
    block_enabled=False on the alarm threshold."""
    item = SimpleNamespace(
        product_id=1, product_name="Test", new_price="20000000000000", old_price=None,
        stock_status="instock", change_status="changed", categories=None,
        price_changed=1, stock_changed=0, missing_image=0, missing_cost=0,
    )
    # Alarm thresholds with blocking disabled
    thresholds = {None: {"warning": 20.0, "critical": 150.0, "block_enabled": False}}
    summary = _compute_dry_run_summary([item], alarm_threshold=20.0, category_thresholds=thresholds)
    assert summary["dry_run_status"] != "blocked", (
        f"Dry run must not be blocked when block_enabled=False; got: {summary['dry_run_status']}"
    )


def test_critical_validation_still_blocks_apply():
    """A genuinely invalid (non-numeric) price must still produce a critical finding."""
    results = validate_price(1, "not_a_price", None)
    assert any(r.level == ValidationLevel.critical for r in results), (
        "Non-numeric price must produce a critical finding that blocks apply"
    )


if __name__ == "__main__":
    test_threshold_is_exactly_10_trillion_irr()
    test_5_million_irr_no_extremely_high_warning()
    test_50_million_irr_no_extremely_high_warning()
    test_500_million_irr_no_extremely_high_warning()
    test_9_billion_irr_no_extremely_high_warning()
    test_exactly_10_trillion_irr_no_warning()
    test_just_above_10_trillion_irr_triggers_advisory_warning()
    test_20_trillion_irr_triggers_advisory_warning()
    test_extremely_high_warning_is_not_critical()
    test_dry_run_not_blocked_by_extremely_high_when_block_disabled()
    test_critical_validation_still_blocks_apply()
    print("ALL TESTS PASSED")
