"""Project 7.3B R2 — Behavioral tests for capability handling and health endpoint.

These tests exercise actual HTTP responses and backend state transitions, not
just source inspection. Source-inspection tests in test_730b_capability.py
remain as secondary structural guards.

Covers:
  B1 — /api/health returns correct shape and backward-compatible fields
  B2 — /api/health.services.woocommerce is not permanently "unknown"
  B3 — /api/health.services.currency reflects in-memory cache state
  B4 — /api/fetch/light capability guard rejects non-admin override (live HTTP)
  B5 — /api/fetch/light capability guard SSE payload contains capability_error (live HTTP)
  B6 — /api/health backward compat: old fields (status, wc_url, nextcloud_url) still present
  B7 — Shutdown handler cancels background tasks (structural)
"""
import asyncio
import os
import sys
from datetime import datetime
from unittest.mock import patch, AsyncMock

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("NEXTCLOUD_URL", "http://example.invalid")
os.environ.setdefault("NEXTCLOUD_USER", "x")
os.environ.setdefault("NEXTCLOUD_PASSWORD", "x")
os.environ.setdefault("NEXTCLOUD_FILE_PATH", "/x.xlsx")
os.environ.setdefault("WC_URL", "http://wc.example.invalid")
os.environ.setdefault("WC_KEY", "ck_test")
os.environ.setdefault("WC_SECRET", "cs_test")
os.environ.setdefault("SUPER_ADMIN_USERS", "testadmin_b")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services.auth import create_token  # noqa: E402
from app.database import Base, engine  # noqa: E402
import app.services.woocommerce as _wc_svc  # noqa: E402
import app.services.nextcloud as _nc_svc  # noqa: E402

Base.metadata.create_all(bind=engine)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_wc_nc_state():
    _wc_svc.reset_wc_health_state()
    _wc_svc.reset_wc_capability_cache()
    _nc_svc.reset_nc_health_state()
    yield
    _wc_svc.reset_wc_health_state()
    _wc_svc.reset_wc_capability_cache()
    _nc_svc.reset_nc_health_state()


def _admin_tok():
    return {"Authorization": f"Bearer {create_token('testadmin_b', permission_version=0, role='admin')}"}


def _user_tok():
    return {"Authorization": f"Bearer {create_token('plain_user_b', permission_version=0, role='user')}"}


# ── B1/B6: Health endpoint shape and backward compatibility ───────────────────

def test_health_returns_200(client: TestClient):
    r = client.get("/api/health")
    assert r.status_code == 200


def test_health_backward_compat_fields_present(client: TestClient):
    """Existing fields must still be present so reverse-proxy health checks pass."""
    r = client.get("/api/health")
    body = r.json()
    assert body.get("status") == "ok", f"'status' field missing or wrong: {body}"
    assert "wc_url" in body, f"'wc_url' missing: {body}"
    assert "nextcloud_url" in body, f"'nextcloud_url' missing: {body}"


def test_health_services_dict_present(client: TestClient):
    r = client.get("/api/health")
    body = r.json()
    assert "services" in body, f"'services' key missing from /api/health: {body}"
    svc = body["services"]
    for key in ("api", "woocommerce", "nextcloud", "currency", "cache"):
        assert key in svc, f"Expected services.{key} but not found; got {list(svc.keys())}"


def test_health_api_service_is_ok(client: TestClient):
    """The 'api' service field must always be 'ok' when the endpoint responds."""
    r = client.get("/api/health")
    assert r.json()["services"]["api"] == "ok"


def test_health_cache_field_has_expected_shape(client: TestClient):
    r = client.get("/api/health")
    cache = r.json()["services"]["cache"]
    assert "size" in cache, f"cache.size missing: {cache}"
    assert "age_seconds" in cache, f"cache.age_seconds missing: {cache}"
    assert isinstance(cache["size"], int)


# ── B2: WooCommerce status is not hardcoded "unknown" ─────────────────────────

def test_health_wc_status_reflects_recent_success(client: TestClient):
    """After a successful WC fetch, status must be 'ok' (not permanently 'unknown')."""
    _wc_svc.record_wc_success()
    status = client.get("/api/health").json()["services"]["woocommerce"]
    assert status in ("ok", "limited"), (
        f"woocommerce status must be 'ok' or 'limited' after a recorded success; got '{status}'"
    )


def test_health_wc_status_is_limited_when_capability_false(client: TestClient):
    """When capability probe returned False AND a fresh success is recorded → 'limited'."""
    _wc_svc.record_wc_success()
    _wc_svc._wc_variation_filter_capable = False
    status = client.get("/api/health").json()["services"]["woocommerce"]
    assert status == "limited", (
        f"woocommerce must be 'limited' when capability=False + fresh success; got '{status}'"
    )


