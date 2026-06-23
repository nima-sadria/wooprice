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

R2 (7.4A R2 remediation) — MEDIUM 3: price filter matches displayed price (final_price || regular_price):
  M1  — final_price only → has_price
  M2  — regular_price only → has_price
  M3  — both populated → has_price
  M4  — both missing → no_price
  M5  — stock + price combination filter works correctly
  M6  — pagination total counts are correct across both filter values

R2 (7.4A R2 remediation) — LOW: deterministic sort secondary key:
  L1  — identical last_synced_at: secondary wc_id DESC breaks ties for newest
  L2  — identical names: secondary wc_id ASC breaks ties for name_asc
  L3  — page boundaries are stable with deterministic sort
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


# ── MEDIUM 3 fixtures ─────────────────────────────────────────────────────────

M3_WC_IDS = [97011, 97012, 97013, 97014, 97015]


@pytest.fixture()
def m3_db(db):
    """Products with deliberate final_price/regular_price combinations."""
    db.query(ProductCache).filter(ProductCache.wc_id.in_(M3_WC_IDS)).delete()
    db.commit()
    rows = [
        # 97011: final_price only (regular_price empty) → has_price via final_price
        ProductCache(
            wc_id=97011, parent_id=0, product_type="simple",
            name="M3 Final Only", sku="M3-A",
            stock_status="instock", stock_quantity=1,
            regular_price="", final_price="100000",
            categories="[]", last_synced_at=_now(), last_seen_at=_now(), cache_version=1,
        ),
        # 97012: regular_price only (final_price empty) → has_price via regular_price
        ProductCache(
            wc_id=97012, parent_id=0, product_type="simple",
            name="M3 Regular Only", sku="M3-B",
            stock_status="outofstock", stock_quantity=0,
            regular_price="200000", final_price="",
            categories="[]", last_synced_at=_now(), last_seen_at=_now(), cache_version=1,
        ),
        # 97013: both populated → has_price
        ProductCache(
            wc_id=97013, parent_id=0, product_type="simple",
            name="M3 Both Prices", sku="M3-C",
            stock_status="instock", stock_quantity=5,
            regular_price="90000", final_price="85000",
            categories="[]", last_synced_at=_now(), last_seen_at=_now(), cache_version=1,
        ),
        # 97014: both missing → no_price
        ProductCache(
            wc_id=97014, parent_id=0, product_type="simple",
            name="M3 No Price", sku="M3-D",
            stock_status="instock", stock_quantity=3,
            regular_price="", final_price="",
            categories="[]", last_synced_at=_now(), last_seen_at=_now(), cache_version=1,
        ),
        # 97015: instock + no price (for stock+price combination test)
        ProductCache(
            wc_id=97015, parent_id=0, product_type="simple",
            name="M3 Instock No Price", sku="M3-E",
            stock_status="instock", stock_quantity=2,
            regular_price="", final_price=None,
            categories="[]", last_synced_at=_now(), last_seen_at=_now(), cache_version=1,
        ),
    ]
    for r in rows:
        db.add(r)
    db.commit()
    yield
    db.query(ProductCache).filter(ProductCache.wc_id.in_(M3_WC_IDS)).delete()
    db.commit()


# ── M1: final_price only → has_price ─────────────────────────────────────────

def test_m3_final_price_only_is_has_price(db, m3_db):
    items, _ = get_page(db, limit=1000, price_status="has_price")
    result = ids(items)
    assert 97011 in result, "final_price only must be included in has_price"
    assert 97014 not in result, "both-empty must NOT be in has_price"
    assert 97015 not in result, "final=None, regular='' must NOT be in has_price"


# ── M2: regular_price only → has_price ───────────────────────────────────────

def test_m3_regular_price_only_is_has_price(db, m3_db):
    items, _ = get_page(db, limit=1000, price_status="has_price")
    result = ids(items)
    assert 97012 in result, "regular_price only must be included in has_price"


# ── M3: both populated → has_price ───────────────────────────────────────────

def test_m3_both_populated_is_has_price(db, m3_db):
    items, _ = get_page(db, limit=1000, price_status="has_price")
    result = ids(items)
    assert 97013 in result, "both prices populated must be in has_price"


# ── M4: both missing → no_price ──────────────────────────────────────────────

def test_m3_both_missing_is_no_price(db, m3_db):
    items, _ = get_page(db, limit=1000, price_status="no_price")
    result = ids(items)
    assert 97014 in result, "both empty must be in no_price"
    assert 97015 in result, "final=None, regular='' must be in no_price"
    assert 97011 not in result, "final_price present must NOT be in no_price"
    assert 97012 not in result, "regular_price present must NOT be in no_price"
    assert 97013 not in result, "both prices present must NOT be in no_price"


# ── M5: stock + price combination filter ─────────────────────────────────────

