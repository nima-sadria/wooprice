"""Tests for the brand-analytics foundation.

Brand source confirmed via live WooCommerce audit (softpple.com): the native
WooCommerce "Brands" feature (taxonomy `product_brand`), exposed on every
product payload as a top-level `brands: [{id, name, slug}]` array — structured
exactly like `categories`. Variations never carry their own `brands` key and
always inherit the parent's brand. No brand assigned -> (None, None); this
must never be guessed from the product name or any other field.

Run directly (no pytest dependency):
    python tests/test_brand_foundation.py
"""
import os
import sys

os.environ.setdefault("NEXTCLOUD_URL", "http://example.invalid")
os.environ.setdefault("NEXTCLOUD_USER", "x")
os.environ.setdefault("NEXTCLOUD_PASSWORD", "x")
os.environ.setdefault("NEXTCLOUD_FILE_PATH", "/x.xlsx")
os.environ.setdefault("WC_URL", "http://example.invalid")
os.environ.setdefault("WC_KEY", "x")
os.environ.setdefault("WC_SECRET", "x")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import _compute_brand_coverage  # noqa: E402
from app.models import ProductCache  # noqa: E402
from app.services.product_cache import _to_dict, upsert_products  # noqa: E402
from app.services.woocommerce import (  # noqa: E402
    _extract_brand,
    _parse_full_product,
    _parse_product,
)

Base.metadata.create_all(engine)


# ── _extract_brand ──────────────────────────────────────────────────────────

def test_extract_brand_with_brand():
    p = {"brands": [{"id": 942, "name": "اپل", "slug": "apple"}]}
    assert _extract_brand(p) == (942, "اپل")
    print("test_extract_brand_with_brand: PASS")


def test_extract_brand_no_brand_assigned():
    assert _extract_brand({"brands": []}) == (None, None)
    assert _extract_brand({}) == (None, None)
    print("test_extract_brand_no_brand_assigned: PASS")


# ── _parse_product (light/legacy fetch path) ────────────────────────────────

def test_parse_product_includes_brand():
    p = {
        "name": "iPad", "regular_price": "100", "sku": "X1",
        "categories": [], "brands": [{"id": 5, "name": "Apple"}],
    }
    out = _parse_product(p)
    assert out["brand_id"] == 5
    assert out["brand_name"] == "Apple"
    print("test_parse_product_includes_brand: PASS")


def test_parse_product_no_brand_is_none_not_guessed():
    p = {"name": "Some Apple-branded Cable", "regular_price": "10", "categories": []}
    out = _parse_product(p)
    assert out["brand_id"] is None
    assert out["brand_name"] is None
    print("test_parse_product_no_brand_is_none_not_guessed: PASS")


# ── _parse_full_product (fast/full/light sync path) ─────────────────────────

def test_parse_full_product_parent_uses_own_brand():
    p = {"id": 1, "name": "iPad", "type": "variable", "brands": [{"id": 942, "name": "Apple"}]}
    out = _parse_full_product(p)
    assert out["brand_id"] == 942 and out["brand_name"] == "Apple"
    print("test_parse_full_product_parent_uses_own_brand: PASS")


def test_parse_full_product_variation_inherits_parent_brand():
    # Variations never carry their own `brands` key (confirmed via audit) —
    # even if one were present, parent_id > 0 must always win.
    v = {"id": 2, "brands": [{"id": 999, "name": "WRONG"}]}
    out = _parse_full_product(v, parent_id=1, parent_cats=[], parent_brand=(942, "Apple"))
    assert out["brand_id"] == 942 and out["brand_name"] == "Apple"
    print("test_parse_full_product_variation_inherits_parent_brand: PASS")


def test_parse_full_product_variation_no_parent_brand_is_unknown():
    v = {"id": 2}
    out = _parse_full_product(v, parent_id=1, parent_cats=[], parent_brand=None)
    assert out["brand_id"] is None and out["brand_name"] is None
    print("test_parse_full_product_variation_no_parent_brand_is_unknown: PASS")


# ── _compute_brand_coverage ──────────────────────────────────────────────────

def test_compute_brand_coverage_basic():
    rows = [(942, "Apple", 10), (5758, "Whoop", 3), (None, None, 2)]
    out = _compute_brand_coverage(rows)
    assert out["total_products"] == 15
    assert out["brand_count"] == 2
    assert out["brands"][0]["brand_name"] == "Apple"  # sorted desc by count
    assert out["unknown_brand"]["product_count"] == 2
    assert out["coverage_percent"] == round(13 / 15 * 100, 1)
    print("test_compute_brand_coverage_basic: PASS")


