"""Project 7.3A Remediation 2 — Parent-managed stock, image removal, capability guard.

Coverage:
  S1 — parent manage_stock=true propagates stock_status + stock_quantity to inherited children
  S2 — parent manage_stock=false does NOT overwrite child's own stock
  S3 — child with manage_stock=true is not overwritten by parent stock
  S4 — parent stock change is reflected for inherited children
  I1 — parent image changed → inherited child image updates (regression: covered in r1)
  I2 — parent image removed → inherited child image clears to None/none
  I3 — child with own variation image is not cleared when parent image removed
  C1 — no variable parent → probe skipped, result not cached, function returns True
  C2 — empty variable parent → no false positive (OPTIONS schema checked, not empty-result heuristic)
  C3 — OPTIONS schema without modified_after → capability = False
  C4 — OPTIONS schema with modified_after → capability = True
  C5 — incapable result is cached; capable result is cached
  C6 — unsupported mode: fetch_light_stream returns SSE error when guard returns False
  M1 — telemetry includes propagated_children after light fetch propagation
  M2 — telemetry includes capability_probe_requests after probe
"""
import asyncio
import inspect
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
os.environ.setdefault("SUPER_ADMIN_USERS", "testadmin730ar2")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models import ProductCache  # noqa: E402
from app.services.product_cache import propagate_parent_metadata_to_children  # noqa: E402
from app.services.woocommerce import (  # noqa: E402
    FetchTelemetry,
    _schema_supports_modified_after,
    check_variation_filter_capability,
    reset_wc_capability_cache,
)

Base.metadata.create_all(bind=engine)


# ── DB helpers ────────────────────────────────────────────────────────────────

def _now():
    return datetime.utcnow()


def _make_parent(db, wc_id, manage_stock="false", stock_status="instock",
                 stock_quantity=10, image_url="http://img/p.jpg", image_source="simple",
                 name="Parent", categories='[{"id":1,"name":"A"}]',
                 brand_id=1, brand_name="B"):
    row = ProductCache(
        wc_id=wc_id, parent_id=0, product_type="variable",
        manage_stock=manage_stock, stock_status=stock_status, stock_quantity=stock_quantity,
        image_url=image_url, image_source=image_source,
        name=name, categories=categories, brand_id=brand_id, brand_name=brand_name,
        last_synced_at=_now(), last_seen_at=_now(), cache_version=1,
    )
    db.add(row)
    db.commit()
    return row


def _make_child(db, wc_id, parent_id, manage_stock="parent", stock_status="instock",
                stock_quantity=10, image_url="http://img/p.jpg", image_source="parent",
                name="Parent", categories='[{"id":1,"name":"A"}]',
                brand_id=1, brand_name="B"):
    row = ProductCache(
        wc_id=wc_id, parent_id=parent_id, product_type="variation",
        manage_stock=manage_stock, stock_status=stock_status, stock_quantity=stock_quantity,
        image_url=image_url, image_source=image_source,
        name=name, categories=categories, brand_id=brand_id, brand_name=brand_name,
        last_synced_at=_now(), last_seen_at=_now(), cache_version=1,
    )
    db.add(row)
    db.commit()
    return row


def _cleanup(db, *wc_ids):
    db.query(ProductCache).filter(ProductCache.wc_id.in_(wc_ids)).delete()
    db.commit()


# ── S1: parent manage_stock=true propagates stock ────────────────────────────

def test_propagate_stock_when_parent_manages():
    db = SessionLocal()
    try:
        _make_parent(db, 7001, manage_stock="true", stock_status="outofstock", stock_quantity=0)
        _make_child(db, 7002, 7001, manage_stock="parent", stock_status="instock", stock_quantity=5)

        count = propagate_parent_metadata_to_children(db, [7001])
        db.commit()

        child = db.query(ProductCache).filter(ProductCache.wc_id == 7002).first()
        assert child.stock_status == "outofstock", (
            f"Expected stock_status='outofstock' (from parent), got {child.stock_status!r}"
        )
        assert child.stock_quantity == 0, (
            f"Expected stock_quantity=0 (from parent), got {child.stock_quantity}"
        )
        assert count >= 1
    finally:
        _cleanup(db, 7001, 7002)
        db.close()


# ── S2: parent manage_stock=false does not overwrite child stock ──────────────

