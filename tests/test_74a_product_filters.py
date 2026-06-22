"""Project 7.4A — Tests for new /api/products filter parameters.

Covers the get_page() additions:
  F1  — stock_status filter: instock only
  F2  — stock_status filter: outofstock only
  F3  — price_status has_price: filters out empty-price products
  F4  — price_status no_price: returns only empty-price products
  F5  — category_ids OR filter: returns products in any of the given categories
  F6  — category_ids OR filter: does NOT return products outside the given categories
  F7  — quality_filter missing_sku
  F8  — quality_filter missing_image
  F9  — sort newest: last_synced_at DESC
  F10 — sort name_asc: alphabetical
  F11 — /api/products endpoint accepts new query params (HTTP integration)
  F12 — category_ids with multiple IDs uses OR logic

R1 (7.4A R1 remediation):
  V1  — stock_status=all returns all products (no filter)
  V2  — price_status=all returns all products (no filter)
  V3  — stock_status=all is safe in get_page() (no spurious DB predicate)
  V4  — price_status=all is safe in get_page() (no spurious DB predicate)
  V5  — invalid stock_status returns HTTP 422
  V6  — invalid price_status returns HTTP 422
  V7  — invalid sort returns HTTP 422
  V8  — invalid quality_filter returns HTTP 422
  V9  — invalid product_type returns HTTP 422
"""
import json
import os
import sys
from datetime import datetime, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("NEXTCLOUD_URL", "http://example.invalid")
os.environ.setdefault("NEXTCLOUD_USER", "x")
os.environ.setdefault("NEXTCLOUD_PASSWORD", "x")
os.environ.setdefault("NEXTCLOUD_FILE_PATH", "/x.xlsx")
os.environ.setdefault("WC_URL", "http://wc.example.invalid")
os.environ.setdefault("WC_KEY", "ck_test")
os.environ.setdefault("WC_SECRET", "cs_test")
os.environ.setdefault("SUPER_ADMIN_USERS", "testadmin_74a")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.auth import create_token
from app.database import Base, SessionLocal, engine
from app.models import ProductCache, AppUser
from app.services.product_cache import get_page

Base.metadata.create_all(bind=engine)

# ── Fixtures ──────────────────────────────────────────────────────────────────

WC_IDS = [97001, 97002, 97003, 97004, 97005]
_HTTP_USER = "http_user_74a"


def _now() -> datetime:
    return datetime.utcnow()


