"""Project 7.3A — Light Refresh optimization + watermark safety regression tests.

Coverage:
  L1 — fetch_products_light does NOT crawl all variations; only modified ones
  L2 — modified_after is passed to variation fetch call
  L3 — dates_are_gmt=true is passed to variation fetch call
  L4 — Deep Sync still crawls all variations via fetch_all_products_full
  L5 — FetchTelemetry retry_count / retry_sleep_s are populated on retry
  L6 — Degraded warning logged when retries happen in light fetch
  L7 — No Apply / Dry Run / Emergency write-path changes
  W1 — get_last_wc_modified_time returns max(date_modified_gmt) from top-level rows
  W2 — get_last_wc_modified_time ignores variation rows (parent_id > 0)
  W3 — get_last_wc_modified_time returns None when cache is empty
"""
import asyncio
import inspect
import os
import sys
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch, call

import httpx
import pytest

# ── Minimal env ───────────────────────────────────────────────────────────────
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("NEXTCLOUD_URL", "http://example.invalid")
os.environ.setdefault("NEXTCLOUD_USER", "x")
os.environ.setdefault("NEXTCLOUD_PASSWORD", "x")
os.environ.setdefault("NEXTCLOUD_FILE_PATH", "/x.xlsx")
os.environ.setdefault("WC_URL", "http://wc.example.invalid")
os.environ.setdefault("WC_KEY", "x")
os.environ.setdefault("WC_SECRET", "x")
os.environ.setdefault("SUPER_ADMIN_USERS", "testadmin730a")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.woocommerce import (  # noqa: E402
    FetchTelemetry,
    _MAX_RETRY_SLEEP,
    _get_with_retry,
    fetch_products_light,
    fetch_all_products_full,
)


# ── Mock helpers ──────────────────────────────────────────────────────────────

def _ok_resp(body: list) -> MagicMock:
    r = MagicMock(spec=httpx.Response)
    r.status_code = 200
    r.headers = httpx.Headers({})
    r.json.return_value = body
    r.raise_for_status = MagicMock()
    return r


def _rate_resp(retry_after: str = "1") -> MagicMock:
    r = MagicMock(spec=httpx.Response)
    r.status_code = 429
    r.headers = httpx.Headers({"Retry-After": retry_after})
    r.json.return_value = {}
    r.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("429", request=MagicMock(), response=r)
    )
    return r


def _make_parent(pid: int, name: str = "Var Parent") -> dict:
    return {
        "id": pid, "name": name, "type": "variable",
        "sku": f"P{pid}", "regular_price": "10", "sale_price": "", "price": "10",
        "stock_status": "instock", "stock_quantity": 5,
        "categories": [], "brands": [], "attributes": [],
        "date_modified_gmt": "2024-06-01T10:00:00",
        "status": "publish", "images": [],
    }


def _make_variation(vid: int, parent_id: int) -> dict:
    return {
        "id": vid, "sku": f"V{vid}",
        "regular_price": "10", "sale_price": "", "price": "10",
        "stock_status": "instock", "stock_quantity": 1,
        "date_modified_gmt": "2024-06-01T10:05:00",
        "image": {},
    }


# ── L1: Light Refresh does NOT crawl all variations ──────────────────────────

def test_light_fetch_uses_modified_after_filter_on_variations():
    """fetch_products_light must pass modified_after to the variation endpoint,
    not crawl all variations (which is what fetch_all_products_full does)."""
    parent = _make_parent(pid=100)
    var = _make_variation(vid=200, parent_id=100)

    calls_made: list[tuple] = []

    async def _fake_get(url: str, **kwargs):
        params = kwargs.get("params", {})
        calls_made.append((url, dict(params)))
        if "/variations" in url:
            # First page has 1 modified variation, second page empty
            if params.get("page", "1") == "1":
                return _ok_resp([var])
            return _ok_resp([])
        # Top-level products
        if params.get("page", "1") == "1":
            return _ok_resp([parent])
        return _ok_resp([])

    client_mock = MagicMock(spec=httpx.AsyncClient)
    client_mock.get = AsyncMock(side_effect=_fake_get)
    client_mock.__aenter__ = AsyncMock(return_value=client_mock)
    client_mock.__aexit__ = AsyncMock(return_value=False)

    async def run():
        with patch("httpx.AsyncClient", return_value=client_mock):
            return await fetch_products_light("2024-06-01T00:00:00", "2024-06-01T23:59:59")

    products, warnings = asyncio.run(run())

    # Verify variation call included modified_after
    var_calls = [c for c in calls_made if "/variations" in c[0]]
    assert var_calls, "Expected at least one variation API call"
    for url, params in var_calls:
        assert "modified_after" in params, (
            f"Variation call missing modified_after: {params}"
        )