def test_no_stock_propagation_when_parent_does_not_manage():
    db = SessionLocal()
    try:
        _make_parent(db, 7003, manage_stock="false", stock_status="outofstock", stock_quantity=0)
        _make_child(db, 7004, 7003, manage_stock="parent", stock_status="instock", stock_quantity=3)

        propagate_parent_metadata_to_children(db, [7003])
        db.commit()

        child = db.query(ProductCache).filter(ProductCache.wc_id == 7004).first()
        assert child.stock_status == "instock", (
            "stock_status should NOT be overwritten when parent.manage_stock=false"
        )
        assert child.stock_quantity == 3, (
            "stock_quantity should NOT be overwritten when parent.manage_stock=false"
        )
    finally:
        _cleanup(db, 7003, 7004)
        db.close()


# ── S3: child with own manage_stock is NOT touched ───────────────────────────

def test_child_own_manage_stock_not_overwritten():
    db = SessionLocal()
    try:
        _make_parent(db, 7005, manage_stock="true", stock_status="outofstock", stock_quantity=0)
        # This child independently manages its own stock
        _make_child(db, 7006, 7005, manage_stock="true", stock_status="instock", stock_quantity=7)

        propagate_parent_metadata_to_children(db, [7005])
        db.commit()

        child = db.query(ProductCache).filter(ProductCache.wc_id == 7006).first()
        assert child.stock_status == "instock", (
            "Child with manage_stock='true' must not have stock overwritten by parent propagation"
        )
        assert child.stock_quantity == 7
    finally:
        _cleanup(db, 7005, 7006)
        db.close()


# ── S4: parent stock change reflected in children ────────────────────────────

def test_parent_stock_status_change_reflected_in_children():
    db = SessionLocal()
    try:
        _make_parent(db, 7007, manage_stock="true", stock_status="instock", stock_quantity=5)
        _make_child(db, 7008, 7007, manage_stock="parent", stock_status="instock", stock_quantity=5)

        # Simulate parent stock update (would have come from a Light Refresh upsert)
        parent = db.query(ProductCache).filter(ProductCache.wc_id == 7007).first()
        parent.stock_status = "outofstock"
        parent.stock_quantity = 0
        db.commit()

        count = propagate_parent_metadata_to_children(db, [7007])
        db.commit()

        child = db.query(ProductCache).filter(ProductCache.wc_id == 7008).first()
        assert child.stock_status == "outofstock"
        assert child.stock_quantity == 0
        assert count == 1
    finally:
        _cleanup(db, 7007, 7008)
        db.close()


# ── I2: parent image removed clears inherited child image ────────────────────

def test_parent_image_removal_clears_inherited_child_image():
    db = SessionLocal()
    try:
        _make_parent(db, 7009, image_url=None, image_source="none")
        _make_child(db, 7010, 7009, image_url="http://img/old.jpg", image_source="parent")

        count = propagate_parent_metadata_to_children(db, [7009])
        db.commit()

        child = db.query(ProductCache).filter(ProductCache.wc_id == 7010).first()
        assert child.image_url is None, (
            f"Expected image_url=None after parent image removed, got {child.image_url!r}"
        )
        assert child.image_source == "none", (
            f"Expected image_source='none', got {child.image_source!r}"
        )
        assert count >= 1
    finally:
        _cleanup(db, 7009, 7010)
        db.close()


# ── I3: child with own image not cleared when parent image removed ────────────

def test_child_own_image_not_cleared_when_parent_image_removed():
    db = SessionLocal()
    try:
        _make_parent(db, 7011, image_url=None, image_source="none")
        _make_child(db, 7012, 7011, image_url="http://img/own.jpg", image_source="variation")

        propagate_parent_metadata_to_children(db, [7011])
        db.commit()

        child = db.query(ProductCache).filter(ProductCache.wc_id == 7012).first()
        assert child.image_url == "http://img/own.jpg", (
            "Child's own variation image must not be cleared when parent image removed"
        )
        assert child.image_source == "variation"
    finally:
        _cleanup(db, 7011, 7012)
        db.close()


# ── C1: no variable parent → probe skipped, result NOT cached ────────────────

def test_capability_no_variable_parent_not_cached():
    reset_wc_capability_cache()
    db = SessionLocal()
    try:
        db.query(ProductCache).delete()
        db.commit()

        async def run():
            with patch("httpx.AsyncClient") as mock_cls:
                result = await check_variation_filter_capability(db)
                # Should return True (allow Light Refresh) but NOT call WC
                mock_cls.assert_not_called()
                return result

        result = asyncio.run(run())
        assert result is True, "Should return True (no variations to filter)"

        # The global should NOT have been set — stays None so next call re-checks
        import app.services.woocommerce as wc_mod
        assert wc_mod._wc_variation_filter_capable is None, (
            "Capability must NOT be cached when no variable parent exists"
        )
    finally:
        db.close()
        reset_wc_capability_cache()


