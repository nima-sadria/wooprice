"""Project 7.3A Remediation 1 — Parent metadata propagation + WC capability guard.

Coverage:
  P1 — propagate_parent_metadata_to_children updates child name when parent name changed
  P2 — propagate_parent_metadata_to_children updates child categories when parent changed
  P3 — propagate_parent_metadata_to_children updates child brand when parent changed
  P4 — propagate_parent_metadata_to_children updates inherited image when parent changed
  P5 — propagate_parent_metadata_to_children does NOT overwrite child's own variation image
  P6 — propagate_parent_metadata_to_children makes no WooCommerce (httpx.AsyncClient) call
  P7 — propagate_parent_metadata_to_children returns count of actually-changed rows
  C1 — check_variation_filter_capability returns True when endpoint returns empty list
  C2 — check_variation_filter_capability returns False when endpoint ignores the filter
  C3 — check_variation_filter_capability result is cached after first call
"""
import asyncio
import os
import sys
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# ── Minimal env ───────────────────────────────────────────────────────────────
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("NEXTCLOUD_URL", "http://example.invalid")
os.environ.setdefault("NEXTCLOUD_USER", "x")
os.environ.setdefault("NEXTCLOUD_PASSWORD", "x")
os.environ.setdefault("NEXTCLOUD_FILE_PATH", "/x.xlsx")
os.environ.setdefault("WC_URL", "http://wc.example.invalid")
os.environ.setdefault("WC_KEY", "ck_test")
os.environ.setdefault("WC_SECRET", "cs_test")
os.environ.setdefault("SUPER_ADMIN_USERS", "testadmin730ar1")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models import ProductCache  # noqa: E402

# Ensure tables exist for in-process SQLite (app.main would do this at startup)
Base.metadata.create_all(bind=engine)
from app.services.product_cache import propagate_parent_metadata_to_children  # noqa: E402
from app.services.woocommerce import (  # noqa: E402
    check_variation_filter_capability,
    reset_wc_capability_cache,
)


# ── DB helpers ────────────────────────────────────────────────────────────────

def _now():
    return datetime.utcnow()


def _make_parent_row(db, wc_id, name="Parent", categories='[{"id":10,"name":"Cat A"}]',
                     brand_id=1, brand_name="BrandX", image_url="http://img/p.jpg",
                     image_source="simple"):
    row = ProductCache(
        wc_id=wc_id, parent_id=0, product_type="variable",
        name=name, categories=categories,
        brand_id=brand_id, brand_name=brand_name,
        image_url=image_url, image_source=image_source,
        last_synced_at=_now(), last_seen_at=_now(), cache_version=1,
    )
    db.add(row)
    db.commit()
    return row


def _make_child_row(db, wc_id, parent_id, name="Parent", categories='[{"id":10,"name":"Cat A"}]',
                    brand_id=1, brand_name="BrandX",
                    image_url="http://img/p.jpg", image_source="parent"):
    row = ProductCache(
        wc_id=wc_id, parent_id=parent_id, product_type="variation",
        name=name, categories=categories,
        brand_id=brand_id, brand_name=brand_name,
        image_url=image_url, image_source=image_source,
        last_synced_at=_now(), last_seen_at=_now(), cache_version=1,
    )
    db.add(row)
    db.commit()
    return row


def _cleanup(db, *wc_ids):
    db.query(ProductCache).filter(ProductCache.wc_id.in_(wc_ids)).delete()
    db.commit()


# ── P1: Name propagation ──────────────────────────────────────────────────────

def test_propagate_updates_name_on_children():
    db = SessionLocal()
    try:
        _make_parent_row(db, wc_id=5001, name="New Parent Name")
        _make_child_row(db, wc_id=5002, parent_id=5001, name="Old Name")

        count = propagate_parent_metadata_to_children(db, [5001])
        db.commit()

        child = db.query(ProductCache).filter(ProductCache.wc_id == 5002).first()
        assert child.name == "New Parent Name", f"Expected name propagated, got: {child.name!r}"
        assert count == 1
    finally:
        _cleanup(db, 5001, 5002)
        db.close()


# ── P2: Categories propagation ────────────────────────────────────────────────

def test_propagate_updates_categories_on_children():
    db = SessionLocal()
    new_cats = '[{"id":20,"name":"Cat B"}]'
    try:
        _make_parent_row(db, wc_id=5003, categories=new_cats)
        _make_child_row(db, wc_id=5004, parent_id=5003, categories='[{"id":10,"name":"Cat A"}]')

        count = propagate_parent_metadata_to_children(db, [5003])
        db.commit()

        child = db.query(ProductCache).filter(ProductCache.wc_id == 5004).first()
        assert child.categories == new_cats, f"Categories not propagated: {child.categories!r}"
        assert count == 1
    finally:
        _cleanup(db, 5003, 5004)
        db.close()