def test_compute_brand_coverage_empty_is_safe():
    out = _compute_brand_coverage([])
    assert out["total_products"] == 0
    assert out["coverage_percent"] == 0.0
    assert out["unknown_brand"]["product_count"] == 0
    print("test_compute_brand_coverage_empty_is_safe: PASS")


def test_compute_brand_coverage_all_unknown():
    rows = [(None, None, 7)]
    out = _compute_brand_coverage(rows)
    assert out["brand_count"] == 0
    assert out["unknown_brand"]["product_count"] == 7
    assert out["coverage_percent"] == 0.0
    print("test_compute_brand_coverage_all_unknown: PASS")


# ── upsert_products / _to_dict round trip ────────────────────────────────────

def test_upsert_products_stores_and_reads_brand():
    db = SessionLocal()
    try:
        upsert_products(db, [{
            "wc_id": 90001, "parent_id": 0, "product_type": "simple",
            "name": "Test Product", "brand_id": 942, "brand_name": "Apple",
        }])
        db.commit()
        row = db.query(ProductCache).filter(ProductCache.wc_id == 90001).one()
        assert row.brand_id == 942 and row.brand_name == "Apple"
        d = _to_dict(row)
        assert d["brand_id"] == 942 and d["brand_name"] == "Apple"
    finally:
        db.query(ProductCache).filter(ProductCache.wc_id == 90001).delete()
        db.commit()
        db.close()
    print("test_upsert_products_stores_and_reads_brand: PASS")


def test_upsert_products_unknown_brand_stays_none():
    db = SessionLocal()
    try:
        upsert_products(db, [{
            "wc_id": 90002, "parent_id": 0, "product_type": "simple",
            "name": "No Brand Product", "brand_id": None, "brand_name": None,
        }])
        db.commit()
        row = db.query(ProductCache).filter(ProductCache.wc_id == 90002).one()
        assert row.brand_id is None and row.brand_name is None
    finally:
        db.query(ProductCache).filter(ProductCache.wc_id == 90002).delete()
        db.commit()
        db.close()
    print("test_upsert_products_unknown_brand_stays_none: PASS")


def test_upsert_brand_preserved_when_keys_absent():
    # A partial-update dict that contains NO brand keys must leave the cached
    # brand untouched — the absent key signals a non-authoritative caller.
    db = SessionLocal()
    try:
        upsert_products(db, [{
            "wc_id": 90003, "parent_id": 0, "product_type": "simple",
            "name": "Branded Product", "brand_id": 5758, "brand_name": "Whoop",
        }])
        db.commit()
        # Second upsert omits brand keys entirely — non-authoritative caller
        upsert_products(db, [{
            "wc_id": 90003, "parent_id": 0, "product_type": "simple",
            "name": "Branded Product",
        }])
        db.commit()
        row = db.query(ProductCache).filter(ProductCache.wc_id == 90003).one()
        assert row.brand_id == 5758 and row.brand_name == "Whoop"
    finally:
        db.query(ProductCache).filter(ProductCache.wc_id == 90003).delete()
        db.commit()
        db.close()
    print("test_upsert_brand_preserved_when_keys_absent: PASS")


def test_upsert_brand_updated_when_value_present():
    # An authoritative update with a non-None brand_id must overwrite the
    # existing cached brand on an UPDATE (not just INSERT).
    db = SessionLocal()
    try:
        upsert_products(db, [{
            "wc_id": 90004, "parent_id": 0, "product_type": "simple",
            "name": "Product", "brand_id": 942, "brand_name": "Apple",
        }])
        db.commit()
        upsert_products(db, [{
            "wc_id": 90004, "parent_id": 0, "product_type": "simple",
            "name": "Product", "brand_id": 5758, "brand_name": "Whoop",
        }])
        db.commit()
        row = db.query(ProductCache).filter(ProductCache.wc_id == 90004).one()
        assert row.brand_id == 5758 and row.brand_name == "Whoop"
    finally:
        db.query(ProductCache).filter(ProductCache.wc_id == 90004).delete()
        db.commit()
        db.close()
    print("test_upsert_brand_updated_when_value_present: PASS")


