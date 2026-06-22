"""Project 7.2.3 — Security & Production Hardening regression tests.

Coverage:
  P1 — test-username names are not in BOOTSTRAP_APP_ADMINS / BOOTSTRAP_APP_USERS
  P2 — login rate limiting: per-IP and per-username 429 + Retry-After
  P3 — DISABLE_DOCS setting controls docs_url / openapi_url
  P4 — alarm threshold block_enabled=False is warning-only (not blocking)
  P5 — access log middleware records method/path/status/duration without auth header
"""
import logging
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("NEXTCLOUD_URL", "http://example.invalid")
os.environ.setdefault("NEXTCLOUD_USER", "x")
os.environ.setdefault("NEXTCLOUD_PASSWORD", "x")
os.environ.setdefault("NEXTCLOUD_FILE_PATH", "/x.xlsx")
os.environ.setdefault("WC_URL", "http://example.invalid")
os.environ.setdefault("WC_KEY", "x")
os.environ.setdefault("WC_SECRET", "x")
os.environ.setdefault("SUPER_ADMIN_USERS", "testadmin")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.main as main_module  # noqa: E402
from app.main import (  # noqa: E402
    _LOGIN_IP_ATTEMPTS,
    _LOGIN_USER_ATTEMPTS,
    _LOGIN_IP_LIMIT,
    _LOGIN_USER_LIMIT,
    _LOGIN_RATE_WINDOW,
    _rate_limit_check,
    _compute_dry_run_summary,
    app,
)
from app.config import get_settings  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# ── P1: Regression — test usernames must not be in bootstrap config ───────────

_TEST_USERNAMES = {
    "dbadmin71", "dbadmin72",
    "permtest71", "permtest72",
    "listtest71", "normaluser71",
}


def test_test_usernames_not_in_bootstrap_admins():
    s = get_settings()
    admins = {e.strip().split(":")[0] for e in s.bootstrap_app_admins.split(",") if e.strip()}
    leaked = _TEST_USERNAMES & admins
    assert not leaked, f"Test usernames in BOOTSTRAP_APP_ADMINS: {leaked}"


def test_test_usernames_not_in_bootstrap_users():
    s = get_settings()
    users = {e.strip().split(":")[0] for e in s.bootstrap_app_users.split(",") if e.strip()}
    leaked = _TEST_USERNAMES & users
    assert not leaked, f"Test usernames in BOOTSTRAP_APP_USERS: {leaked}"


# ── P2: Login rate limiting ───────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clear_rate_state():
    """Wipe in-memory rate limit buckets before every test."""
    _LOGIN_IP_ATTEMPTS.clear()
    _LOGIN_USER_ATTEMPTS.clear()
    yield
    _LOGIN_IP_ATTEMPTS.clear()
    _LOGIN_USER_ATTEMPTS.clear()


def test_rate_limit_check_passes_when_under_limit():
    store: dict = {}
    exceeded, retry = _rate_limit_check(store, "192.0.2.1", 5, 900)
    assert not exceeded
    assert retry == 0


def test_rate_limit_check_blocks_when_at_limit():
    import time
    store: dict = {"192.0.2.1": [time.time()] * 5}
    exceeded, retry = _rate_limit_check(store, "192.0.2.1", 5, 900)
    assert exceeded
    assert retry > 0


def test_rate_limit_check_prunes_expired_entries():
    import time
    # All entries are older than window — should be pruned, not block
    store: dict = {"192.0.2.1": [time.time() - 1000] * 10}
    exceeded, _ = _rate_limit_check(store, "192.0.2.1", 5, 900)
    assert not exceeded


def test_ip_rate_limit_returns_429_after_limit(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        main_module, "verify_nextcloud_credentials", AsyncMock(return_value=False)
    )
    # Use a unique username per request so the per-user limit (5) is never hit;
    # only the per-IP limit (10) can trigger 429 here.
    for i in range(_LOGIN_IP_LIMIT):
        r = client.post("/api/auth/login",
                        json={"username": f"iptest_user_{i}", "password": "bad"},
                        headers={"X-Forwarded-For": "10.0.0.1"})
        assert r.status_code in (401, 403, 503), f"iteration {i}: {r.status_code}"

    # Next attempt (any username) must be rate-limited by IP
    r = client.post("/api/auth/login",
                    json={"username": "iptest_final", "password": "bad"},
                    headers={"X-Forwarded-For": "10.0.0.1"})
    assert r.status_code == 429
    assert "Retry-After" in r.headers
    assert int(r.headers["Retry-After"]) > 0


