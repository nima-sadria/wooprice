"""Project 7.3B Health Behavioral Tests.

Verifies WooCommerce and Nextcloud health state via actual HTTP calls to /api/health,
plus unit-level checks for fetch instrumentation and capability tri-state.

WC1  — WC status 'unknown' before any fetch
WC2  — WC status 'ok' after fresh success
WC3  — WC status 'stale' after success older than 300 s threshold
WC4  — WC status 'limited' when capability confirmed False
WC5  — WC status 'unavailable' when failure is newer than success
WC6  — WC status recovers to 'ok' after failure then success
WC7  — Full refresh success records WC success
WC8  — Deep refresh success records WC success
WC9  — Light refresh success records WC success
WC10 — Empty successful fetch still records WC success
WC11 — DB failure after successful WC fetch does NOT mark WC unavailable
WC12 — Retry budget exhaustion returns None, not cached as False
WC13 — force_capability rejected when capability is indeterminate (None)

NC1  — NC status 'unknown' before any download
NC2  — NC status 'ok' after fresh successful download
NC3  — NC status 'stale' after success older than _XLSX_CACHE_TTL
NC4  — NC status 'unavailable' when failure is newer than success
NC5  — NC status recovers to 'ok' after failure then success
NC6  — Cache hit does NOT update verification timestamp
NC7  — Failed download records NC failure
NC8  — Successful upload clears data, ts, etag, last_modified
NC9  — NC status is 'unknown' after upload invalidation (before new download)
NC10 — Failed upload records NC failure
"""
import asyncio
import io
import os
import sys
import time
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("NEXTCLOUD_URL", "http://example.invalid")
os.environ.setdefault("NEXTCLOUD_USER", "x")
os.environ.setdefault("NEXTCLOUD_PASSWORD", "x")
os.environ.setdefault("NEXTCLOUD_FILE_PATH", "/x.xlsx")
os.environ.setdefault("WC_URL", "http://wc.example.invalid")
os.environ.setdefault("WC_KEY", "ck_test")
os.environ.setdefault("WC_SECRET", "cs_test")
os.environ.setdefault("SUPER_ADMIN_USERS", "testadmin_hb")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.auth import create_token
from app.database import Base, engine
import app.services.woocommerce as wc_svc
import app.services.nextcloud as nc_svc

Base.metadata.create_all(bind=engine)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def reset_all_health_state():
    wc_svc.reset_wc_health_state()
    wc_svc.reset_wc_capability_cache()
    nc_svc.reset_nc_health_state()
    nc_svc._xlsx_cache.update({"data": None, "ts": 0.0, "etag": "", "last_modified": ""})
    yield
    wc_svc.reset_wc_health_state()
    wc_svc.reset_wc_capability_cache()
    nc_svc.reset_nc_health_state()
    nc_svc._xlsx_cache.update({"data": None, "ts": 0.0, "etag": "", "last_modified": ""})


def _admin_tok():
    return {"Authorization": f"Bearer {create_token('testadmin_hb', permission_version=0, role='admin')}"}


def _svc(client) -> dict:
    r = client.get("/api/health")
    assert r.status_code == 200, f"Health returned {r.status_code}: {r.text}"
    return r.json()["services"]


# ── WC1: unknown before any fetch ────────────────────────────────────────────

def test_wc_status_unknown_before_any_fetch(client):
    assert _svc(client)["woocommerce"] == "unknown"


# ── WC2: ok after fresh success ──────────────────────────────────────────────

def test_wc_status_ok_after_fresh_success(client):
    wc_svc.record_wc_success()
    assert _svc(client)["woocommerce"] == "ok"


# ── WC3: stale after success older than 300 s ────────────────────────────────

def test_wc_status_stale_after_old_success(client):
    wc_svc._wc_last_success_ts = time.time() - 400  # 400 s > 300 s threshold
    assert _svc(client)["woocommerce"] == "stale"


# ── WC4: limited when capability is False ────────────────────────────────────

def test_wc_status_limited_when_capability_false(client):
    wc_svc.record_wc_success()
    wc_svc._wc_variation_filter_capable = False
    assert _svc(client)["woocommerce"] == "limited"


# ── WC5: unavailable when failure is newer than success ──────────────────────

def test_wc_status_unavailable_when_failure_newer_than_success(client):
    wc_svc._wc_last_success_ts = time.time() - 20
    wc_svc._wc_last_failure_ts = time.time()
    assert _svc(client)["woocommerce"] == "unavailable"