@pytest.fixture(scope="module")
def db():
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module", autouse=True)
def seed(db):
    """Insert 5 test products with varying attributes."""
    db.query(ProductCache).filter(ProductCache.wc_id.in_(WC_IDS)).delete()
    db.commit()

    # AppUser for HTTP integration tests — permission_version=0 matches token pv=0
    db.query(AppUser).filter(AppUser.username == _HTTP_USER).delete()
    db.commit()
    http_user = AppUser(
        username=_HTTP_USER, is_active=True, is_admin=False,
        permission_version=0, can_access_site=True, can_fetch=True,
    )
    db.add(http_user)
    db.commit()

    rows = [
        ProductCache(
            wc_id=97001, parent_id=0, product_type="simple",
            name="Alpha Product", sku="SKU-A",
            stock_status="instock", stock_quantity=10,
            regular_price="100000", final_price="100000",
            categories=json.dumps([{"id": 10, "name": "Clothing"}]),
            image_url="http://img.example/a.jpg",
            last_synced_at=_now() - timedelta(hours=1),
            last_seen_at=_now(), cache_version=1,
        ),
        ProductCache(
            wc_id=97002, parent_id=0, product_type="variable",
            name="Beta Product", sku="",
            stock_status="outofstock", stock_quantity=0,
            regular_price="200000", final_price="200000",
            categories=json.dumps([{"id": 20, "name": "Electronics"}]),
            image_url=None,
            last_synced_at=_now() - timedelta(hours=2),
            last_seen_at=_now(), cache_version=1,
        ),
        ProductCache(
            wc_id=97003, parent_id=0, product_type="simple",
            name="Gamma Product", sku="SKU-G",
            stock_status="instock", stock_quantity=5,
            regular_price="", final_price="",
            categories=json.dumps([{"id": 10, "name": "Clothing"}, {"id": 30, "name": "Sale"}]),
            image_url="http://img.example/g.jpg",
            last_synced_at=_now() - timedelta(minutes=30),
            last_seen_at=_now(), cache_version=1,
        ),
        ProductCache(
            wc_id=97004, parent_id=97002, product_type="variation",
            name="Beta Product - Red", sku=None,
            stock_status="outofstock", stock_quantity=0,
            regular_price="180000", final_price="180000",
            categories=json.dumps([{"id": 20, "name": "Electronics"}]),
            image_url=None,
            last_synced_at=_now() - timedelta(hours=3),
            last_seen_at=_now(), cache_version=1,
        ),
        ProductCache(
            wc_id=97005, parent_id=0, product_type="simple",
            name="Delta Product", sku="SKU-D",
            stock_status="instock", stock_quantity=0,
            regular_price="50000", final_price="50000",
            categories=json.dumps([]),
            image_url="http://img.example/d.jpg",
            last_synced_at=_now() - timedelta(minutes=5),
            last_seen_at=_now(), cache_version=1,
        ),
    ]
    for r in rows:
        db.add(r)
    db.commit()

    yield

    db.query(ProductCache).filter(ProductCache.wc_id.in_(WC_IDS)).delete()
    db.query(AppUser).filter(AppUser.username == _HTTP_USER).delete()
    db.commit()


# ── Helper ────────────────────────────────────────────────────────────────────

def ids(items) -> set:
    return {it["wc_id"] for it in items}


# ── F1: stock_status instock ──────────────────────────────────────────────────

def test_filter_stock_instock(db):
    items, total = get_page(db, limit=100, stock_status="instock")
    result = ids(items)
    assert 97001 in result, "Alpha (instock) must be returned"
    assert 97003 in result, "Gamma (instock) must be returned"
    assert 97005 in result, "Delta (instock) must be returned"
    assert 97002 not in result, "Beta (outofstock) must NOT be returned"
    assert 97004 not in result, "Beta-Red (outofstock) must NOT be returned"


# ── F2: stock_status outofstock ───────────────────────────────────────────────

def test_filter_stock_outofstock(db):
    items, _ = get_page(db, limit=100, stock_status="outofstock")
    result = ids(items)
    assert 97002 in result
    assert 97004 in result
    assert 97001 not in result


# ── F3: price_status has_price ────────────────────────────────────────────────

def test_filter_price_has_price(db):
    items, _ = get_page(db, limit=100, price_status="has_price")
    result = ids(items)
    assert 97001 in result, "Alpha has price"
    assert 97002 in result, "Beta has price"
    assert 97004 in result, "Beta-Red has price"
    assert 97005 in result, "Delta has price"
    assert 97003 not in result, "Gamma has empty price — must be excluded"


# ── F4: price_status no_price ─────────────────────────────────────────────────

def test_filter_price_no_price(db):
    items, _ = get_page(db, limit=100, price_status="no_price")
    result = ids(items)
    assert 97003 in result, "Gamma (empty price) must be returned"
    assert 97001 not in result
    assert 97002 not in result


# ── F5: category_ids OR — returns products in given categories ────────────────

def test_filter_category_ids_returns_matching(db):
    items, _ = get_page(db, limit=100, category_ids=[10])
    result = ids(items)
    assert 97001 in result, "Alpha is in category 10"
    assert 97003 in result, "Gamma is in categories 10 and 30"


# ── F6: category_ids OR — excludes products outside the categories ────────────

def test_filter_category_ids_excludes_others(db):
    items, _ = get_page(db, limit=100, category_ids=[20])
    result = ids(items)
    assert 97002 in result, "Beta is in category 20"
    assert 97004 in result, "Beta-Red is in category 20"
    assert 97001 not in result, "Alpha is NOT in category 20"
    assert 97005 not in result, "Delta has no categories"