# ── L2: modified_after passed to variation fetch ──────────────────────────────

def test_light_fetch_passes_modified_after_to_variations():
    """The modified_after parameter sent to /variations must match the one passed to fetch_products_light."""
    parent = _make_parent(pid=101)
    captured_params: list[dict] = []

    async def _fake_get(url: str, **kwargs):
        params = kwargs.get("params", {})
        captured_params.append(dict(params))
        if "/variations" in url:
            return _ok_resp([])
        if params.get("page", "1") == "1":
            return _ok_resp([parent])
        return _ok_resp([])

    client_mock = MagicMock(spec=httpx.AsyncClient)
    client_mock.get = AsyncMock(side_effect=_fake_get)
    client_mock.__aenter__ = AsyncMock(return_value=client_mock)
    client_mock.__aexit__ = AsyncMock(return_value=False)

    watermark = "2024-05-15T08:00:00"

    async def run():
        with patch("httpx.AsyncClient", return_value=client_mock):
            return await fetch_products_light(watermark, "2024-05-15T09:00:00")

    asyncio.run(run())
    var_calls = [p for p in captured_params if "modified_after" in p and "per_page" in p]
    assert any(p.get("modified_after") == watermark for p in var_calls), (
        f"modified_after={watermark!r} not found in variation calls. Got: {var_calls}"
    )


# ── L3: dates_are_gmt=true passed ────────────────────────────────────────────

def test_light_fetch_passes_dates_are_gmt_to_all_calls():
    """Both top-level and variation WC calls must include dates_are_gmt=true."""
    parent = _make_parent(pid=102)
    all_params: list[dict] = []

    async def _fake_get(url: str, **kwargs):
        all_params.append(dict(kwargs.get("params", {})))
        if "/variations" in url:
            return _ok_resp([])
        if kwargs.get("params", {}).get("page", "1") == "1":
            return _ok_resp([parent])
        return _ok_resp([])

    client_mock = MagicMock(spec=httpx.AsyncClient)
    client_mock.get = AsyncMock(side_effect=_fake_get)
    client_mock.__aenter__ = AsyncMock(return_value=client_mock)
    client_mock.__aexit__ = AsyncMock(return_value=False)

    async def run():
        with patch("httpx.AsyncClient", return_value=client_mock):
            return await fetch_products_light("2024-01-01T00:00:00", "2024-01-02T00:00:00")

    asyncio.run(run())
    for params in all_params:
        assert params.get("dates_are_gmt") == "true", (
            f"dates_are_gmt missing or wrong in call: {params}"
        )


# ── L4: Deep Sync still crawls all variations ─────────────────────────────────

def test_deep_sync_crawls_all_variations_without_modified_filter():
    """fetch_all_products_full must NOT pass modified_after to variation calls."""
    all_params: list[dict] = []
    parent = _make_parent(pid=103)
    var = _make_variation(vid=203, parent_id=103)

    async def _fake_get(url: str, **kwargs):
        params = dict(kwargs.get("params", {}))
        all_params.append(params)
        if "/variations" in url:
            if params.get("page", "1") == "1":
                return _ok_resp([var])
            return _ok_resp([])
        if params.get("page", "1") == "1":
            return _ok_resp([parent])
        return _ok_resp([])

    client_mock = MagicMock(spec=httpx.AsyncClient)
    client_mock.get = AsyncMock(side_effect=_fake_get)
    client_mock.__aenter__ = AsyncMock(return_value=client_mock)
    client_mock.__aexit__ = AsyncMock(return_value=False)

    async def run():
        with patch("httpx.AsyncClient", return_value=client_mock):
            return await fetch_all_products_full()

    products, warnings = asyncio.run(run())
    var_calls = [p for p in all_params if "modified_after" not in p and "per_page" in p]
    var_api_calls = [p for p in all_params if "modified_after" in p]
    assert not var_api_calls, (
        f"fetch_all_products_full must not pass modified_after to any call, but found: {var_api_calls}"
    )


# ── L5: Telemetry retry_count / retry_sleep_s populated on retry ─────────────

def test_telemetry_retry_count_incremented():
    """_get_with_retry must increment telemetry.retry_count and retry_sleep_s on a retry."""
    ok_resp = MagicMock(spec=httpx.Response)
    ok_resp.status_code = 200
    ok_resp.headers = httpx.Headers({})
    ok_resp.json.return_value = []
    ok_resp.raise_for_status = MagicMock()

    rate_resp = MagicMock(spec=httpx.Response)
    rate_resp.status_code = 429
    rate_resp.headers = httpx.Headers({"Retry-After": "2"})
    rate_resp.json.return_value = {}
    rate_resp.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("429", request=MagicMock(), response=rate_resp)
    )

    call_count = [0]

    async def _fake_get(*args, **kwargs):
        call_count[0] += 1
        return rate_resp if call_count[0] == 1 else ok_resp

    client = MagicMock(spec=httpx.AsyncClient)
    client.get = AsyncMock(side_effect=_fake_get)
    telem = FetchTelemetry()

    async def run():
        with patch("asyncio.sleep", new=AsyncMock()):
            await _get_with_retry(client, "http://wc.example.invalid/products", telemetry=telem)

    asyncio.run(run())
    assert telem.retry_count == 1, f"Expected retry_count=1, got {telem.retry_count}"
    assert telem.retry_sleep_s > 0, f"Expected retry_sleep_s > 0, got {telem.retry_sleep_s}"