def test_m3_stock_and_price_combination(db, m3_db):
    # instock products that have no price
    items, total = get_page(db, limit=1000, stock_status="instock", price_status="no_price")
    result = ids(items)
    assert 97014 in result, "instock + no_price: wc_id 97014 expected"
    assert 97015 in result, "instock + no_price: wc_id 97015 expected"
    assert 97012 not in result, "outofstock must be excluded by stock filter"
    assert 97011 not in result, "has final_price must be excluded by price filter"

    # outofstock products that have a price
    items2, _ = get_page(db, limit=1000, stock_status="outofstock", price_status="has_price")
    result2 = ids(items2)
    assert 97012 in result2, "outofstock + has_price: wc_id 97012 expected"
    assert 97014 not in result2, "no_price must be excluded"


# ── M6: pagination totals remain correct with new price logic ─────────────────

def test_m3_pagination_total_consistent(db, m3_db):
    _, total_has = get_page(db, limit=1000, price_status="has_price")
    _, total_no = get_page(db, limit=1000, price_status="no_price")
    _, total_all = get_page(db, limit=1000)
    assert total_has + total_no == total_all, (
        f"has_price ({total_has}) + no_price ({total_no}) must equal total ({total_all})"
    )


# ── LOW: deterministic sort fixtures ─────────────────────────────────────────

L_WC_IDS = [97021, 97022, 97023, 97024]
_SHARED_TS = _now() - timedelta(hours=10)


@pytest.fixture()
def l_db(db):
    """Products with identical timestamps and identical names for tie-break tests."""
    db.query(ProductCache).filter(ProductCache.wc_id.in_(L_WC_IDS)).delete()
    db.commit()
    rows = [
        # 97021 and 97022 share the same last_synced_at — tie must break by wc_id DESC for newest
        ProductCache(
            wc_id=97021, parent_id=0, product_type="simple",
            name="L TieBreak Name", sku="L-A",
            stock_status="instock", stock_quantity=1,
            regular_price="10000", final_price="10000",
            categories="[]", last_synced_at=_SHARED_TS, last_seen_at=_now(), cache_version=1,
        ),
        ProductCache(
            wc_id=97022, parent_id=0, product_type="simple",
            name="L TieBreak Name", sku="L-B",
            stock_status="instock", stock_quantity=1,
            regular_price="10000", final_price="10000",
            categories="[]", last_synced_at=_SHARED_TS, last_seen_at=_now(), cache_version=1,
        ),
        # 97023 and 97024 also share the same name for name sort tie-break tests
        ProductCache(
            wc_id=97023, parent_id=0, product_type="simple",
            name="L Identical Name", sku="L-C",
            stock_status="instock", stock_quantity=1,
            regular_price="10000", final_price="10000",
            categories="[]", last_synced_at=_now() - timedelta(hours=1), last_seen_at=_now(), cache_version=1,
        ),
        ProductCache(
            wc_id=97024, parent_id=0, product_type="simple",
            name="L Identical Name", sku="L-D",
            stock_status="instock", stock_quantity=1,
            regular_price="10000", final_price="10000",
            categories="[]", last_synced_at=_now() - timedelta(hours=2), last_seen_at=_now(), cache_version=1,
        ),
    ]
    for r in rows:
        db.add(r)
    db.commit()
    yield
    db.query(ProductCache).filter(ProductCache.wc_id.in_(L_WC_IDS)).delete()
    db.commit()


# ── L1: identical timestamps — wc_id DESC breaks tie for newest sort ──────────

def test_low_identical_ts_newest_tie_break(db, l_db):
    items, _ = get_page(db, limit=1000, sort="newest")
    our_items = [it for it in items if it["wc_id"] in (97021, 97022)]
    assert len(our_items) == 2
    # Higher wc_id first (97022 before 97021)
    assert our_items[0]["wc_id"] == 97022, (
        f"With equal timestamps, higher wc_id must come first in newest sort; "
        f"got {[it['wc_id'] for it in our_items]}"
    )


# ── L2: identical names — wc_id ASC breaks tie for name_asc sort ─────────────

def test_low_identical_names_name_asc_tie_break(db, l_db):
    items, _ = get_page(db, limit=1000, sort="name_asc")
    our_items = [it for it in items if it["wc_id"] in (97023, 97024)]
    assert len(our_items) == 2
    # Lower wc_id first (97023 before 97024)
    assert our_items[0]["wc_id"] == 97023, (
        f"With equal names, lower wc_id must come first in name_asc sort; "
        f"got {[it['wc_id'] for it in our_items]}"
    )


# ── L3: page boundaries stable with deterministic sort ────────────────────────

def test_low_page_boundaries_stable(db, l_db):
    # Fetch two pages of size 2 and verify no wc_id appears on both pages
    page1, total = get_page(db, limit=2, sort="newest", page=1)
    page2, _ = get_page(db, limit=2, sort="newest", page=2)
    ids_p1 = {it["wc_id"] for it in page1}
    ids_p2 = {it["wc_id"] for it in page2}
    overlap = ids_p1 & ids_p2
    assert not overlap, (
        f"Deterministic sort must produce stable pages; "
        f"found wc_ids on both page 1 and page 2: {overlap}"
    )
