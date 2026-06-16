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


def test_upsert_products_does_not_clear_known_brand_on_partial_update():
    # A later upsert that omits brand info entirely (brand_id=None) must not
    # erase a previously known brand — only an explicit non-null brand_id
    # from WooCommerce should change it.
    db = SessionLocal()
    try:
        upsert_products(db, [{
            "wc_id": 90003, "parent_id": 0, "product_type": "simple",
            "name": "Branded Product", "brand_id": 5758, "brand_name": "Whoop",
        }])
        db.commit()
        upsert_products(db, [{
            "wc_id": 90003, "parent_id": 0, "product_type": "simple",
            "name": "Branded Product", "brand_id": None, "brand_name": None,
        }])
        db.commit()
        row = db.query(ProductCache).filter(ProductCache.wc_id == 90003).one()
        assert row.brand_id == 5758 and row.brand_name == "Whoop"
    finally:
        db.query(ProductCache).filter(ProductCache.wc_id == 90003).delete()
        db.commit()
        db.close()
    print("test_upsert_products_does_not_clear_known_brand_on_partial_update: PASS")


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
    test_upsert_products_does_not_clear_known_brand_on_partial_update()
    print("ALL TESTS PASSED")