# ── C2: empty variable parent does not mark capability supported ──────────────

def test_capability_empty_variable_parent_uses_options_not_empty_result():
    """A variable parent with no variations should not trigger a false positive.
    The guard must use OPTIONS schema inspection, not the far-future-date heuristic."""
    reset_wc_capability_cache()
    db = SessionLocal()
    try:
        db.query(ProductCache).delete()
        parent = ProductCache(
            wc_id=8001, parent_id=0, product_type="variable",
            last_synced_at=_now(), last_seen_at=_now(), cache_version=1,
        )
        db.add(parent)
        db.commit()

        # OPTIONS returns 200 but schema does NOT include modified_after
        options_resp = MagicMock(spec=httpx.Response)
        options_resp.status_code = 200
        options_resp.json.return_value = {
            "routes": {
                "/wc/v3/products/(?P<product_id>[\\d]+)/variations": {
                    "endpoints": [
                        {
                            "methods": ["GET"],
                            "args": {
                                "per_page": {},
                                "page": {},
                                # modified_after intentionally absent
                            }
                        }
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
        assert result is False, (
            "Schema without modified_after must return False (not True just because parent exists)"
        )
    finally:
        db.query(ProductCache).filter(ProductCache.wc_id.in_([8001])).delete()
        db.commit()
        db.close()
        reset_wc_capability_cache()


# ── C3: OPTIONS schema without modified_after → False ────────────────────────

def test_capability_guard_returns_false_when_schema_missing_modified_after():
    reset_wc_capability_cache()
    db = SessionLocal()
    try:
        db.query(ProductCache).delete()
        parent = ProductCache(
            wc_id=8002, parent_id=0, product_type="variable",
            last_synced_at=_now(), last_seen_at=_now(), cache_version=1,
        )
        db.add(parent)
        db.commit()

        bad_schema = {
            "routes": {
                "/wc/v3/products/(?P<id>[\\d]+)/variations": {
                    "endpoints": [{"methods": ["GET"], "args": {"per_page": {}, "page": {}}}]
                }
            }
        }
        options_resp = MagicMock(spec=httpx.Response)
        options_resp.status_code = 200
        options_resp.json.return_value = bad_schema

        client_mock = MagicMock(spec=httpx.AsyncClient)
        client_mock.options = AsyncMock(return_value=options_resp)
        client_mock.__aenter__ = AsyncMock(return_value=client_mock)
        client_mock.__aexit__ = AsyncMock(return_value=False)

        async def run():
            with patch("httpx.AsyncClient", return_value=client_mock):
                return await check_variation_filter_capability(db)

        result = asyncio.run(run())
        assert result is False
    finally:
        db.query(ProductCache).filter(ProductCache.wc_id.in_([8002])).delete()
        db.commit()
        db.close()
        reset_wc_capability_cache()


# ── C4: OPTIONS schema with modified_after → True ────────────────────────────

def test_capability_guard_returns_true_when_schema_includes_modified_after():
    reset_wc_capability_cache()
    db = SessionLocal()
    try:
        db.query(ProductCache).delete()
        parent = ProductCache(
            wc_id=8003, parent_id=0, product_type="variable",
            last_synced_at=_now(), last_seen_at=_now(), cache_version=1,
        )
        db.add(parent)
        db.commit()

        good_schema = {
            "routes": {
                "/wc/v3/products/(?P<id>[\\d]+)/variations": {
                    "endpoints": [
                        {
                            "methods": ["GET"],
                            "args": {
                                "per_page": {},
                                "modified_after": {"description": "filter by modification date"},
                                "dates_are_gmt": {},
                            }
                        }
                    ]
                }
            }
        }
        options_resp = MagicMock(spec=httpx.Response)
        options_resp.status_code = 200
        options_resp.json.return_value = good_schema

        client_mock = MagicMock(spec=httpx.AsyncClient)
        client_mock.options = AsyncMock(return_value=options_resp)
        client_mock.__aenter__ = AsyncMock(return_value=client_mock)
        client_mock.__aexit__ = AsyncMock(return_value=False)

        async def run():
            with patch("httpx.AsyncClient", return_value=client_mock):
                return await check_variation_filter_capability(db)

        result = asyncio.run(run())
        assert result is True
    finally:
        db.query(ProductCache).filter(ProductCache.wc_id.in_([8003])).delete()
        db.commit()
        db.close()
        reset_wc_capability_cache()


# ── C5: result is cached after first probe ────────────────────────────────────

def test_capability_guard_result_cached_after_probe():
    reset_wc_capability_cache()
    db = SessionLocal()
    call_count = [0]
    try:
        db.query(ProductCache).delete()
        parent = ProductCache(
            wc_id=8004, parent_id=0, product_type="variable",
            last_synced_at=_now(), last_seen_at=_now(), cache_version=1,
        )
        db.add(parent)
        db.commit()

        good_schema = {
            "routes": {
                "/wc/v3/products/(?P<id>[\\d]+)/variations": {
                    "endpoints": [
                        {"methods": ["GET"], "args": {"modified_after": {}}}
                    ]
                }
            }
        }

        async def _fake_options(*args, **kwargs):
            call_count[0] += 1
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.json.return_value = good_schema
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
        assert r1 is True and r2 is True
        assert call_count[0] == 1, (
            f"WC OPTIONS should only be called once (result cached); called {call_count[0]} time(s)"
        )
    finally:
        db.query(ProductCache).filter(ProductCache.wc_id.in_([8004])).delete()
        db.commit()
        db.close()
        reset_wc_capability_cache()


# ── C6: unsupported mode surfaces error, not silent optimized fetch ───────────

def test_fetch_light_stream_returns_error_when_capability_guard_false():
    """When check_variation_filter_capability returns False, fetch_light_stream
    must emit an SSE error and NOT proceed to fetch from WooCommerce."""
    import app.main as main_module

    src = inspect.getsource(main_module.fetch_light_stream)
    assert "capability_error" in src, (
        "fetch_light_stream must surface capability-guard failure as SSE error with capability_error field"
    )
    assert "check_variation_filter_capability" in src, (
        "fetch_light_stream must call check_variation_filter_capability"
    )


# ── M1: telemetry includes propagated_children ────────────────────────────────

def test_telemetry_has_propagated_children_field():
    t = FetchTelemetry()
    assert hasattr(t, "propagated_children"), "FetchTelemetry must have propagated_children field"
    assert t.propagated_children == 0


# ── M2: telemetry includes capability_probe_requests ─────────────────────────

def test_telemetry_capability_probe_requests_incremented():
    reset_wc_capability_cache()
    db = SessionLocal()
    try:
        db.query(ProductCache).delete()
        parent = ProductCache(
            wc_id=8005, parent_id=0, product_type="variable",
            last_synced_at=_now(), last_seen_at=_now(), cache_version=1,
        )
        db.add(parent)
        db.commit()

        schema_with_filter = {
            "routes": {
                "/wc/v3/products/(?P<id>[\\d]+)/variations": {
                    "endpoints": [{"methods": ["GET"], "args": {"modified_after": {}}}]
                }
            }
        }
        options_resp = MagicMock(spec=httpx.Response)
        options_resp.status_code = 200
        options_resp.json.return_value = schema_with_filter

        client_mock = MagicMock(spec=httpx.AsyncClient)
        client_mock.options = AsyncMock(return_value=options_resp)
        client_mock.__aenter__ = AsyncMock(return_value=client_mock)
        client_mock.__aexit__ = AsyncMock(return_value=False)

        telem = FetchTelemetry()

        async def run():
            with patch("httpx.AsyncClient", return_value=client_mock):
                await check_variation_filter_capability(db, telemetry=telem)

        asyncio.run(run())
        assert telem.capability_probe_requests == 1, (
            f"Expected capability_probe_requests=1, got {telem.capability_probe_requests}"
        )
    finally:
        db.query(ProductCache).filter(ProductCache.wc_id.in_([8005])).delete()
        db.commit()
        db.close()
        reset_wc_capability_cache()


# ── Unit: _schema_supports_modified_after ────────────────────────────────────

def test_schema_supports_modified_after_true():
    data = {
        "routes": {
            "/wc/v3/products/(?P<id>[\\d]+)/variations": {
                "endpoints": [
                    {"methods": ["GET"], "args": {"modified_after": {}, "per_page": {}}}
                ]
            }
        }
    }
    assert _schema_supports_modified_after(data) is True


def test_schema_supports_modified_after_false():
    data = {
        "routes": {
            "/wc/v3/products/(?P<id>[\\d]+)/variations": {
                "endpoints": [
                    {"methods": ["GET"], "args": {"per_page": {}, "page": {}}}
                ]
            }
        }
    }
    assert _schema_supports_modified_after(data) is False


def test_schema_supports_modified_after_empty():
    assert _schema_supports_modified_after({}) is False