def test_upsert_brand_cleared_when_key_present_with_none():
    # An authoritative update where brand_id key IS present but value is None
    # must clear the cached brand — this is how full-sync expresses
    # "brand removed in WooCommerce".
    db = SessionLocal()
    try:
        upsert_products(db, [{
            "wc_id": 90005, "parent_id": 0, "product_type": "simple",
            "name": "Was Branded", "brand_id": 942, "brand_name": "Apple",
        }])
        db.commit()
        upsert_products(db, [{
            "wc_id": 90005, "parent_id": 0, "product_type": "simple",
            "name": "Was Branded", "brand_id": None, "brand_name": None,
        }])
        db.commit()
        row = db.query(ProductCache).filter(ProductCache.wc_id == 90005).one()
        assert row.brand_id is None and row.brand_name is None
    finally:
        db.query(ProductCache).filter(ProductCache.wc_id == 90005).delete()
        db.commit()
        db.close()
    print("test_upsert_brand_cleared_when_key_present_with_none: PASS")


def test_full_sync_clears_stale_brand_after_wc_brand_removal():
    # Simulate the exact production failure path:
    # 1. Product in cache with brand_id=942 ("Apple")
    # 2. Brand removed from product in WooCommerce (brands: [])
    # 3. Full-sync parser (_parse_full_product) emits brand_id=None (key present)
    # 4. upsert_products must clear the stale brand — not preserve it
    db = SessionLocal()
    try:
        upsert_products(db, [{
            "wc_id": 90006, "parent_id": 0, "product_type": "simple",
            "name": "iPad", "brand_id": 942, "brand_name": "Apple",
        }])
        db.commit()
        # Simulate WC response after brand removal
        wc_response_no_brand = {
            "id": 90006, "name": "iPad", "type": "simple", "brands": [],
        }
        parsed = _parse_full_product(wc_response_no_brand)
        assert parsed["brand_id"] is None, "parser must produce None for brands:[]"
        assert "brand_id" in parsed, "key must be present so upsert knows to clear"
        upsert_products(db, [parsed])
        db.commit()
        row = db.query(ProductCache).filter(ProductCache.wc_id == 90006).one()
        assert row.brand_id is None and row.brand_name is None
    finally:
        db.query(ProductCache).filter(ProductCache.wc_id == 90006).delete()
        db.commit()
        db.close()
    print("test_full_sync_clears_stale_brand_after_wc_brand_removal: PASS")


def test_unknown_brand_bucket_increases_after_explicit_clear():
    # After an authoritative brand clear the product must move from the
    # known-brand bucket into the unknown_brand bucket in coverage analytics.
    db = SessionLocal()
    try:
        upsert_products(db, [{
            "wc_id": 90007, "parent_id": 0, "product_type": "simple",
            "name": "MacBook", "brand_id": 942, "brand_name": "Apple",
        }])
        db.commit()
        rows_before = db.query(
            ProductCache.brand_id, ProductCache.brand_name,
            func.count(ProductCache.wc_id),
        ).filter(ProductCache.wc_id == 90007).group_by(
            ProductCache.brand_id, ProductCache.brand_name,
        ).all()
        before = _compute_brand_coverage(rows_before)
        assert before["unknown_brand"]["product_count"] == 0
        # Authoritative clear — brand removed in WC
        upsert_products(db, [{
            "wc_id": 90007, "parent_id": 0, "product_type": "simple",
            "name": "MacBook", "brand_id": None, "brand_name": None,
        }])
        db.commit()
        rows_after = db.query(
            ProductCache.brand_id, ProductCache.brand_name,
            func.count(ProductCache.wc_id),
        ).filter(ProductCache.wc_id == 90007).group_by(
            ProductCache.brand_id, ProductCache.brand_name,
        ).all()
        after = _compute_brand_coverage(rows_after)
        assert after["unknown_brand"]["product_count"] == 1
    finally:
        db.query(ProductCache).filter(ProductCache.wc_id == 90007).delete()
        db.commit()
        db.close()
    print("test_unknown_brand_bucket_increases_after_explicit_clear: PASS")


if __name__ == "__main__":
    test_extract_brand_with_brand()
    test_extract_brand_no_brand_assigned()
    test_parse_product_includes_brand()
    test_parse_product_no_brand_is_none_not_guessed()
    test_parse_full_product_parent_uses_own_brand()
    test_parse_full_product_variation_inherits_parent_brand()
    test_parse_full_product_variation_no_parent_brand_is_unknown()
    test_compute_brand_coverage_basic()
    test_compute_brand_coverage_empty_is_safe()
    test_compute_brand_coverage_all_unknown()
    test_upsert_products_stores_and_reads_brand()
    test_upsert_products_unknown_brand_stays_none()
    test_upsert_brand_preserved_when_keys_absent()
    test_upsert_brand_updated_when_value_present()
    test_upsert_brand_cleared_when_key_present_with_none()
    test_full_sync_clears_stale_brand_after_wc_brand_removal()
    test_unknown_brand_bucket_increases_after_explicit_clear()
    print("ALL TESTS PASSED")