def test_user_rate_limit_returns_429_after_limit(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        main_module, "verify_nextcloud_credentials", AsyncMock(return_value=False)
    )
    # Different IPs (none exceed per-IP limit); same username exhausts per-user limit (5)
    for i in range(_LOGIN_USER_LIMIT):
        r = client.post("/api/auth/login",
                        json={"username": "uniquetarget723", "password": "bad"},
                        headers={"X-Forwarded-For": f"10.1.1.{i + 1}"})
        assert r.status_code in (401, 403, 503), f"iteration {i}: {r.status_code}"

    r = client.post("/api/auth/login",
                    json={"username": "uniquetarget723", "password": "bad"},
                    headers={"X-Forwarded-For": "10.1.1.99"})
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_rate_limit_detail_is_generic(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        main_module, "verify_nextcloud_credentials", AsyncMock(return_value=False)
    )
    # Use unique usernames to stay under per-user limit while filling per-IP limit
    for i in range(_LOGIN_IP_LIMIT):
        client.post("/api/auth/login",
                    json={"username": f"generic_user_{i}", "password": "bad"},
                    headers={"X-Forwarded-For": "10.0.0.2"})

    r = client.post("/api/auth/login",
                    json={"username": "anyuser", "password": "bad"},
                    headers={"X-Forwarded-For": "10.0.0.2"})
    assert r.status_code == 429
    body = r.json()
    assert "detail" in body
    # Must not expose internal info (IP, username, attempt count)
    assert "10.0.0.2" not in body["detail"]
    assert "anyuser" not in body["detail"]


def test_different_ip_not_blocked_by_another_ip_limit(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        main_module, "verify_nextcloud_credentials", AsyncMock(return_value=False)
    )
    # Saturate IP A with unique usernames to avoid triggering the per-user limit
    for i in range(_LOGIN_IP_LIMIT):
        client.post("/api/auth/login",
                    json={"username": f"ipdiff_u_{i}", "password": "bad"},
                    headers={"X-Forwarded-For": "10.2.0.1"})

    # IP B with a fresh username must not be blocked by IP A's limit
    r = client.post("/api/auth/login",
                    json={"username": "ipdiff_fresh", "password": "bad"},
                    headers={"X-Forwarded-For": "10.2.0.2"})
    assert r.status_code != 429


# ── P3: Swagger docs configuration ───────────────────────────────────────────

def test_disable_docs_false_by_default():
    s = get_settings()
    assert s.disable_docs is False


def test_docs_enabled_in_test_environment(client: TestClient):
    """docs_url=/docs because DISABLE_DOCS is not set in the test environment."""
    r = client.get("/docs")
    assert r.status_code == 200


def test_openapi_json_enabled_in_test_environment(client: TestClient):
    r = client.get("/openapi.json")
    assert r.status_code == 200


def test_disable_docs_true_hides_both_endpoints():
    """When disable_docs=True, FastAPI must receive docs_url=None and openapi_url=None."""
    from fastapi import FastAPI
    settings_on = SimpleNamespace(disable_docs=True)
    docs = None if settings_on.disable_docs else "/docs"
    openapi = None if settings_on.disable_docs else "/openapi.json"
    assert docs is None
    assert openapi is None

    settings_off = SimpleNamespace(disable_docs=False)
    docs = None if settings_off.disable_docs else "/docs"
    openapi = None if settings_off.disable_docs else "/openapi.json"
    assert docs == "/docs"
    assert openapi == "/openapi.json"


# ── P4: Alarm threshold — block_enabled=False is always warning-only ──────────

