"""Tests for in-memory connection cache."""

from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest

from app.beta.connections.cache import ConnectionCache
from app.beta.connections.models import (
    CircuitState,
    ConnectionResult,
    ConnectionStatus,
    ConnectionType,
)
from app.beta.control_plane.failure import FailureClass, Severity


def _make_result(name: str = "nextcloud") -> ConnectionResult:
    return ConnectionResult(
        name=name,
        connection_type=ConnectionType.NEXTCLOUD,
        status=ConnectionStatus.HEALTHY,
        reachable=True,
        authenticated=None,
        latency_ms=5.0,
        failure_class=FailureClass.NONE,
        severity=Severity.INFO,
        message="ok",
        repair_hint="",
        checked_at=datetime.now(tz=timezone.utc),
        retryable=False,
        circuit_state=CircuitState.CLOSED,
    )


@pytest.fixture
def cache() -> ConnectionCache:
    return ConnectionCache(default_ttl_seconds=60.0)


# ---------------------------------------------------------------------------
# Basic get / set
# ---------------------------------------------------------------------------


def test_miss_returns_none(cache):
    assert cache.get("nextcloud") is None


def test_set_then_get(cache):
    r = _make_result()
    cache.set("nextcloud", r)
    assert cache.get("nextcloud") is r


def test_size_after_set(cache):
    cache.set("a", _make_result("a"))
    cache.set("b", _make_result("b"))
    assert cache.size() == 2


def test_has_returns_true(cache):
    cache.set("nextcloud", _make_result())
    assert cache.has("nextcloud") is True


def test_has_returns_false_when_missing(cache):
    assert cache.has("nextcloud") is False


# ---------------------------------------------------------------------------
# TTL / expiry
# ---------------------------------------------------------------------------


def test_expired_entry_returns_none():
    cache = ConnectionCache(default_ttl_seconds=0.01)
    cache.set("nextcloud", _make_result())
    time.sleep(0.02)
    assert cache.get("nextcloud") is None


def test_non_expired_entry_returns_result():
    cache = ConnectionCache(default_ttl_seconds=60.0)
    r = _make_result()
    cache.set("nextcloud", r)
    assert cache.get("nextcloud") is r


def test_per_entry_ttl_overrides_default():
    cache = ConnectionCache(default_ttl_seconds=60.0)
    cache.set("nextcloud", _make_result(), ttl_seconds=0.01)
    time.sleep(0.02)
    assert cache.get("nextcloud") is None


def test_remaining_ttl_positive(cache):
    cache.set("nextcloud", _make_result())
    assert (cache.remaining_ttl("nextcloud") or 0) > 0


def test_remaining_ttl_none_when_missing(cache):
    assert cache.remaining_ttl("nextcloud") is None


# ---------------------------------------------------------------------------
# invalidate / clear
# ---------------------------------------------------------------------------


def test_invalidate_removes_entry(cache):
    cache.set("nextcloud", _make_result())
    cache.invalidate("nextcloud")
    assert cache.get("nextcloud") is None


def test_invalidate_missing_key_is_noop(cache):
    cache.invalidate("does_not_exist")  # must not raise


def test_clear_removes_all(cache):
    cache.set("a", _make_result("a"))
    cache.set("b", _make_result("b"))
    cache.clear()
    assert cache.size() == 0
    assert cache.get("a") is None


# ---------------------------------------------------------------------------
# Overwrite
# ---------------------------------------------------------------------------


def test_set_overwrites_existing(cache):
    r1 = _make_result()
    r2 = _make_result()
    r2.message = "updated"
    cache.set("nextcloud", r1)
    cache.set("nextcloud", r2)
    assert cache.get("nextcloud").message == "updated"