# ── P3: Brand propagation ─────────────────────────────────────────────────────

def test_propagate_updates_brand_on_children():
    db = SessionLocal()
    try:
        _make_parent_row(db, wc_id=5005, brand_id=99, brand_name="NewBrand")
        _make_child_row(db, wc_id=5006, parent_id=5005, brand_id=1, brand_name="OldBrand")

        count = propagate_parent_metadata_to_children(db, [5005])
        db.commit()

        child = db.query(ProductCache).filter(ProductCache.wc_id == 5006).first()
        assert child.brand_id == 99, f"brand_id not propagated: {child.brand_id}"
        assert child.brand_name == "NewBrand", f"brand_name not propagated: {child.brand_name!r}"
        assert count == 1
    finally:
        _cleanup(db, 5005, 5006)
        db.close()


# ── P4: Inherited image propagation ──────────────────────────────────────────

def test_propagate_updates_inherited_image_on_children():
    db = SessionLocal()
    try:
        _make_parent_row(db, wc_id=5007, image_url="http://img/new.jpg", image_source="simple")
        _make_child_row(db, wc_id=5008, parent_id=5007,
                        image_url="http://img/old.jpg", image_source="parent")

        count = propagate_parent_metadata_to_children(db, [5007])
        db.commit()

        child = db.query(ProductCache).filter(ProductCache.wc_id == 5008).first()
        assert child.image_url == "http://img/new.jpg", (
            f"Expected new parent image, got: {child.image_url!r}"
        )
        assert child.image_source == "parent"
        assert count == 1
    finally:
        _cleanup(db, 5007, 5008)
        db.close()


# ── P5: Own variation image is NOT overwritten ────────────────────────────────

def test_propagate_does_not_overwrite_own_variation_image():
    db = SessionLocal()
    try:
        _make_parent_row(db, wc_id=5009, image_url="http://img/parent.jpg")
        _make_child_row(db, wc_id=5010, parent_id=5009,
                        image_url="http://img/own-variation.jpg", image_source="variation")

        propagate_parent_metadata_to_children(db, [5009])
        db.commit()

        child = db.query(ProductCache).filter(ProductCache.wc_id == 5010).first()
        assert child.image_url == "http://img/own-variation.jpg", (
            f"Own variation image should NOT be overwritten, got: {child.image_url!r}"
        )
        assert child.image_source == "variation"
    finally:
        _cleanup(db, 5009, 5010)
        db.close()


# ── P6: No WooCommerce call ───────────────────────────────────────────────────

def test_propagate_makes_no_wc_call():
    db = SessionLocal()
    try:
        _make_parent_row(db, wc_id=5011, name="Updated")
        _make_child_row(db, wc_id=5012, parent_id=5011, name="Old")

        with patch("httpx.AsyncClient") as mock_client_cls:
            propagate_parent_metadata_to_children(db, [5011])

        mock_client_cls.assert_not_called(), (
            "propagate_parent_metadata_to_children must not create any httpx.AsyncClient"
        )
    finally:
        _cleanup(db, 5011, 5012)
        db.close()


# ── P7: Returns count of changed rows ────────────────────────────────────────

def test_propagate_returns_count_of_changed_rows():
    db = SessionLocal()
    try:
        _make_parent_row(db, wc_id=5013, name="Parent X", brand_id=7, brand_name="Brand7")
        # Child 1 — different name → will change
        _make_child_row(db, wc_id=5014, parent_id=5013, name="Stale Name", brand_id=7, brand_name="Brand7")
        # Child 2 — already in sync → no change
        _make_child_row(db, wc_id=5015, parent_id=5013, name="Parent X", brand_id=7, brand_name="Brand7",
                        image_url="http://img/p.jpg", image_source="parent")

        count = propagate_parent_metadata_to_children(db, [5013])
        db.commit()

        assert count == 1, f"Expected exactly 1 changed row, got {count}"
    finally:
        _cleanup(db, 5013, 5014, 5015)
        db.close()


# ── C1: Capability guard — schema confirms filter supported ──────────────────