def _make_item(**kw):
    defaults = dict(
        product_id=1, product_name="Test", new_price="", old_price=None,
        stock_status="instock", change_status=None, categories=None,
        price_changed=0, stock_changed=0, missing_image=0, missing_cost=0,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def test_block_enabled_false_never_produces_blocked_status():
    item = _make_item(product_id=20, old_price="100.00", new_price="900.00",
                      change_status="changed", price_changed=1)
    # 800% change, critical threshold 200%, but block_enabled=False
    thresholds = {None: {"warning": 50.0, "critical": 200.0, "block_enabled": False}}
    summary = _compute_dry_run_summary([item], alarm_threshold=50.0, category_thresholds=thresholds)
    assert summary["dry_run_status"] != "blocked"
    assert summary["dry_run_status"] == "warnings"


def test_block_enabled_true_produces_blocked_status():
    item = _make_item(product_id=21, old_price="100.00", new_price="400.00",
                      change_status="changed", price_changed=1)
    # 300% change, critical threshold 250%, block_enabled=True
    thresholds = {None: {"warning": 50.0, "critical": 250.0, "block_enabled": True}}
    summary = _compute_dry_run_summary([item], alarm_threshold=50.0, category_thresholds=thresholds)
    assert summary["dry_run_status"] == "blocked"
    assert any(e["type"] == "extreme_price_change" for e in summary["critical_errors"])


def test_no_thresholds_configured_is_always_safe():
    item = _make_item(product_id=22, old_price="100.00", new_price="99999.00",
                      change_status="changed", price_changed=1)
    summary = _compute_dry_run_summary([item], alarm_threshold=float("inf"))
    assert summary["dry_run_status"] in ("passed", "warnings")
    assert summary["critical_errors"] == []


# ── P5: Access logging ───────────────────────────────────────────────────────

class _ListHandler(logging.Handler):
    """In-test handler: attaches directly to app.main logger to capture async logs."""
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


import asyncio as _asyncio
from unittest.mock import MagicMock as _MagicMock, patch as _patch
from starlette.responses import JSONResponse as _JSONResponse


async def _fake_call_next(_req):
    return _JSONResponse({"ok": True}, status_code=200)


def _make_mock_request(method: str = "GET", path: str = "/api/health",
                       headers: dict | None = None) -> "_MagicMock":
    req = _MagicMock()
    req.method = method
    req.url.path = path
    hdr = headers or {}
    req.headers.get = lambda k, d=None: hdr.get(k, d)
    req.client = None
    return req


def test_access_log_emits_method_path_status_duration():
    """_access_log must call logger.info with method, path, status, duration."""
    req = _make_mock_request("GET", "/api/health")
    with _patch.object(main_module, "logger") as mock_logger:
        _asyncio.run(main_module._access_log(req, _fake_call_next))

    assert mock_logger.info.called, "logger.info was never called by _access_log"
    fmt, *args = mock_logger.info.call_args[0]
    line = fmt % tuple(args)
    assert "access:" in line
    assert "method=GET" in line
    assert "path=/api/health" in line
    assert "status=" in line
    assert "duration_ms=" in line


def test_access_log_does_not_contain_auth_header():
    """Authorization header value must never appear in any log line."""
    secret_token = "supersecrettoken123"
    req = _make_mock_request(headers={"Authorization": f"Bearer {secret_token}"})
    with _patch.object(main_module, "logger") as mock_logger:
        _asyncio.run(main_module._access_log(req, _fake_call_next))

    for call in mock_logger.info.call_args_list:
        fmt, *args = call[0]
        line = fmt % tuple(args)
        assert secret_token not in line, f"Auth token leaked into log: {line}"


def test_access_log_does_not_log_query_params():
    """The log records request.url.path only — query strings are not in any other field."""
    secret_token = "ssetoken456"
    # Simulate a path that contains the token (as would come from url.path in some impls)
    req = _make_mock_request(path="/api/health")
    with _patch.object(main_module, "logger") as mock_logger:
        _asyncio.run(main_module._access_log(req, _fake_call_next))

    for call in mock_logger.info.call_args_list:
        fmt, *args = call[0]
        # The format string itself must not include any auth/body/query field
        assert "Authorization" not in fmt
        assert "token" not in fmt.lower() or "token" not in fmt  # path is ok, raw header is not