# ── F12: category_ids OR — multiple IDs use OR logic ─────────────────────────

def test_filter_category_ids_or_logic(db):
    items, _ = get_page(db, limit=100, category_ids=[10, 20])
    result = ids(items)
    assert 97001 in result, "Alpha (cat 10)"
    assert 97002 in result, "Beta (cat 20)"
    assert 97003 in result, "Gamma (cat 10 and 30)"
    assert 97004 in result, "Beta-Red (cat 20)"
    assert 97005 not in result, "Delta has no categories → excluded"


# ── F7: quality_filter missing_sku ───────────────────────────────────────────

def test_filter_quality_missing_sku(db):
    items, _ = get_page(db, limit=100, quality_filter="missing_sku")
    result = ids(items)
    assert 97002 in result, "Beta has empty-string SKU"
    assert 97004 in result, "Beta-Red has NULL SKU"
    assert 97001 not in result, "Alpha has SKU-A"
    assert 97003 not in result, "Gamma has SKU-G"


# ── F8: quality_filter missing_image ─────────────────────────────────────────

def test_filter_quality_missing_image(db):
    items, _ = get_page(db, limit=100, quality_filter="missing_image")
    result = ids(items)
    assert 97002 in result, "Beta has no image_url"
    assert 97004 in result, "Beta-Red has no image_url"
    assert 97001 not in result, "Alpha has image"
    assert 97003 not in result, "Gamma has image"


# ── F9: sort newest ───────────────────────────────────────────────────────────

def test_sort_newest_first(db):
    items, _ = get_page(db, limit=10, sort="newest")
    result = [it["wc_id"] for it in items if it["wc_id"] in WC_IDS]
    # Delta (5 min ago) should come before Alpha (1 hr ago)
    assert result.index(97005) < result.index(97001), (
        "Most recently synced product must appear before older ones"
    )


# ── F10: sort name_asc ────────────────────────────────────────────────────────

def test_sort_name_asc(db):
    items, _ = get_page(db, limit=100, sort="name_asc")
    names = [it["name"] for it in items if it["wc_id"] in WC_IDS]
    assert names == sorted(names), f"Expected A→Z order, got: {names}"


# ── F11: HTTP integration — /api/products accepts new params ─────────────────

def test_api_products_new_params(client):
    # Use a DB user with can_fetch=True (seeded in the module fixture).
    tok = create_token(_HTTP_USER, permission_version=0, role="user")
    headers = {"Authorization": f"Bearer {tok}"}

    # stock_status
    r = client.get("/api/products?stock_status=instock&limit=100", headers=headers)
    assert r.status_code == 200
    body = r.json()
    wc_ids = {it["wc_id"] for it in body["items"]}
    assert 97001 in wc_ids

    # price_status
    r = client.get("/api/products?price_status=no_price&limit=100", headers=headers)
    assert r.status_code == 200
    body = r.json()
    wc_ids = {it["wc_id"] for it in body["items"]}
    assert 97003 in wc_ids

    # sort + limit
    r = client.get("/api/products?sort=name_asc&limit=5", headers=headers)
    assert r.status_code == 200

    # category_ids (multi-value)
    r = client.get("/api/products?category_ids=10&category_ids=20&limit=100", headers=headers)
    assert r.status_code == 200
    body = r.json()
    wc_ids = {it["wc_id"] for it in body["items"]}
    assert 97001 in wc_ids
    assert 97002 in wc_ids

    # quality_filter
    r = client.get("/api/products?quality_filter=missing_image&limit=100", headers=headers)
    assert r.status_code == 200
    body = r.json()
    wc_ids = {it["wc_id"] for it in body["items"]}
    assert 97002 in wc_ids


# ── V1: stock_status=all returns all products (no filter) ─────────────────────

