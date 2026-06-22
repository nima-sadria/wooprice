"""Tests for the configurable price-change alarm thresholds (warning + opt-in
blocking critical threshold), and for demoting the old hardcoded
PRICE_EXTREMELY_HIGH check from a blocker to an advisory warning.

Root cause this addresses: Dry Run was unconditionally blocking on
`validation_extremely_high` because app/validation.py treated any price over
999999 as a `critical` finding regardless of currency scale (Rial/Toman
catalogs routinely exceed this). The fix demotes that check to `warning` and
introduces a separate, opt-in, percentage-based critical threshold
(AlarmThreshold.critical_threshold_percent + block_enabled) that admins
control explicitly via /api/alarm-settings, resolved per-item with
category-specific overrides falling back to the global row.

Run directly (no pytest dependency):
    python tests/test_alarm_thresholds.py
"""
import json
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

from app.main import _compute_dry_run_summary, _resolve_alarm_threshold  # noqa: E402
from app.validation import ValidationLevel, validate_price  # noqa: E402


def make_item(**kw):
    defaults = dict(
        product_id=1, product_name="Test", new_price="", old_price=None,
        stock_status="instock", change_status=None, categories=None,
        price_changed=0, stock_changed=0, missing_image=0, missing_cost=0,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def test_extremely_high_price_is_warning_not_critical():
    # Price above 9,999,999,999,999 — genuinely unreachable for Rial/Toman catalogs in normal use.
    results = validate_price(1, "20000000000000", None)
    levels = {r.level for r in results}
    assert ValidationLevel.critical not in levels, results
    assert any(r.rule == "extremely_high" and r.level == ValidationLevel.warning for r in results), results
    print("test_extremely_high_price_is_warning_not_critical: PASS")


def test_rial_price_below_threshold_is_clean():
    """Typical high-end Iranian product price must not trigger extremely_high warning."""
    # ~$8,000 item at USD/IRR ≈ 1,200,000 → 9,600,000,000 IRR, well below new 9.99T threshold
    results = validate_price(1, "9600000000", None)
    assert not any(r.rule == "extremely_high" for r in results), (
        f"A typical 9.6B IRR price must not trigger extremely_high, got: {[r.rule for r in results]}"
    )


def test_resolve_alarm_threshold_global_fallback():
    item = make_item(categories=None)
    thresholds = {None: {"warning": 20.0, "critical": 150.0, "block_enabled": True}}
    thr = _resolve_alarm_threshold(item, 20.0, thresholds)
    assert thr["critical"] == 150.0 and thr["block_enabled"] is True
    print("test_resolve_alarm_threshold_global_fallback: PASS")


def test_resolve_alarm_threshold_category_override():
    item = make_item(categories=json.dumps([{"id": 5, "name": "Electronics"}]))
    thresholds = {
        None: {"warning": 20.0, "critical": 150.0, "block_enabled": True},
        5: {"warning": 50.0, "critical": 80.0, "block_enabled": True},
    }
    thr = _resolve_alarm_threshold(item, 20.0, thresholds)
    assert thr["warning"] == 50.0 and thr["critical"] == 80.0
    print("test_resolve_alarm_threshold_category_override: PASS")


def test_resolve_alarm_threshold_legacy_call_no_category_dict():
    item = make_item(categories=None)
    thr = _resolve_alarm_threshold(item, float("inf"), None)
    assert thr["warning"] == float("inf") and thr["critical"] is None and thr["block_enabled"] is False
    print("test_resolve_alarm_threshold_legacy_call_no_category_dict: PASS")


def test_dry_run_blocks_on_extreme_price_change_when_enabled():
    item = make_item(product_id=10, old_price="100.00", new_price="300.00",
                      change_status="changed", price_changed=1)
    thresholds = {None: {"warning": 20.0, "critical": 150.0, "block_enabled": True}}
    summary = _compute_dry_run_summary([item], alarm_threshold=20.0, category_thresholds=thresholds)
    assert any(e["type"] == "extreme_price_change" for e in summary["critical_errors"]), summary
    assert summary["dry_run_status"] == "blocked", summary
    print("test_dry_run_blocks_on_extreme_price_change_when_enabled: PASS")


def test_dry_run_warns_only_when_block_disabled():
    item = make_item(product_id=11, old_price="100.00", new_price="300.00",
                      change_status="changed", price_changed=1)
    thresholds = {None: {"warning": 20.0, "critical": 150.0, "block_enabled": False}}
    summary = _compute_dry_run_summary([item], alarm_threshold=20.0, category_thresholds=thresholds)
    assert summary["critical_errors"] == [], summary["critical_errors"]
    assert any(w["type"] == "large_price_change" for w in summary["warnings"]), summary["warnings"]
    assert summary["dry_run_status"] == "warnings", summary
    print("test_dry_run_warns_only_when_block_disabled: PASS")


def test_dry_run_category_threshold_overrides_global():
    item = make_item(product_id=12, old_price="100.00", new_price="160.00",  # 60% change
                      change_status="changed", price_changed=1,
                      categories=json.dumps([{"id": 5, "name": "Electronics"}]))
    thresholds = {
        None: {"warning": 20.0, "critical": 150.0, "block_enabled": True},   # would warn+not block at 60%
        5: {"warning": 10.0, "critical": 50.0, "block_enabled": True},        # 60% > 50% -> blocks
    }
    summary = _compute_dry_run_summary([item], alarm_threshold=20.0, category_thresholds=thresholds)
    assert any(e["type"] == "extreme_price_change" for e in summary["critical_errors"]), summary
    assert summary["dry_run_status"] == "blocked", summary
    print("test_dry_run_category_threshold_overrides_global: PASS")


def test_dry_run_no_thresholds_configured_is_safe_default():
    item = make_item(product_id=13, old_price="100.00", new_price="900.00",
                      change_status="changed", price_changed=1)
    summary = _compute_dry_run_summary([item], alarm_threshold=float("inf"))
    assert summary["critical_errors"] == [], summary["critical_errors"]
    assert not any(w["type"] in ("large_price_change", "extreme_price_change") for w in summary["warnings"]), summary["warnings"]
    print("test_dry_run_no_thresholds_configured_is_safe_default: PASS")


if __name__ == "__main__":
    test_extremely_high_price_is_warning_not_critical()
    test_rial_price_below_threshold_is_clean()
    test_resolve_alarm_threshold_global_fallback()
    test_resolve_alarm_threshold_category_override()
    test_resolve_alarm_threshold_legacy_call_no_category_dict()
    test_dry_run_blocks_on_extreme_price_change_when_enabled()
    test_dry_run_warns_only_when_block_disabled()
    test_dry_run_category_threshold_overrides_global()
    test_dry_run_no_thresholds_configured_is_safe_default()
    print("ALL TESTS PASSED")