# ── L6: Degraded warning emitted when light fetch retried ────────────────────

def test_light_stream_logs_degraded_event_on_retries():
    """The light SSE route must emit event=wc_fetch_degraded to the log when
    the fetch completed with retries."""
    import app.main as main_module

    # Verify the structured warning is in the route source
    src = inspect.getsource(main_module.fetch_light_stream)
    assert "wc_fetch_degraded" in src, (
        "fetch_light_stream does not emit event=wc_fetch_degraded — "
        "degraded logging was not added"
    )
    assert "mode=light" in src, (
        "fetch_light_stream degraded log must include mode=light"
    )


# ── L7: No write-path changes ─────────────────────────────────────────────────

def test_no_write_path_changes_in_light_route():
    """Light sync must not touch Apply, Dry Run, or Emergency paths."""
    import app.main as main_module

    light_src = inspect.getsource(main_module.fetch_light_stream)
    # None of the write-path functions must be called inside the light route
    assert "batch_update_prices" not in light_src, "Light route must not call batch_update_prices"
    assert "apply_stream" not in light_src.lower(), "Light route must not reference apply_stream"
    assert "emergency" not in light_src.lower(), "Light route must not reference emergency"


# ── W1: get_last_wc_modified_time returns max(date_modified_gmt) ──────────────

def test_get_last_wc_modified_time_returns_max():
    """get_last_wc_modified_time must return the maximum date_modified_gmt from
    top-level (parent_id == 0) rows."""
    from app.services.product_cache import get_last_wc_modified_time
    from app.models import ProductCache
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        db.query(ProductCache).delete()
        db.add(ProductCache(
            wc_id=1001, parent_id=0, product_type="simple",
            date_modified_gmt="2024-01-15T10:00:00",
            last_synced_at=datetime.utcnow(), last_seen_at=datetime.utcnow(),
        ))
        db.add(ProductCache(
            wc_id=1002, parent_id=0, product_type="simple",
            date_modified_gmt="2024-03-20T15:30:00",
            last_synced_at=datetime.utcnow(), last_seen_at=datetime.utcnow(),
        ))
        db.commit()

        result = get_last_wc_modified_time(db)
        assert result is not None
        assert result.year == 2024 and result.month == 3 and result.day == 20
    finally:
        db.query(ProductCache).filter(ProductCache.wc_id.in_([1001, 1002])).delete()
        db.commit()
        db.close()


# ── W2: get_last_wc_modified_time ignores variation rows ──────────────────────

def test_get_last_wc_modified_time_ignores_variations():
    """Variation rows (parent_id > 0) must not affect the watermark."""
    from app.services.product_cache import get_last_wc_modified_time
    from app.models import ProductCache
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        db.query(ProductCache).delete()
        # Variation with a NEWER date — must be ignored
        db.add(ProductCache(
            wc_id=2001, parent_id=999, product_type="variation",
            date_modified_gmt="2024-12-31T23:59:59",
            last_synced_at=datetime.utcnow(), last_seen_at=datetime.utcnow(),
        ))
        # Top-level parent with an OLDER date — this is what should be returned
        db.add(ProductCache(
            wc_id=2002, parent_id=0, product_type="variable",
            date_modified_gmt="2024-06-01T08:00:00",
            last_synced_at=datetime.utcnow(), last_seen_at=datetime.utcnow(),
        ))
        db.commit()

        result = get_last_wc_modified_time(db)
        assert result is not None
        assert result.month == 6, (
            f"Expected month=6 (top-level parent), got month={result.month} "
            f"(variation row should have been ignored)"
        )
    finally:
        db.query(ProductCache).filter(ProductCache.wc_id.in_([2001, 2002])).delete()
        db.commit()
        db.close()


# ── W3: get_last_wc_modified_time returns None for empty cache ────────────────

def test_get_last_wc_modified_time_returns_none_when_empty():
    from app.services.product_cache import get_last_wc_modified_time
    from app.models import ProductCache
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        db.query(ProductCache).delete()
        db.commit()
        result = get_last_wc_modified_time(db)
        assert result is None
    finally:
        db.close()