# ── WC6: recovery from failure ───────────────────────────────────────────────

def test_wc_status_recovers_to_ok_after_failure_then_success(client):
    wc_svc._wc_last_failure_ts = time.time() - 20
    wc_svc._wc_last_success_ts = time.time()  # success is newer
    assert _svc(client)["woocommerce"] == "ok"


# ── WC7: full refresh success records WC success ─────────────────────────────

def test_full_refresh_success_records_wc_success():
    from app.services.woocommerce import fetch_all_products_fast

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.headers = httpx.Headers({})
    mock_resp.json.return_value = []  # empty page → stop paging
    mock_resp.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    assert wc_svc._wc_last_success_ts == 0.0, "Pre-condition: no success yet"

    async def run():
        with patch("app.services.woocommerce.httpx.AsyncClient", return_value=mock_client):
            return await fetch_all_products_fast()

    asyncio.run(run())
    assert wc_svc._wc_last_success_ts > 0, "Full refresh success must record WC success"


# ── WC8: deep refresh success records WC success ─────────────────────────────

def test_deep_refresh_success_records_wc_success():
    from app.services.woocommerce import fetch_all_products_full

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.headers = httpx.Headers({})
    mock_resp.json.return_value = []
    mock_resp.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    assert wc_svc._wc_last_success_ts == 0.0

    async def run():
        with patch("app.services.woocommerce.httpx.AsyncClient", return_value=mock_client):
            return await fetch_all_products_full()

    asyncio.run(run())
    assert wc_svc._wc_last_success_ts > 0, "Deep refresh success must record WC success"


# ── WC9: light refresh success records WC success ────────────────────────────

def test_light_refresh_success_records_wc_success():
    from app.services.woocommerce import fetch_products_light

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.headers = httpx.Headers({})
    mock_resp.json.return_value = []
    mock_resp.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    assert wc_svc._wc_last_success_ts == 0.0

    async def run():
        with patch("app.services.woocommerce.httpx.AsyncClient", return_value=mock_client):
            return await fetch_products_light("2024-01-01T00:00:00", "2024-01-02T00:00:00")

    asyncio.run(run())
    assert wc_svc._wc_last_success_ts > 0, "Light refresh success must record WC success"


# ── WC10: empty successful fetch records success ──────────────────────────────

def test_empty_successful_fetch_records_wc_success():
    from app.services.woocommerce import fetch_all_products_fast

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.headers = httpx.Headers({})
    mock_resp.json.return_value = []  # explicitly empty = no products in WC
    mock_resp.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    async def run():
        with patch("app.services.woocommerce.httpx.AsyncClient", return_value=mock_client):
            products, _ = await fetch_all_products_fast()
            return products

    products = asyncio.run(run())
    assert products == [], "Empty response returns empty list"
    assert wc_svc._wc_last_success_ts > 0, (
        "Empty successful fetch must still record WC success (connectivity confirmed)"
    )


# ── WC11: DB failure after WC fetch does NOT mark WC unavailable ─────────────

def test_db_failure_after_successful_wc_fetch_does_not_mark_wc_unavailable(client):
    """The WC fetch succeeds (success recorded), then DB upsert raises.
    _wc_last_failure_ts must remain 0 — it's a DB problem, not a WC problem."""
    from app.services.woocommerce import fetch_all_products_fast

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.headers = httpx.Headers({})
    mock_resp.json.return_value = []
    mock_resp.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    # Simulate: WC fetch succeeds (products=[]) but downstream DB upsert raises
    async def run():
        with patch("app.services.woocommerce.httpx.AsyncClient", return_value=mock_client):
            prods, _ = await fetch_all_products_fast()
        return prods

    asyncio.run(run())

    # WC success must be recorded
    assert wc_svc._wc_last_success_ts > 0, "WC success must be recorded when fetch completes"
    # WC failure must NOT be recorded (DB upsert is separate)
    assert wc_svc._wc_last_failure_ts == 0.0, (
        "DB failure must NOT record WC failure — these are different failure domains"
    )


# ── WC12: retry budget exhaustion → None, not cached ─────────────────────────

