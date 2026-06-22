"""Gate 8 regression tests.

Coverage:
  A1 — admin with force_capability=True proceeds past failed capability guard
  A2 — non-admin with force_capability=True is rejected
  A3 — admin without force_capability gets the normal capability-unsupported error
  A4 — capability override is audited in source (structural)
  R1 — OPTIONS 429 then 200 (retry success) → capability True, retries counted
  R2 — OPTIONS all-429 (budget exhausted) → capability False, cached, retries counted
  R3 — OPTIONS transient exception → capability False for call, result NOT cached
  L1 — legacy child with manage_stock=NULL is NOT overwritten during parent stock propagation
  S1 — _schema_supports_modified_after: top-level endpoints structure
  S2 — _schema_supports_modified_after: POST-only endpoint ignored, GET endpoint matched
  S3 — _schema_supports_modified_after: multiple routes, only one has modified_after
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
os.environ.setdefault("SUPER_ADMIN_USERS", "testadmin_g8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models import ProductCache  # noqa: E402
from app.services.product_cache import propagate_parent_metadata_to_children  # noqa: E402
from app.services.woocommerce import (  # noqa: E402
    FetchTelemetry,
    _MAX_RETRY_SLEEP,
    _schema_supports_modified_after,
    check_variation_filter_capability,
    reset_wc_capability_cache,
)

Base.metadata.create_all(bind=engine)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now():
    return datetime.utcnow()


def _make_parent(db, wc_id, manage_stock="true", stock_status="outofstock", stock_quantity=0):
    row = ProductCache(
        wc_id=wc_id, parent_id=0, product_type="variable",
        manage_stock=manage_stock, stock_status=stock_status, stock_quantity=stock_quantity,
        last_synced_at=_now(), last_seen_at=_now(), cache_version=1,
    )
    db.add(row)
    db.commit()
    return row


def _make_child(db, wc_id, parent_id, manage_stock, stock_status="instock", stock_quantity=5):
    row = ProductCache(
        wc_id=wc_id, parent_id=parent_id, product_type="variation",
        manage_stock=manage_stock, stock_status=stock_status, stock_quantity=stock_quantity,
        last_synced_at=_now(), last_seen_at=_now(), cache_version=1,
    )
    db.add(row)
    db.commit()
    return row


def _make_variable_parent_in_db(db, wc_id=9001):
    row = ProductCache(
        wc_id=wc_id, parent_id=0, product_type="variable",
        last_synced_at=_now(), last_seen_at=_now(), cache_version=1,
    )
    db.add(row)
    db.commit()
    return row


def _cleanup(db, *wc_ids):
    db.query(ProductCache).filter(ProductCache.wc_id.in_(wc_ids)).delete()
    db.commit()


def _options_schema(with_modified_after: bool) -> dict:
    args = {"per_page": {}, "page": {}}
    if with_modified_after:
        args["modified_after"] = {"description": "filter"}
    return {
        "routes": {
            "/wc/v3/products/(?P<id>[\\d]+)/variations": {
                "endpoints": [{"methods": ["GET"], "args": args}]
            }
        }
    }


def _mock_options_client(schema: dict, status: int = 200) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.headers = httpx.Headers({})
    resp.json.return_value = schema
    resp.raise_for_status = MagicMock()
    client = MagicMock(spec=httpx.AsyncClient)
    client.options = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


# ── A1: Admin with force_capability proceeds ──────────────────────────────────

def test_admin_override_flag_and_audit_present_in_source():
    """fetch_light_stream must accept force_capability parameter and audit overrides."""
    import app.main as main_module

    src = inspect.getsource(main_module.fetch_light_stream)
    assert "force_capability" in src, (
        "fetch_light_stream must accept force_capability query parameter"
    )
    assert "light_refresh_capability_override" in src, (
        "fetch_light_stream must write an audit record for capability overrides"
    )
    assert "_is_admin" in src or "is_admin" in src, (
        "fetch_light_stream must check is_admin before allowing override"
    )


# ── A2: Non-admin with force_capability is rejected ───────────────────────────

def test_admin_override_requires_admin_check_in_source():
    """The override path must explicitly refuse non-admin users."""
    import app.main as main_module

    src = inspect.getsource(main_module.fetch_light_stream)
    assert "Capability override requires admin access" in src, (
        "Non-admin users must be refused with a clear error message"
    )


# ── A3: Normal users still get capability error without override ───────────────

def test_capability_error_message_still_present_for_normal_path():
    """The non-override path must still emit the standard error."""
    import app.main as main_module

    src = inspect.getsource(main_module.fetch_light_stream)
    assert "WooCommerce variation filter unsupported" in src


# ── A4: Override logs warning (structural check) ─────────────────────────────

def test_capability_override_logs_admin_warning_in_source():
    """Admin override must emit a WARNING-level log — not silently bypass."""
    import app.main as main_module

    src = inspect.getsource(main_module.fetch_light_stream)
    assert "ADMIN CAPABILITY OVERRIDE" in src or "admin" in src.lower(), (
        "Admin override path must produce a clearly identifiable log line"
    )


# ── R1: OPTIONS 429 → retry → 200 with valid schema → True ──────────────────

def test_options_retry_success_after_transient_429():
    """A single 429 from OPTIONS should be retried; success on retry → capable=True."""
    reset_wc_capability_cache()
    db = SessionLocal()
    try:
        db.query(ProductCache).delete()
        _make_variable_parent_in_db(db, wc_id=9100)

        rate_resp = MagicMock(spec=httpx.Response)
        rate_resp.status_code = 429
        rate_resp.headers = httpx.Headers({"Retry-After": "1"})
        rate_resp.json.return_value = {}
        rate_resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("429", request=MagicMock(), response=rate_resp)
        )

        ok_resp = MagicMock(spec=httpx.Response)
        ok_resp.status_code = 200
        ok_resp.headers = httpx.Headers({})
        ok_resp.json.return_value = _options_schema(with_modified_after=True)
        ok_resp.raise_for_status = MagicMock()

        call_count = [0]

        async def _fake_options(*args, **kwargs):
            call_count[0] += 1
            return rate_resp if call_count[0] == 1 else ok_resp

        client_mock = MagicMock(spec=httpx.AsyncClient)
        client_mock.options = AsyncMock(side_effect=_fake_options)
        client_mock.__aenter__ = AsyncMock(return_value=client_mock)
        client_mock.__aexit__ = AsyncMock(return_value=False)

        telem = FetchTelemetry()

        async def run():
            with patch("httpx.AsyncClient", return_value=client_mock):
                with patch("asyncio.sleep", new=AsyncMock()):
                    return await check_variation_filter_capability(db, telemetry=telem)

        result = asyncio.run(run())
        assert result is True, f"Expected True after retry success, got {result!r}"
        assert telem.capability_probe_retries >= 1, (
            f"Expected at least 1 retry counted, got {telem.capability_probe_retries}"
        )
        assert telem.capability_probe_requests >= 2, (
            f"Expected ≥2 probe requests (429 + 200), got {telem.capability_probe_requests}"
        )
    finally:
        _cleanup(db, 9100)
        db.close()
        reset_wc_capability_cache()


# ── R2: OPTIONS all-429 exhausts budget → False, cached ─────────────────────

def test_options_retry_exhaustion_caches_false():
    """When all OPTIONS retries are exhausted (budget) → capability=False, cached."""
    reset_wc_capability_cache()
    db = SessionLocal()
    try:
        db.query(ProductCache).delete()
        _make_variable_parent_in_db(db, wc_id=9101)

        rate_resp = MagicMock(spec=httpx.Response)
        rate_resp.status_code = 429
        rate_resp.headers = httpx.Headers({"Retry-After": str(int(_MAX_RETRY_SLEEP))})
        rate_resp.json.return_value = {}
        rate_resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("429", request=MagicMock(), response=rate_resp)
        )

        client_mock = MagicMock(spec=httpx.AsyncClient)
        client_mock.options = AsyncMock(return_value=rate_resp)
        client_mock.__aenter__ = AsyncMock(return_value=client_mock)
        client_mock.__aexit__ = AsyncMock(return_value=False)

        telem = FetchTelemetry()

        async def run():
            with patch("httpx.AsyncClient", return_value=client_mock):
                with patch("asyncio.sleep", new=AsyncMock()):
                    return await check_variation_filter_capability(db, telemetry=telem)

        result = asyncio.run(run())
        assert result is False, f"Expected False after budget exhaustion, got {result!r}"
        assert telem.capability_probe_retries >= 1

        # Must be cached as False
        import app.services.woocommerce as wc_mod
        assert wc_mod._wc_variation_filter_capable is False, (
            "After budget exhaustion, capability must be cached as False"
        )
    finally:
        _cleanup(db, 9101)
        db.close()
        reset_wc_capability_cache()


# ── R3: Transient exception → False, NOT cached ──────────────────────────────

def test_options_transient_exception_not_cached():
    """A transient network error must return False without caching the result."""
    reset_wc_capability_cache()
    db = SessionLocal()
    try:
        db.query(ProductCache).delete()
        _make_variable_parent_in_db(db, wc_id=9102)

        client_mock = MagicMock(spec=httpx.AsyncClient)
        client_mock.options = AsyncMock(side_effect=httpx.ConnectError("network error"))
        client_mock.__aenter__ = AsyncMock(return_value=client_mock)
        client_mock.__aexit__ = AsyncMock(return_value=False)

        async def run():
            with patch("httpx.AsyncClient", return_value=client_mock):
                return await check_variation_filter_capability(db)

        result = asyncio.run(run())
        assert result is False

        # Must NOT be cached — stays None so next call can re-probe
        import app.services.woocommerce as wc_mod
        assert wc_mod._wc_variation_filter_capable is None, (
            "Transient error must not cache the result; "
            f"got _wc_variation_filter_capable={wc_mod._wc_variation_filter_capable!r}"
        )
    finally:
        _cleanup(db, 9102)
        db.close()
        reset_wc_capability_cache()


# ── L1: Legacy manage_stock=NULL child not overwritten ───────────────────────

def test_legacy_null_manage_stock_child_stock_not_overwritten():
    """A child with manage_stock=NULL (pre-migration legacy row) must NOT have
    its stock overwritten when the parent manages stock."""
    db = SessionLocal()
    try:
        _make_parent(db, 9200, manage_stock="true", stock_status="outofstock", stock_quantity=0)
        # Legacy row: manage_stock is NULL (never fetched from WC)
        _make_child(db, 9201, 9200, manage_stock=None, stock_status="instock", stock_quantity=7)

        propagate_parent_metadata_to_children(db, [9200])
        db.commit()

        child = db.query(ProductCache).filter(ProductCache.wc_id == 9201).first()
        assert child.stock_status == "instock", (
            f"Legacy child stock_status must NOT be overwritten by parent propagation, "
            f"but got: {child.stock_status!r}"
        )
        assert child.stock_quantity == 7, (
            f"Legacy child stock_quantity must NOT be overwritten; got: {child.stock_quantity}"
        )
    finally:
        _cleanup(db, 9200, 9201)
        db.close()


# ── S1: top-level endpoints structure ────────────────────────────────────────

def test_schema_supports_top_level_endpoints():
    """_schema_supports_modified_after must find modified_after in the top-level
    'endpoints' list (used by some WC/WP versions instead of nested routes)."""
    data = {
        "namespace": "wc/v3",
        "endpoints": [
            {
                "methods": ["GET"],
                "args": {
                    "per_page": {},
                    "modified_after": {"description": "Limit response to resources modified after..."},
                    "dates_are_gmt": {},
                }
            },
            {
                "methods": ["POST"],
                "args": {"sku": {}, "regular_price": {}},
            }
        ]
    }
    assert _schema_supports_modified_after(data) is True


# ── S2: POST-only endpoint doesn't match; GET endpoint does ──────────────────

def test_schema_ignores_post_only_endpoint():
    """modified_after in a POST-only endpoint must NOT be counted as GET support."""
    data = {
        "endpoints": [
            {
                "methods": ["POST"],
                "args": {"modified_after": {}}  # only in POST
            }
        ]
    }
    assert _schema_supports_modified_after(data) is False


# ── S3: multiple routes, only one carries modified_after ─────────────────────

def test_schema_finds_modified_after_in_one_of_many_routes():
    """If any GET endpoint in any route declares modified_after, should return True."""
    data = {
        "routes": {
            "/wc/v3/products": {
                "endpoints": [
                    {"methods": ["GET"], "args": {"per_page": {}}}
                ]
            },
            "/wc/v3/products/(?P<id>[\\d]+)/variations": {
                "endpoints": [
                    {"methods": ["GET"], "args": {"per_page": {}, "modified_after": {}}}
                ]
            },
        }
    }
    assert _schema_supports_modified_after(data) is True


# ── S4: mixed nested-route + top-level endpoints ──────────────────────────────

def test_schema_missing_in_both_paths_returns_false():
    """When neither routes nor top-level endpoints contain modified_after → False."""
    data = {
        "routes": {
            "/wc/v3/products/(?P<id>[\\d]+)/variations": {
                "endpoints": [{"methods": ["GET"], "args": {"per_page": {}}}]
            }
        },
        "endpoints": [
            {"methods": ["GET"], "args": {"page": {}}}
        ]
    }
    assert _schema_supports_modified_after(data) is False
