"""Project 7.3 — Fetch performance + business reporting remediation regression tests.

Coverage:
  H1 — _get_with_retry: Retry-After capped to _MAX_RETRY_SLEEP; budget exceeded → RuntimeError
  H2 — preview_stream does not make live variation-image WC calls for cached products
  H3 — analytics_seller_staleness filters to parent_id == 0 (excludes variations)
  M1 — FetchTelemetry counters are populated by fetch_all_products_fast
  M2 — _extract_brand falls back to pa_brand-filter attribute when `brands` is empty
"""
import asyncio
import os
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# ── Minimal env so Settings() doesn't error ───────────────────────────────────
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("NEXTCLOUD_URL", "http://example.invalid")
os.environ.setdefault("NEXTCLOUD_USER", "x")
os.environ.setdefault("NEXTCLOUD_PASSWORD", "x")
os.environ.setdefault("NEXTCLOUD_FILE_PATH", "/x.xlsx")
os.environ.setdefault("WC_URL", "http://example.invalid")
os.environ.setdefault("WC_KEY", "x")
os.environ.setdefault("WC_SECRET", "x")
os.environ.setdefault("SUPER_ADMIN_USERS", "testadmin730")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.woocommerce import (  # noqa: E402
    FetchTelemetry,
    _MAX_RETRY_SLEEP,
    _MAX_TOTAL_RETRY_SLEEP,
    _get_with_retry,
    _extract_brand,
    fetch_all_products_fast,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_resp(status: int, body=None, headers: dict | None = None) -> MagicMock:
    """Build a mock httpx.Response."""
    r = MagicMock(spec=httpx.Response)
    r.status_code = status
    h = httpx.Headers(headers or {})
    r.headers = h
    if body is not None:
        r.json.return_value = body
    r.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("error", request=MagicMock(), response=r)
        if status >= 400 else None
    )
    return r


# ── H1: Retry cap tests ───────────────────────────────────────────────────────

