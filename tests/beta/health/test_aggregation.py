"""Tests for health check aggregation logic."""

from __future__ import annotations

import pytest

from app.beta.control_plane.failure import FailureClass, Severity
from app.beta.health.aggregation import (
    SystemHealthSummary,
    aggregate_results,
    filter_by_category,
    filter_failed,
    worst_result,
)
from app.beta.health.models import CheckCategory, HealthCheckResult, HealthStatus


def _ok(name="check") -> HealthCheckResult:
    return HealthCheckResult.ok(name, CheckCategory.DNS, "host", "ok")


def _warn(name="check") -> HealthCheckResult:
    return HealthCheckResult.warn(name, CheckCategory.TLS, "host", "expiring")


def _fail(name="check") -> HealthCheckResult:
    return HealthCheckResult.fail(
        name, CheckCategory.DNS, "host", FailureClass.DNS_FAILURE, "nxdomain"
    )


def _skip(name="check") -> HealthCheckResult:
    return HealthCheckResult.skip(name, CheckCategory.TCP, "host:443", "dns")


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------


def test_aggregate_empty_returns_unknown():
    summary = aggregate_results([])
    assert summary.overall_status == HealthStatus.UNKNOWN
    assert summary.total_checks == 0


# ---------------------------------------------------------------------------
# All pass
# ---------------------------------------------------------------------------


def test_aggregate_all_pass():
    summary = aggregate_results([_ok("a"), _ok("b")])
    assert summary.overall_status == HealthStatus.PASS
    assert summary.passed == 2
    assert summary.failed == 0


# ---------------------------------------------------------------------------
# Any warn → WARN overall
# ---------------------------------------------------------------------------


def test_aggregate_one_warn_gives_warn():
    summary = aggregate_results([_ok(), _warn()])
    assert summary.overall_status == HealthStatus.WARN


def test_aggregate_warn_count():
    summary = aggregate_results([_ok(), _warn(), _warn()])
    assert summary.warned == 2


# ---------------------------------------------------------------------------
# Any fail → FAIL overall
# ---------------------------------------------------------------------------


def test_aggregate_one_fail_gives_fail():
    summary = aggregate_results([_ok(), _warn(), _fail()])
    assert summary.overall_status == HealthStatus.FAIL


def test_aggregate_fail_count():
    summary = aggregate_results([_fail("a"), _fail("b"), _ok("c")])
    assert summary.failed == 2


# ---------------------------------------------------------------------------
# Skip only
# ---------------------------------------------------------------------------


def test_aggregate_all_skip_gives_pass():
    # All skipped — no failures — treated as PASS
    summary = aggregate_results([_skip("a"), _skip("b")])
    assert summary.overall_status == HealthStatus.PASS


def test_aggregate_skip_count():
    summary = aggregate_results([_skip("a"), _skip("b")])
    assert summary.skipped == 2


# ---------------------------------------------------------------------------
# highest_severity
# ---------------------------------------------------------------------------


def test_aggregate_highest_severity_all_ok():
    summary = aggregate_results([_ok()])
    assert summary.highest_severity == Severity.INFO


def test_aggregate_highest_severity_with_warn():
    summary = aggregate_results([_ok(), _warn()])
    assert summary.highest_severity == Severity.WARNING


def test_aggregate_highest_severity_with_fail():
    summary = aggregate_results([_ok(), _warn(), _fail()])
    assert summary.highest_severity >= Severity.ERROR


# ---------------------------------------------------------------------------
# to_dict
# ---------------------------------------------------------------------------


def test_summary_to_dict_contains_expected_keys():
    summary = aggregate_results([_ok()])
    d = summary.to_dict()
    for key in ("overall_status", "total_checks", "passed", "failed", "generated_at"):
        assert key in d


# ---------------------------------------------------------------------------
# worst_result
# ---------------------------------------------------------------------------


def test_worst_result_returns_fail():
    results = [_ok(), _warn(), _fail()]
    worst = worst_result(results)
    assert worst.status == HealthStatus.FAIL


def test_worst_result_returns_warn_when_no_fail():
    results = [_ok(), _warn()]
    worst = worst_result(results)
    assert worst.status == HealthStatus.WARN


def test_worst_result_returns_none_for_empty():
    assert worst_result([]) is None


# ---------------------------------------------------------------------------
# filter_by_category
# ---------------------------------------------------------------------------


def test_filter_by_category():
    results = [
        HealthCheckResult.ok("dns", CheckCategory.DNS, "host", "ok"),
        HealthCheckResult.ok("tcp", CheckCategory.TCP, "host:443", "ok"),
    ]
    dns_results = filter_by_category(results, CheckCategory.DNS)
    assert len(dns_results) == 1
    assert dns_results[0].category == CheckCategory.DNS


# ---------------------------------------------------------------------------
# filter_failed
# ---------------------------------------------------------------------------


def test_filter_failed():
    results = [_ok(), _fail("a"), _warn(), _fail("b")]
    failed = filter_failed(results)
    assert len(failed) == 2
    assert all(r.status == HealthStatus.FAIL for r in failed)