def test_health_wc_status_is_unknown_before_any_fetch(client: TestClient):
    """Before any successful WC fetch is recorded, status must be 'unknown'."""
    status = client.get("/api/health").json()["services"]["woocommerce"]
    assert status == "unknown", (
        f"woocommerce must be 'unknown' before any fetch is recorded; got '{status}'"
    )


# ── B3: Currency status reflects in-memory cache state ───────────────────────

def test_health_currency_is_unavailable_when_no_cache(client: TestClient):
    import app.main as m
    original = m._currency_cache.copy()
    try:
        m._currency_cache["data"] = None
        m._currency_cache["ts"] = 0.0
        r = client.get("/api/health")
        assert r.json()["services"]["currency"] == "unavailable"
    finally:
        m._currency_cache.update(original)


def test_health_currency_is_ok_when_cache_fresh(client: TestClient):
    import time
    import app.main as m
    original = m._currency_cache.copy()
    try:
        m._currency_cache["data"] = {"usd_to_irr": 1_200_000}
        m._currency_cache["ts"] = time.time()  # fresh
        r = client.get("/api/health")
        assert r.json()["services"]["currency"] == "ok"
    finally:
        m._currency_cache.update(original)


def test_health_currency_is_stale_when_cache_old(client: TestClient):
    import time
    import app.main as m
    original = m._currency_cache.copy()
    try:
        m._currency_cache["data"] = {"usd_to_irr": 1_200_000}
        m._currency_cache["ts"] = time.time() - 400  # 400s old > 300s TTL
        r = client.get("/api/health")
        assert r.json()["services"]["currency"] == "stale"
    finally:
        m._currency_cache.update(original)


# ── B4: capability guard rejects non-admin override via live HTTP ─────────────

def test_light_refresh_capability_override_rejected_for_nonadmin(client: TestClient):
    """Non-admin must not bypass capability guard via force_capability=true.

    We patch validate_sse_token to return a non-admin, non-super-admin user so
    the request reaches the capability override check. The response must contain
    'admin' or 'override' in the error message.
    """
    plain_creds = {"sub": "plain_user_nonadmin", "role": "user"}
    with patch("app.main.validate_sse_token", return_value=plain_creds):
        with patch("app.main._enforce_permission"):  # bypass can_fetch check
            # Return a real datetime so the watermark arithmetic at line 2138 doesn't crash.
            with patch("app.main.get_last_sync_time", return_value=datetime(2024, 1, 1)):
                # Patch in main's namespace — main.py holds a local `from ... import` reference.
                with patch("app.main.check_variation_filter_capability",
                           new=AsyncMock(return_value=False)):
                    r = client.get("/api/fetch/light?force_capability=true", headers=_user_tok())
    body = r.text
    assert "admin" in body.lower() or "override" in body.lower(), (
        f"Non-admin force_capability must be rejected with admin/override message; got: {body[:300]}"
    )


# ── B5: capability guard SSE payload contains capability_error ────────────────

def test_light_refresh_capability_guard_sse_contains_capability_error(client: TestClient):
    """When capability guard fires (no override), SSE payload must include capability_error.

    We patch validate_sse_token to bypass JWT validation (DB is in-memory and
    may not have the test user), and patch the downstream checks so the request
    reaches the capability guard. The key assertion is the SSE payload shape.
    """
    fake_creds = {"sub": "testadmin_b", "role": "admin"}
    with patch("app.main.validate_sse_token", return_value=fake_creds):
        with patch("app.main._enforce_permission"):  # bypass DB/permission check
            with patch("app.main.get_last_sync_time", return_value=datetime(2024, 1, 1)):
                # Patch in main's namespace — main.py holds a local `from ... import` reference.
                with patch("app.main.check_variation_filter_capability",
                           new=AsyncMock(return_value=False)):
                    r = client.get("/api/fetch/light", headers=_admin_tok())
    body = r.text
    assert "capability_error" in body, (
        f"Capability-limited SSE must include capability_error field; got: {body[:300]}"
    )


# ── B7: Shutdown handler is registered ───────────────────────────────────────

def test_shutdown_handler_registered_in_app():
    """The app must have a shutdown handler that can cancel background tasks."""
    import inspect
    import app.main as m
    src = inspect.getsource(m._stop_bg_tasks)
    assert "cancel" in src, "_stop_bg_tasks must call task.cancel()"
    assert "_bg_tasks" in src, "_stop_bg_tasks must iterate _bg_tasks"


if __name__ == "__main__":
    import pytest as _pytest
    _pytest.main([__file__, "-v"])