def test_stock_all_returns_all_products(db):
    items_all, total_all = get_page(db, limit=1000, stock_status="all")
    items_none, total_none = get_page(db, limit=1000, stock_status=None)
    assert total_all == total_none, (
        f"stock_status='all' must apply no filter; "
        f"got {total_all} vs {total_none} with no filter"
    )


# ── V2: price_status=all returns all products (no filter) ─────────────────────

def test_price_all_returns_all_products(db):
    items_all, total_all = get_page(db, limit=1000, price_status="all")
    items_none, total_none = get_page(db, limit=1000, price_status=None)
    assert total_all == total_none, (
        f"price_status='all' must apply no filter; "
        f"got {total_all} vs {total_none} with no filter"
    )


# ── V3: stock_status=all never creates a spurious DB predicate ────────────────

def test_stock_all_not_spurious_predicate(db):
    """stock_status='all' must not search for a literal stock_status='all' value."""
    items, total = get_page(db, limit=1000, stock_status="all")
    ids_result = {it["wc_id"] for it in items}
    # All seeded products must appear (they have instock/outofstock, never 'all')
    for wc_id in WC_IDS:
        assert wc_id in ids_result, (
            f"wc_id={wc_id} was excluded by stock_status='all' — spurious predicate suspected"
        )


# ── V4: price_status=all never creates a spurious DB predicate ───────────────

def test_price_all_not_spurious_predicate(db):
    """price_status='all' must not filter; all products must be returned."""
    _, total_all = get_page(db, limit=1000, price_status="all")
    _, total_baseline = get_page(db, limit=1000)
    assert total_all == total_baseline, (
        f"price_status='all' changed result count: {total_all} vs baseline {total_baseline}"
    )


# ── V5: invalid stock_status → HTTP 422 ───────────────────────────────────────

def test_invalid_stock_status_returns_422(client):
    tok = create_token(_HTTP_USER, permission_version=0, role="user")
    headers = {"Authorization": f"Bearer {tok}"}
    r = client.get("/api/products?stock_status=unknown_value", headers=headers)
    assert r.status_code == 422, (
        f"Invalid stock_status must return HTTP 422, got {r.status_code}"
    )


# ── V6: invalid price_status → HTTP 422 ───────────────────────────────────────

def test_invalid_price_status_returns_422(client):
    tok = create_token(_HTTP_USER, permission_version=0, role="user")
    headers = {"Authorization": f"Bearer {tok}"}
    r = client.get("/api/products?price_status=cheap", headers=headers)
    assert r.status_code == 422, (
        f"Invalid price_status must return HTTP 422, got {r.status_code}"
    )


# ── V7: invalid sort → HTTP 422 ───────────────────────────────────────────────

def test_invalid_sort_returns_422(client):
    tok = create_token(_HTTP_USER, permission_version=0, role="user")
    headers = {"Authorization": f"Bearer {tok}"}
    r = client.get("/api/products?sort=random", headers=headers)
    assert r.status_code == 422, (
        f"Invalid sort must return HTTP 422, got {r.status_code}"
    )


# ── V8: invalid quality_filter → HTTP 422 ────────────────────────────────────

def test_invalid_quality_filter_returns_422(client):
    tok = create_token(_HTTP_USER, permission_version=0, role="user")
    headers = {"Authorization": f"Bearer {tok}"}
    r = client.get("/api/products?quality_filter=bad_filter", headers=headers)
    assert r.status_code == 422, (
        f"Invalid quality_filter must return HTTP 422, got {r.status_code}"
    )


# ── V9: invalid product_type → HTTP 422 ──────────────────────────────────────

def test_invalid_product_type_returns_422(client):
    tok = create_token(_HTTP_USER, permission_version=0, role="user")
    headers = {"Authorization": f"Bearer {tok}"}
    r = client.get("/api/products?product_type=bundle", headers=headers)
    assert r.status_code == 422, (
        f"Invalid product_type must return HTTP 422, got {r.status_code}"
    )
