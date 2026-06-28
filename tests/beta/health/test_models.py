"""Tests for HealthCheckResult model."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.beta.control_plane.failure import FailureClass, Severity
from app.beta.health.models import CheckCategory, HealthCheckResult, HealthStatus


def test_ok_factory_sets_pass_status():
    r = HealthCheckResult.ok("dns", CheckCategory.DNS, "host", "resolved ok")
    assert r.status == HealthStatus.PASS


def test_ok_factory_sets_info_severity():
    r = HealthCheckResult.ok("dns", CheckCategory.DNS, "host", "resolved ok")
    assert r.severity == Severity.INFO


def test_ok_factory_sets_none_failure_class():
    r = HealthCheckResult.ok("dns", CheckCategory.DNS, "host", "resolved ok")
    assert r.failure_class == FailureClass.NONE


def test_warn_factory_sets_warn_status():
    r = HealthCheckResult.warn("tls", CheckCategory.TLS, "host", "expiring soon")
    assert r.status == HealthStatus.WARN


def test_warn_factory_sets_warning_severity():
    r = HealthCheckResult.warn("tls", CheckCategory.TLS, "host", "expiring soon")
    assert r.severity == Severity.WARNING


def test_fail_factory_sets_fail_status():
    r = HealthCheckResult.fail(
        "dns", CheckCategory.DNS, "host",
        FailureClass.DNS_FAILURE, "could not resolve"
    )
    assert r.status == HealthStatus.FAIL


def test_fail_factory_uses_meta_severity():
    r = HealthCheckResult.fail(
        "dns", CheckCategory.DNS, "host",
        FailureClass.DNS_FAILURE, "could not resolve"
    )
    assert r.severity == FailureClass.DNS_FAILURE.meta.severity_default


def test_skip_factory_sets_skip_status():
    r = HealthCheckResult.skip("tcp", CheckCategory.TCP, "host:443", "dns")
    assert r.status == HealthStatus.SKIP


def test_skip_factory_sets_skipped_because():
    r = HealthCheckResult.skip("tcp", CheckCategory.TCP, "host:443", "dns")
    assert r.skipped_because == "dns"


def test_stub_skip_sets_skip_status():
    r = HealthCheckResult.stub_skip("docker", CheckCategory.DOCKER)
    assert r.status == HealthStatus.SKIP


def test_stub_skip_sets_not_implemented_reason():
    r = HealthCheckResult.stub_skip("docker", CheckCategory.DOCKER)
    assert r.skipped_because == "not_implemented"


def test_is_blocking_for_fail():
    r = HealthCheckResult.fail(
        "dns", CheckCategory.DNS, "host",
        FailureClass.DNS_FAILURE, "nxdomain"
    )
    assert r.is_blocking() is True


def test_is_blocking_false_for_pass():
    r = HealthCheckResult.ok("dns", CheckCategory.DNS, "host", "ok")
    assert r.is_blocking() is False


def test_is_blocking_false_for_warn():
    r = HealthCheckResult.warn("tls", CheckCategory.TLS, "host", "expiring")
    assert r.is_blocking() is False


def test_is_blocking_true_for_skip():
    # SKIP is blocking so downstream checks also skip (chain cascade)
    r = HealthCheckResult.skip("tcp", CheckCategory.TCP, "host", "dns")
    assert r.is_blocking() is True


def test_to_dict_contains_expected_keys():
    r = HealthCheckResult.ok("dns", CheckCategory.DNS, "host", "ok")
    d = r.to_dict()
    for key in ("check_name", "category", "target", "status", "severity",
                "failure_class", "message", "duration_ms", "checked_at"):
        assert key in d


def test_to_dict_no_credential_keys():
    r = HealthCheckResult.ok("auth", CheckCategory.AUTH, "url", "ok")
    d = r.to_dict()
    for key in d:
        assert "password" not in key.lower()
        assert "secret" not in key.lower()


def test_details_default_is_empty_dict():
    r = HealthCheckResult.ok("dns", CheckCategory.DNS, "host", "ok")
    assert r.details == {}


def test_details_dict_must_not_contain_credentials():
    """details field must never contain passwords or secrets."""
    r = HealthCheckResult.ok(
        "auth", CheckCategory.AUTH, "url", "ok",
        details={"service": "nextcloud", "status_code": 200}
    )
    for key in r.details:
        assert "password" not in key.lower()
        assert "secret" not in key.lower()