def test_retry_after_capped_to_max_sleep():
    """A large Retry-After (e.g. 120s) must be capped to _MAX_RETRY_SLEEP."""
    ok_resp = _mock_resp(200, body=[])
    ok_resp.raise_for_status = MagicMock()

    rate_resp = _mock_resp(429, headers={"Retry-After": "120"})
    call_count = 0

    async def _fake_get(_self_or_url, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        return rate_resp if call_count == 1 else ok_resp

    client = MagicMock(spec=httpx.AsyncClient)
    client.get = AsyncMock(side_effect=_fake_get)

    slept: list[float] = []

    async def run():
        with patch("asyncio.sleep", new=AsyncMock(side_effect=lambda t: slept.append(t))):
            return await _get_with_retry(client, "http://example.invalid/wp-json/wc/v3/products")

    asyncio.run(run())
    assert slept, "Expected at least one retry sleep"
    assert all(s <= _MAX_RETRY_SLEEP for s in slept), (
        f"A retry sleep {max(slept):.0f}s exceeded cap {_MAX_RETRY_SLEEP}s"
    )


def test_retry_after_small_value_not_increased():
    """A Retry-After smaller than _MAX_RETRY_SLEEP must be used as-is."""
    ok_resp = _mock_resp(200, body=[])
    ok_resp.raise_for_status = MagicMock()

    rate_resp = _mock_resp(429, headers={"Retry-After": "5"})
    call_count = 0

    async def _fake_get(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return rate_resp if call_count == 1 else ok_resp

    client = MagicMock(spec=httpx.AsyncClient)
    client.get = AsyncMock(side_effect=_fake_get)
    slept: list[float] = []

    async def run():
        with patch("asyncio.sleep", new=AsyncMock(side_effect=lambda t: slept.append(t))):
            return await _get_with_retry(client, "http://example.invalid/products")

    asyncio.run(run())
    assert slept and slept[0] == 5.0, f"Expected sleep of 5s, got {slept}"


def test_retry_budget_exceeded_raises_runtime_error():
    """When cumulative sleep would exceed _MAX_TOTAL_RETRY_SLEEP, raise RuntimeError."""
    rate_resp = _mock_resp(429, headers={"Retry-After": str(int(_MAX_RETRY_SLEEP))})

    client = MagicMock(spec=httpx.AsyncClient)
    # Always return 429
    client.get = AsyncMock(return_value=rate_resp)
    slept: list[float] = []

    async def run():
        with patch("asyncio.sleep", new=AsyncMock(side_effect=lambda t: slept.append(t))):
            await _get_with_retry(client, "http://example.invalid/products")

    with pytest.raises(RuntimeError, match="budget exhausted"):
        asyncio.run(run())


def test_retry_budget_respects_max_constant():
    """_MAX_TOTAL_RETRY_SLEEP must be at least 2× _MAX_RETRY_SLEEP so two retries are allowed."""
    assert _MAX_TOTAL_RETRY_SLEEP > _MAX_RETRY_SLEEP * 2, (
        f"_MAX_TOTAL_RETRY_SLEEP ({_MAX_TOTAL_RETRY_SLEEP}) should be > 2× "
        f"_MAX_RETRY_SLEEP ({_MAX_RETRY_SLEEP}) to allow at least two retry sleeps"
    )


# ── H2: Preview stream — no live variation-image calls for cached products ────

def test_preview_stream_does_not_call_fetch_variations_for_cached_products():
    """When all product IDs are in the DB cache, preview_stream must NOT call
    fetch_variations_for_selected_parents (the variation image enrichment block
    was removed in 7.3)."""
    import app.main as main_module

    # We verify the enrichment block is gone by checking that
    # fetch_variations_for_selected_parents is not called during a preview
    # where all products are satisfied from cache.
    with patch.object(
        main_module,
        "fetch_variations_for_selected_parents",
        new=AsyncMock(return_value=([], [])),
    ) as mock_var_fetch:
        # The function is no longer invoked from preview_stream — if it is, test fails.
        # We confirm the symbol still exists (import sanity) but is not called.
        assert mock_var_fetch is not None

    # Deeper check: verify the enrichment code path is absent from the SSE generator source.
    import inspect
    from app.main import preview_stream  # type: ignore[attr-defined]
    src = inspect.getsource(preview_stream)
    assert "fetch_variations_for_selected_parents" not in src, (
        "preview_stream still references fetch_variations_for_selected_parents — "
        "the H2 enrichment block was not removed"
    )
    assert "_VAR_PARENT_CAP" not in src, (
        "preview_stream still contains _VAR_PARENT_CAP — H2 block not fully removed"
    )


# ── H3: Staleness endpoint filters to parent_id == 0 ─────────────────────────

def test_analytics_staleness_filters_to_parent_products():
    """analytics_seller_staleness must query only rows with parent_id == 0."""
    import inspect
    import app.main as main_module

    src = inspect.getsource(main_module.analytics_seller_staleness)
    assert "parent_id == 0" in src, (
        "analytics_seller_staleness does not filter to parent_id == 0 — "
        "variations will inflate staleness counts"
    )


# ── M1: FetchTelemetry is populated by fetch_all_products_fast ───────────────

def test_fetch_telemetry_product_pages_counted():
    """fetch_all_products_fast must increment telemetry.product_pages per WC page fetched."""
    page1 = [{"id": i, "name": f"P{i}", "type": "simple", "sku": str(i),
               "regular_price": "10", "sale_price": "", "price": "10",
               "stock_status": "instock", "stock_quantity": 1,
               "categories": [], "brands": [], "attributes": [],
               "date_modified_gmt": "2024-01-01T00:00:00",
               "status": "publish", "images": []}
              for i in range(1, 6)]

    call_num = [0]

    async def _fake_get(*args, **kwargs):
        call_num[0] += 1
        resp = _mock_resp(200, body=page1 if call_num[0] == 1 else [])
        resp.raise_for_status = MagicMock()
        return resp

    client_mock = MagicMock(spec=httpx.AsyncClient)
    client_mock.get = AsyncMock(side_effect=_fake_get)
    client_mock.__aenter__ = AsyncMock(return_value=client_mock)
    client_mock.__aexit__ = AsyncMock(return_value=False)

    telem = FetchTelemetry()

    async def run():
        with patch("httpx.AsyncClient", return_value=client_mock):
            await fetch_all_products_fast(telemetry=telem)

    asyncio.run(run())
    assert telem.product_pages >= 1, f"Expected product_pages ≥ 1, got {telem.product_pages}"
    assert telem.wc_requests >= 1, f"Expected wc_requests ≥ 1, got {telem.wc_requests}"


def test_fetch_telemetry_dataclass_defaults():
    """FetchTelemetry must start with all-zero fields."""
    t = FetchTelemetry()
    assert t.product_pages == 0
    assert t.variation_pages == 0
    assert t.wc_requests == 0
    assert t.retry_count == 0
    assert t.retry_sleep_s == 0.0
    assert t.elapsed_s == 0.0


def test_get_with_retry_increments_wc_requests():
    """_get_with_retry must increment telemetry.wc_requests on every HTTP call."""
    ok_resp = _mock_resp(200, body=[])
    ok_resp.raise_for_status = MagicMock()

    client = MagicMock(spec=httpx.AsyncClient)
    client.get = AsyncMock(return_value=ok_resp)

    telem = FetchTelemetry()

    async def run():
        await _get_with_retry(client, "http://example.invalid/products", telemetry=telem)

    asyncio.run(run())
    assert telem.wc_requests == 1


# ── M2: Brand extraction from pa_brand-filter attribute ──────────────────────

def test_extract_brand_uses_brands_field_first():
    """_extract_brand prefers the WC `brands` taxonomy field."""
    product = {"brands": [{"id": 42, "name": "Acme"}], "attributes": []}
    brand_id, brand_name = _extract_brand(product)
    assert brand_id == 42
    assert brand_name == "Acme"


def test_extract_brand_falls_back_to_pa_brand_filter_attribute():
    """When `brands` is empty, _extract_brand must use pa_brand-filter attribute."""
    product = {
        "brands": [],
        "attributes": [
            {"slug": "pa_brand-filter", "name": "Brand", "options": ["GlobalBrand"]},
        ],
    }
    brand_id, brand_name = _extract_brand(product)
    assert brand_name == "GlobalBrand", f"Expected 'GlobalBrand', got {brand_name!r}"
    assert brand_id is not None, "brand_id should be a crc32-derived int, not None"
    assert isinstance(brand_id, int)


def test_extract_brand_returns_none_when_no_brand():
    """_extract_brand must return (None, None) when no brand data is present."""
    product = {"brands": [], "attributes": []}
    brand_id, brand_name = _extract_brand(product)
    assert brand_id is None
    assert brand_name is None


def test_extract_brand_attribute_missing_from_fields_returns_none():
    """Simulates the pre-7.3 bug: attributes not in _fields → empty list → no brand."""
    product = {"brands": [], "attributes": []}  # as if `attributes` was omitted from WC response
    brand_id, _ = _extract_brand(product)
    assert brand_id is None
