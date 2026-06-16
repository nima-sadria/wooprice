"""Regression tests for the missing_image parent-fallback fix.

Business rule: a WooCommerce variation commonly has no image of its own and
visually inherits its parent product's gallery image. _classify_row's
missing_image flag must not warn in that case — only when neither the
variation nor its parent has an image.

Run directly (no pytest dependency):
    python tests/test_missing_image_parent_fallback.py
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

from app.main import _classify_row, _row_has_image  # noqa: E402


def cache_row(image_url=None, parent_id=0):
    return SimpleNamespace(image_url=image_url, parent_id=parent_id)


def test_row_has_image_own_image():
    assert _row_has_image(cache_row(image_url="http://x/own.jpg")) is True


def test_row_has_image_no_own_no_parent():
    assert _row_has_image(cache_row(image_url=None), None) is False


def test_row_has_image_parent_fallback():
    variation = cache_row(image_url=None, parent_id=99)
    parent = cache_row(image_url="http://x/parent.jpg")
    assert _row_has_image(variation, parent) is True


def test_row_has_image_neither_has_image():
    variation = cache_row(image_url=None, parent_id=99)
    parent = cache_row(image_url=None)
    assert _row_has_image(variation, parent) is False


def test_classify_row_variation_missing_own_image_but_parent_has_image_not_flagged():
    wc = {"price": "50.00", "stock_status": "instock"}
    variation = cache_row(image_url=None, parent_id=99)
    parent = cache_row(image_url="http://x/parent.jpg")
    clf = _classify_row(1, "55.00", wc, last_price_updated="2024-01-01",
                         cache_row=variation, parent_cache_row=parent)
    assert clf["missing_image"] == 0, clf


def test_classify_row_variation_missing_own_image_and_parent_also_missing_is_flagged():
    wc = {"price": "50.00", "stock_status": "instock"}
    variation = cache_row(image_url=None, parent_id=99)
    parent = cache_row(image_url=None)
    clf = _classify_row(1, "55.00", wc, last_price_updated="2024-01-01",
                         cache_row=variation, parent_cache_row=parent)
    assert clf["missing_image"] == 1, clf


def test_classify_row_no_parent_cache_row_falls_back_to_old_behavior():
    wc = {"price": "50.00", "stock_status": "instock"}
    variation = cache_row(image_url=None, parent_id=99)
    clf = _classify_row(1, "55.00", wc, last_price_updated="2024-01-01",
                         cache_row=variation, parent_cache_row=None)
    assert clf["missing_image"] == 1, clf


def test_classify_row_missing_from_wc_cache_also_uses_parent_fallback():
    variation = cache_row(image_url=None, parent_id=99)
    parent = cache_row(image_url="http://x/parent.jpg")
    clf = _classify_row(1, "55.00", {}, last_price_updated=None,
                         cache_row=variation, parent_cache_row=parent)
    assert clf["change_status"] == "missing_from_wc_cache"
    assert clf["missing_image"] == 0, clf


def test_classify_row_own_image_present_ignores_parent():
    wc = {"price": "50.00", "stock_status": "instock"}
    variation = cache_row(image_url="http://x/own.jpg", parent_id=99)
    clf = _classify_row(1, "55.00", wc, last_price_updated="2024-01-01",
                         cache_row=variation, parent_cache_row=None)
    assert clf["missing_image"] == 0, clf


if __name__ == "__main__":
    test_row_has_image_own_image()
    test_row_has_image_no_own_no_parent()
    test_row_has_image_parent_fallback()
    test_row_has_image_neither_has_image()
    test_classify_row_variation_missing_own_image_but_parent_has_image_not_flagged()
    test_classify_row_variation_missing_own_image_and_parent_also_missing_is_flagged()
    test_classify_row_no_parent_cache_row_falls_back_to_old_behavior()
    test_classify_row_missing_from_wc_cache_also_uses_parent_fallback()
    test_classify_row_own_image_present_ignores_parent()
    print("ALL TESTS PASSED")