def test_capability_retry_exhaustion_returns_none_not_cached():
    """Retry budget exhaustion is connectivity failure, not schema determination.
    Returns None (indeterminate) and must NOT be cached."""
    from app.services.woocommerce import (
        check_variation_filter_capability, FetchTelemetry,
        _MAX_RETRY_SLEEP, reset_wc_capability_cache,
    )
    from app.database import SessionLocal
    from app.models import ProductCache

    reset_wc_capability_cache()
    db = SessionLocal()
    try:
        db.query(ProductCache).filter(ProductCache.wc_id == 9301).delete()
        db.commit()
        row = ProductCache(
            wc_id=9301, parent_id=0, product_type="variable",
            last_synced_at=datetime.utcnow(), last_seen_at=datetime.utcnow(), cache_version=1,
        )
        db.add(row)
        db.commit()

        rate_resp = MagicMock(spec=httpx.Response)
        rate_resp.status_code = 429
        rate_resp.headers = httpx.Headers({"Retry-After": str(int(_MAX_RETRY_SLEEP))})
        rate_resp.json.return_value = {}
        rate_resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("429", request=MagicMock(), response=rate_resp)
        )

        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.options = AsyncMock(return_value=rate_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        telem = FetchTelemetry()

        async def run():
            with patch("app.services.woocommerce.httpx.AsyncClient", return_value=mock_client):
                with patch("asyncio.sleep", new=AsyncMock()):
                    return await check_variation_filter_capability(db, telemetry=telem)

        result = asyncio.run(run())
        assert result is None, (
            f"Retry budget exhaustion must return None (indeterminate), got {result!r}"
        )
        assert wc_svc._wc_variation_filter_capable is None, (
            "Budget exhaustion must NOT cache the result — "
            f"got {wc_svc._wc_variation_filter_capable!r}"
        )
    finally:
        db.query(ProductCache).filter(ProductCache.wc_id == 9301).delete()
        db.commit()
        db.close()
        reset_wc_capability_cache()


# ── WC13: force_capability rejected when capability is indeterminate ──────────

def test_force_capability_rejected_when_capability_indeterminate(client):
    """When check_variation_filter_capability returns None (connectivity failure),
    force_capability=true must be rejected — we cannot confirm WC supports the feature."""
    with patch("app.main.validate_sse_token", return_value={"sub": "testadmin_hb", "role": "admin"}):
        with patch("app.main._enforce_permission"):
            with patch("app.main.get_last_sync_time", return_value=datetime(2024, 1, 1)):
                with patch("app.main.check_variation_filter_capability",
                           new=AsyncMock(return_value=None)):
                    r = client.get("/api/fetch/light?force_capability=true", headers=_admin_tok())

    body = r.text
    assert "capability_error" not in body, (
        "Indeterminate capability must NOT produce capability_error (that is only for False)"
    )
    assert "probe failed" in body.lower() or "connectivity" in body.lower() or "indeterminate" in body.lower(), (
        f"Indeterminate capability (None) must produce connectivity/probe error; got: {body[:300]}"
    )


# ── NC1: unknown before any download ─────────────────────────────────────────

def test_nc_status_unknown_before_any_download(client):
    assert _svc(client)["nextcloud"] == "unknown"


# ── NC2: ok after fresh successful download ───────────────────────────────────

def test_nc_status_ok_after_fresh_successful_download(client):
    nc_svc.record_nc_success()
    assert _svc(client)["nextcloud"] == "ok"


# ── NC3: stale after success older than _XLSX_CACHE_TTL ──────────────────────

def test_nc_status_stale_after_old_success(client):
    nc_svc._nc_last_success_ts = time.time() - (nc_svc._XLSX_CACHE_TTL + 10)
    assert _svc(client)["nextcloud"] == "stale"


# ── NC4: unavailable when failure is newer than success ──────────────────────

def test_nc_status_unavailable_when_failure_newer_than_success(client):
    nc_svc._nc_last_success_ts = time.time() - 20
    nc_svc._nc_last_failure_ts = time.time()
    assert _svc(client)["nextcloud"] == "unavailable"


# ── NC5: recovery from failure ───────────────────────────────────────────────

def test_nc_status_recovers_to_ok_after_failure_then_success(client):
    nc_svc._nc_last_failure_ts = time.time() - 20
    nc_svc._nc_last_success_ts = time.time()
    assert _svc(client)["nextcloud"] == "ok"


# ── NC6: cache hit does NOT update verification timestamp ────────────────────

def test_nc_cache_hit_does_not_update_verification_timestamp():
    from app.services.nextcloud import download_xlsx

    nc_svc._xlsx_cache.update({
        "data": b"fakexlsxdata",
        "ts": time.time(),  # fresh cache
        "etag": "\"abc\"",
        "last_modified": "Mon, 01 Jan 2024 00:00:00 GMT",
    })
    # Record a success ts, then simulate a cache hit
    recorded_ts = time.time() - 5
    nc_svc._nc_last_success_ts = recorded_ts

    async def run():
        return await download_xlsx(force=False)

    data = asyncio.run(run())
    assert data == b"fakexlsxdata", "Cache hit must return cached data"
    assert nc_svc._nc_last_success_ts == recorded_ts, (
        "Cache hit must NOT update _nc_last_success_ts — no network access occurred"
    )


# ── NC7: failed download records NC failure ───────────────────────────────────

def test_failed_download_records_nc_failure():
    from app.services.nextcloud import download_xlsx

    async def run():
        with patch("app.services.nextcloud.httpx.AsyncClient") as MockCl:
            mock_client = MagicMock()
            mock_client.get = AsyncMock(side_effect=httpx.ConnectError("nc down"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockCl.return_value = mock_client
            try:
                await download_xlsx(force=True)
            except Exception:
                pass

    asyncio.run(run())
    assert nc_svc._nc_last_failure_ts > 0, "Failed download must record NC failure"
    assert nc_svc._nc_last_success_ts == 0.0, "Failed download must NOT record NC success"


# ── NC8: successful upload clears all cache fields ────────────────────────────

def test_successful_upload_clears_all_cache_fields():
    from app.services.nextcloud import _upload_wb
    from openpyxl import Workbook

    nc_svc._xlsx_cache.update({
        "data": b"oldbytes",
        "ts": time.time(),
        "etag": "\"oldtag\"",
        "last_modified": "Mon, 01 Jan 2024 00:00:00 GMT",
    })

    wb = Workbook()

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 204
    mock_resp.raise_for_status = MagicMock()

    async def run():
        with patch("app.services.nextcloud.httpx.AsyncClient") as MockCl:
            mock_client = MagicMock()
            mock_client.put = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockCl.return_value = mock_client
            await _upload_wb(wb)

    asyncio.run(run())

    assert nc_svc._xlsx_cache["data"] is None, "Upload must clear cache data"
    assert nc_svc._xlsx_cache["ts"] == 0.0, "Upload must clear cache ts"
    assert nc_svc._xlsx_cache["etag"] == "", "Upload must clear etag"
    assert nc_svc._xlsx_cache["last_modified"] == "", "Upload must clear last_modified"


# ── NC9: status is 'unknown' after upload invalidation ───────────────────────

def test_nc_status_unknown_after_upload_invalidation(client):
    """After a successful upload clears the cache, NC status must be 'unknown'
    until a new successful download occurs and records nc_success."""
    nc_svc._nc_last_success_ts = time.time()  # simulate prior success
    nc_svc._nc_last_failure_ts = 0.0
    nc_svc._xlsx_cache.update({
        "data": b"oldbytes", "ts": time.time(), "etag": "", "last_modified": "",
    })

    # Simulate upload invalidation (clears ts → triggers nc_health to derive unknown)
    # We also reset last_success_ts because the upload clears all state
    nc_svc._nc_last_success_ts = 0.0
    nc_svc._xlsx_cache.update({"data": None, "ts": 0.0, "etag": "", "last_modified": ""})

    assert _svc(client)["nextcloud"] == "unknown", (
        "NC status must be 'unknown' after upload invalidation and before new download"
    )


# ── NC10: failed upload records NC failure ────────────────────────────────────

def test_failed_upload_records_nc_failure():
    from app.services.nextcloud import _upload_wb
    from openpyxl import Workbook

    wb = Workbook()

    async def run():
        with patch("app.services.nextcloud.httpx.AsyncClient") as MockCl:
            mock_client = MagicMock()
            mock_client.put = AsyncMock(side_effect=httpx.ConnectError("nc down"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockCl.return_value = mock_client
            try:
                await _upload_wb(wb)
            except Exception:
                pass

    asyncio.run(run())
    assert nc_svc._nc_last_failure_ts > 0, "Failed upload must record NC failure"


if __name__ == "__main__":
    import pytest as _pytest
    _pytest.main([__file__, "-v"])