def test_capability_guard_returns_true_when_filter_works():
    """Guard returns True when OPTIONS schema declares modified_after as a GET arg."""
    reset_wc_capability_cache()
    db = SessionLocal()
    try:
        db.query(ProductCache).delete()
        parent = ProductCache(
            wc_id=6001, parent_id=0, product_type="variable",
            last_synced_at=_now(), last_seen_at=_now(), cache_version=1,
        )
        db.add(parent)
        db.commit()

        options_resp = MagicMock(spec=httpx.Response)
        options_resp.status_code = 200
        options_resp.json.return_value = {
            "routes": {
                "/wc/v3/products/(?P<id>[\\d]+)/variations": {
                    "endpoints": [
                        {"methods": ["GET"], "args": {"modified_after": {}, "per_page": {}}}
                    ]
                }
            }
        }

        client_mock = MagicMock(spec=httpx.AsyncClient)
        client_mock.options = AsyncMock(return_value=options_resp)
        client_mock.__aenter__ = AsyncMock(return_value=client_mock)
        client_mock.__aexit__ = AsyncMock(return_value=False)

        async def run():
            with patch("httpx.AsyncClient", return_value=client_mock):
                return await check_variation_filter_capability(db)

        result = asyncio.run(run())
        assert result is True, f"Expected True (schema confirms modified_after), got {result!r}"
    finally:
        db.query(ProductCache).filter(ProductCache.wc_id.in_([6001])).delete()
        db.commit()
        db.close()
        reset_wc_capability_cache()


# ── C2: Capability guard — schema missing modified_after → False ──────────────

def test_capability_guard_returns_false_when_filter_ignored():
    """Guard returns False when OPTIONS schema does not list modified_after."""
    reset_wc_capability_cache()
    db = SessionLocal()
    try:
        db.query(ProductCache).delete()
        parent = ProductCache(
            wc_id=6002, parent_id=0, product_type="variable",
            last_synced_at=_now(), last_seen_at=_now(), cache_version=1,
        )
        db.add(parent)
        db.commit()

        options_resp = MagicMock(spec=httpx.Response)
        options_resp.status_code = 200
        options_resp.json.return_value = {
            "routes": {
                "/wc/v3/products/(?P<id>[\\d]+)/variations": {
                    "endpoints": [
                        {"methods": ["GET"], "args": {"per_page": {}, "page": {}}}
                        # modified_after intentionally absent
                    ]
                }
            }
        }

        client_mock = MagicMock(spec=httpx.AsyncClient)
        client_mock.options = AsyncMock(return_value=options_resp)
        client_mock.__aenter__ = AsyncMock(return_value=client_mock)
        client_mock.__aexit__ = AsyncMock(return_value=False)

        async def run():
            with patch("httpx.AsyncClient", return_value=client_mock):
                return await check_variation_filter_capability(db)

        result = asyncio.run(run())
        assert result is False, f"Expected False (schema missing modified_after), got {result!r}"
    finally:
        db.query(ProductCache).filter(ProductCache.wc_id.in_([6002])).delete()
        db.commit()
        db.close()
        reset_wc_capability_cache()


# ── C3: Capability result is cached ──────────────────────────────────────────

def test_capability_guard_cached_after_first_check():
    """OPTIONS probe is made only once; subsequent calls use the cached result."""
    reset_wc_capability_cache()
    db = SessionLocal()
    try:
        db.query(ProductCache).delete()
        parent = ProductCache(
            wc_id=6003, parent_id=0, product_type="variable",
            last_synced_at=_now(), last_seen_at=_now(), cache_version=1,
        )
        db.add(parent)
        db.commit()

        call_count = [0]

        async def _fake_options(*args, **kwargs):
            call_count[0] += 1
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.json.return_value = {
                "routes": {
                    "/wc/v3/products/(?P<id>[\\d]+)/variations": {
                        "endpoints": [
                            {"methods": ["GET"], "args": {"modified_after": {}}}
                        ]
                    }
                }
            }
            return resp

        client_mock = MagicMock(spec=httpx.AsyncClient)
        client_mock.options = AsyncMock(side_effect=_fake_options)
        client_mock.__aenter__ = AsyncMock(return_value=client_mock)
        client_mock.__aexit__ = AsyncMock(return_value=False)

        async def run():
            with patch("httpx.AsyncClient", return_value=client_mock):
                r1 = await check_variation_filter_capability(db)
                r2 = await check_variation_filter_capability(db)
                return r1, r2

        r1, r2 = asyncio.run(run())
        assert r1 is True
        assert r2 is True
        assert call_count[0] == 1, (
            f"WC OPTIONS should only be called once (result cached); called {call_count[0]} time(s)"
        )
    finally:
        db.query(ProductCache).filter(ProductCache.wc_id.in_([6003])).delete()
        db.commit()
        db.close()
        reset_wc_capability_cache()
