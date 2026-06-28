"""Tests for DiagnosticReport, DiagnosticCheckResult, RepairStep models."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.beta.control_plane.failure import FailureClass, Severity
from app.beta.diagnostics.report import (
    DiagnosticCategory,
    DiagnosticCheckResult,
    DiagnosticReport,
    RepairStep,
)
from app.beta.health.models import HealthCheckResult, HealthStatus, CheckCategory


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


class TestRepairStep:
    def test_to_dict_all_fields(self):
        step = RepairStep(step_number=1, description="Do this", command="cmd", detail="info")
        d = step.to_dict()
        assert d["step_number"] == 1
        assert d["description"] == "Do this"
        assert d["command"] == "cmd"
        assert d["detail"] == "info"

    def test_to_dict_optional_none(self):
        step = RepairStep(step_number=2, description="Do that")
        d = step.to_dict()
        assert d["command"] is None
        assert d["detail"] is None

    def test_step_number_preserved(self):
        step = RepairStep(step_number=5, description="Fifth step")
        assert step.step_number == 5


class TestDiagnosticCheckResult:
    def _make(self, status: HealthStatus) -> DiagnosticCheckResult:
        return DiagnosticCheckResult(
            check_name="dns",
            category=DiagnosticCategory.INTEGRATION,
            target="nextcloud.example.com",
            status=status,
            failure_class=FailureClass.DNS_FAILURE if status == HealthStatus.FAIL else FailureClass.NONE,
            severity=Severity.ERROR if status == HealthStatus.FAIL else Severity.INFO,
            message="Could not resolve",
            repair_hint="Check DNS",
            duration_ms=42.0,
            checked_at=_now(),
        )

    def test_to_dict_has_required_keys(self):
        result = self._make(HealthStatus.FAIL)
        d = result.to_dict()
        for key in ("check_name", "category", "target", "status", "failure_class",
                    "severity", "message", "repair_hint", "duration_ms", "checked_at", "details"):
            assert key in d, f"Missing key: {key}"

    def test_to_dict_status_is_string(self):
        result = self._make(HealthStatus.PASS)
        d = result.to_dict()
        assert d["status"] == "pass"
        assert d["failure_class"] == "none"

    def test_to_dict_failure_has_class(self):
        result = self._make(HealthStatus.FAIL)
        d = result.to_dict()
        assert d["failure_class"] == "dns_failure"

    def test_from_health_result_pass(self):
        hr = HealthCheckResult.ok(
            check_name="dns",
            category=CheckCategory.DNS,
            target="host.example.com",
            message="Resolved",
            duration_ms=5.0,
        )
        dr = DiagnosticCheckResult.from_health_result(hr, DiagnosticCategory.INTEGRATION)
        assert dr.check_name == "dns"
        assert dr.status == HealthStatus.PASS
        assert dr.failure_class == FailureClass.NONE
        assert dr.category == DiagnosticCategory.INTEGRATION

    def test_from_health_result_fail(self):
        hr = HealthCheckResult.fail(
            check_name="dns",
            category=CheckCategory.DNS,
            target="host.example.com",
            failure_class=FailureClass.DNS_FAILURE,
            message="Could not resolve",
        )
        dr = DiagnosticCheckResult.from_health_result(hr, DiagnosticCategory.INTEGRATION)
        assert dr.status == HealthStatus.FAIL
        assert dr.failure_class == FailureClass.DNS_FAILURE

    def test_from_health_result_skip_preserves_skipped_because(self):
        hr = HealthCheckResult.skip(
            check_name="tcp",
            category=CheckCategory.TCP,
            target="host.example.com",
            skipped_because="dns",
        )
        dr = DiagnosticCheckResult.from_health_result(hr, DiagnosticCategory.INTEGRATION)
        assert dr.status == HealthStatus.SKIP
        assert dr.skipped_because == "dns"

    def test_details_no_secrets(self):
        hr = HealthCheckResult.ok(
            check_name="http",
            category=CheckCategory.HTTP,
            target="https://host.example.com",
            message="200 OK",
            details={"status_code": 200, "url": "https://host.example.com"},
        )
        dr = DiagnosticCheckResult.from_health_result(hr, DiagnosticCategory.INTEGRATION)
        d = dr.to_dict()
        details_str = str(d["details"])
        assert "password" not in details_str.lower()
        assert "secret" not in details_str.lower()


class TestDiagnosticReport:
    def _make_report(
        self,
        status: HealthStatus = HealthStatus.PASS,
        failure_class: FailureClass = FailureClass.NONE,
    ) -> DiagnosticReport:
        now = _now()
        checks = [
            DiagnosticCheckResult(
                check_name="dns",
                category=DiagnosticCategory.INTEGRATION,
                target="host",
                status=status,
                failure_class=failure_class,
                severity=Severity.ERROR if status == HealthStatus.FAIL else Severity.INFO,
                message="msg",
                repair_hint="",
                duration_ms=10.0,
                checked_at=now,
            )
        ]
        return DiagnosticReport(
            target="nextcloud",
            started_at=now,
            completed_at=now,
            overall_status=status,
            overall_failure_class=failure_class,
            overall_severity=Severity.ERROR if status == HealthStatus.FAIL else Severity.INFO,
            checks=checks,
        )

    def test_to_dict_has_required_keys(self):
        report = self._make_report()
        d = report.to_dict()
        for key in ("target", "started_at", "completed_at", "duration_ms",
                    "overall_status", "overall_failure_class", "summary", "checks", "repair_steps"):
            assert key in d, f"Missing key: {key}"

    def test_duration_ms_non_negative(self):
        report = self._make_report()
        assert report.duration_ms >= 0.0

    def test_failed_checks_filter(self):
        report = self._make_report(HealthStatus.FAIL, FailureClass.DNS_FAILURE)
        assert len(report.failed_checks()) == 1

    def test_failed_checks_empty_for_pass(self):
        report = self._make_report(HealthStatus.PASS)
        assert report.failed_checks() == []

    def test_warn_checks_filter(self):
        now = _now()
        report = DiagnosticReport(
            target="all",
            started_at=now,
            completed_at=now,
            overall_status=HealthStatus.WARN,
            overall_failure_class=FailureClass.NONE,
            overall_severity=Severity.WARNING,
            checks=[
                DiagnosticCheckResult(
                    check_name="tls",
                    category=DiagnosticCategory.INTEGRATION,
                    target="host",
                    status=HealthStatus.WARN,
                    failure_class=FailureClass.NONE,
                    severity=Severity.WARNING,
                    message="cert expires soon",
                    repair_hint="",
                    duration_ms=3.0,
                    checked_at=now,
                )
            ],
        )
        assert len(report.warn_checks()) == 1

    def test_to_dict_status_strings(self):
        report = self._make_report(HealthStatus.FAIL, FailureClass.DNS_FAILURE)
        d = report.to_dict()
        assert d["overall_status"] == "fail"
        assert d["overall_failure_class"] == "dns_failure"

    def test_to_dict_checks_are_list(self):
        report = self._make_report()
        d = report.to_dict()
        assert isinstance(d["checks"], list)
        assert isinstance(d["repair_steps"], list)
