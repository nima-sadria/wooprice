"""Tests for CircuitBreaker state machine."""

from __future__ import annotations

import time

import pytest

from app.beta.connections.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from app.beta.connections.models import CircuitState


@pytest.fixture
def cb() -> CircuitBreaker:
    config = CircuitBreakerConfig(failure_threshold=3, recovery_window_s=30.0, success_threshold=1)
    return CircuitBreaker(config)


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------


def test_initial_state_is_closed(cb):
    assert cb.state == CircuitState.CLOSED


def test_initial_allows_requests(cb):
    assert cb.allow_request() is True


def test_initial_failure_count_is_zero(cb):
    assert cb.failure_count == 0


# ---------------------------------------------------------------------------
# CLOSED → OPEN transition
# ---------------------------------------------------------------------------


def test_opens_after_failure_threshold(cb):
    for _ in range(3):
        cb.record_failure()
    assert cb.state == CircuitState.OPEN


def test_below_threshold_stays_closed(cb):
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitState.CLOSED


def test_open_blocks_requests(cb):
    for _ in range(3):
        cb.record_failure()
    assert cb.allow_request() is False


def test_success_resets_failure_count_in_closed(cb):
    cb.record_failure()
    cb.record_failure()
    cb.record_success()
    assert cb.failure_count == 0


# ---------------------------------------------------------------------------
# OPEN → HALF_OPEN transition (time-based)
# ---------------------------------------------------------------------------


def test_half_open_after_recovery_window():
    config = CircuitBreakerConfig(failure_threshold=1, recovery_window_s=0.01)
    cb = CircuitBreaker(config)
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    time.sleep(0.02)
    assert cb.state == CircuitState.HALF_OPEN


def test_half_open_allows_one_request():
    config = CircuitBreakerConfig(failure_threshold=1, recovery_window_s=0.01)
    cb = CircuitBreaker(config)
    cb.record_failure()
    time.sleep(0.02)
    assert cb.allow_request() is True


# ---------------------------------------------------------------------------
# HALF_OPEN → CLOSED (success)
# ---------------------------------------------------------------------------


def test_closes_after_success_in_half_open():
    config = CircuitBreakerConfig(failure_threshold=1, recovery_window_s=0.01, success_threshold=1)
    cb = CircuitBreaker(config)
    cb.record_failure()
    time.sleep(0.02)
    assert cb.state == CircuitState.HALF_OPEN
    cb.record_success()
    assert cb.state == CircuitState.CLOSED


def test_failure_count_resets_after_close():
    config = CircuitBreakerConfig(failure_threshold=1, recovery_window_s=0.01)
    cb = CircuitBreaker(config)
    cb.record_failure()
    time.sleep(0.02)
    cb.record_success()
    assert cb.failure_count == 0


# ---------------------------------------------------------------------------
# HALF_OPEN → OPEN (failure)
# ---------------------------------------------------------------------------


def test_reopens_after_failure_in_half_open():
    config = CircuitBreakerConfig(failure_threshold=1, recovery_window_s=0.01)
    cb = CircuitBreaker(config)
    cb.record_failure()
    time.sleep(0.02)
    assert cb.state == CircuitState.HALF_OPEN
    cb.record_failure()
    assert cb.state == CircuitState.OPEN


# ---------------------------------------------------------------------------
# force_reset
# ---------------------------------------------------------------------------


def test_force_reset_from_open():
    config = CircuitBreakerConfig(failure_threshold=1)
    cb = CircuitBreaker(config)
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    cb.force_reset()
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 0


def test_force_reset_from_closed_is_noop(cb):
    cb.force_reset()
    assert cb.state == CircuitState.CLOSED


# ---------------------------------------------------------------------------
# last_failure_class
# ---------------------------------------------------------------------------


def test_last_failure_class_recorded(cb):
    cb.record_failure(failure_class="dns_failure")
    assert cb.last_failure_class == "dns_failure"


def test_last_failure_class_none_initially(cb):
    assert cb.last_failure_class is None


def test_last_failure_class_cleared_on_reset(cb):
    cb.record_failure(failure_class="tls_failure")
    cb.force_reset()
    assert cb.last_failure_class is None
