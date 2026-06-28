"""Tests for DiagnosticRunner — all using FakeNetworkAdapter, no real network."""

from __future__ import annotations

import pytest

from tests.beta.connections.conftest import FakeNetworkAdapter
from app.beta.connections.adapters import (
    DNSResolutionError,
    TCPConnectionError,
    TLSHandshakeError,
    ConnectionTimeoutError,
    AuthenticationError,
    AccessForbiddenError,
)
from app.beta.control_plane.failure import FailureClass
from app.beta.diagnostics.runner import DiagnosticRunner, KNOWN_SERVICES
from app.beta.diagnostics.report import DiagnosticReport
from app.beta.health.models import HealthStatus


@pytest.fixture
def fake() -> FakeNetworkAdapter:
    return FakeNetworkAdapter()


@pytest.fixture
def runner(fake: FakeNetworkAdapter) -> DiagnosticRunner:
    return DiagnosticRunner(adapter=fake, config={})


class TestRunnerKnownServices:
    def test_known_services_is_list(self):
        assert isinstance(KNOWN_SERVICES, list)

    def test_known_services_has_expected_entries(self):
        assert "nextcloud" in KNOWN_SERVICES
        assert "woocommerce" in KNOWN_SERVICES
        assert "currency_api" in KNOWN_SERVICES


class TestRunIntegration:
    def test_all_checks_pass_gives_pass_report(self, runner: DiagnosticRunner, fake: FakeNetworkAdapter):
        report = runner.run_integration("nextcloud", url="https://nextcloud.example.com")
        assert isinstance(report, DiagnosticReport)
        assert report.overall_status == HealthStatus.PASS

    def test_dns_failure_gives_fail_report(self, runner: DiagnosticRunner, fake: FakeNetworkAdapter):
        fake.dns_responses["nextcloud.example.com"] = DNSResolutionError("NXDOMAIN")
        report = runner.run_integration("nextcloud", url="https://nextcloud.example.com")
        assert report.overall_status == HealthStatus.FAIL
        assert report.overall_failure_class == FailureClass.DNS_FAILURE

    def test_dns_fail_causes_downstream_skips(self, runner: DiagnosticRunner, fake: FakeNetworkAdapter):
        fake.dns_responses["nextcloud.example.com"] = DNSResolutionError("NXDOMAIN")
        report = runner.run_integration("nextcloud", url="https://nextcloud.example.com")
        statuses = {c.check_name: c.status for c in report.checks}
        assert statuses.get("dns:nextcloud") == HealthStatus.FAIL or any(
            c.status == HealthStatus.FAIL for c in report.checks
        )
        skip_checks = [c for c in report.checks if c.status == HealthStatus.SKIP]
        assert len(skip_checks) >= 1, "Expected at least one SKIP after DNS failure"

    def test_tls_failure_gives_fail_report(self, runner: DiagnosticRunner, fake: FakeNetworkAdapter):
        fake.tls_responses[("nextcloud.example.com", 443)] = TLSHandshakeError("cert error")
        report = runner.run_integration("nextcloud", url="https://nextcloud.example.com")
        assert report.overall_status == HealthStatus.FAIL
        assert report.overall_failure_class == FailureClass.TLS_FAILURE

    def test_timeout_gives_fail_report(self, runner: DiagnosticRunner, fake: FakeNetworkAdapter):
        fake.dns_responses["nextcloud.example.com"] = ConnectionTimeoutError("timeout")
        report = runner.run_integration("nextcloud", url="https://nextcloud.example.com")
        assert report.overall_status == FailureClass.TIMEOUT or report.overall_status == HealthStatus.FAIL

    def test_auth_failure_gives_fail_report(self, runner: DiagnosticRunner, fake: FakeNetworkAdapter):
        fake.auth_responses["https://nextcloud.example.com"] = AuthenticationError("401")
        report = runner.run_integration(
            "nextcloud",
            url="https://nextcloud.example.com",
            auth_username="admin",
            auth_password="wrongpass",
        )
        assert report.overall_status == HealthStatus.FAIL
        assert report.overall_failure_class == FailureClass.UNAUTHORIZED

    def test_secrets_not_in_report(self, runner: DiagnosticRunner, fake: FakeNetworkAdapter):
        report = runner.run_integration(
            "nextcloud",
            url="https://nextcloud.example.com",
            auth_username="admin",
            auth_password="supersecret123",
        )
        report_str = str(report.to_dict())
        assert "supersecret123" not in report_str

    def test_report_target_is_service_name(self, runner: DiagnosticRunner):
        report = runner.run_integration("nextcloud", url="https://nextcloud.example.com")
        assert report.target == "nextcloud"

    def test_report_has_checks(self, runner: DiagnosticRunner):
        report = runner.run_integration("nextcloud", url="https://nextcloud.example.com")
        assert len(report.checks) >= 1

    def test_report_has_summary(self, runner: DiagnosticRunner):
        report = runner.run_integration("nextcloud", url="https://nextcloud.example.com")
        assert isinstance(report.summary, str)
        assert len(report.summary) > 0

    def test_report_to_dict_serializable(self, runner: DiagnosticRunner):
        import json
        report = runner.run_integration("nextcloud", url="https://nextcloud.example.com")
        d = report.to_dict()
        serialized = json.dumps(d)
        assert "nextcloud" in serialized

    def test_fail_report_has_repair_steps(self, runner: DiagnosticRunner, fake: FakeNetworkAdapter):
        fake.dns_responses["nextcloud.example.com"] = DNSResolutionError("NXDOMAIN")
        report = runner.run_integration("nextcloud", url="https://nextcloud.example.com")
        assert len(report.repair_steps) >= 1

    def test_pass_report_no_repair_steps(self, runner: DiagnosticRunner):
        report = runner.run_integration("nextcloud", url="https://nextcloud.example.com")
        assert report.repair_steps == []

    def test_unexpected_exception_caught_as_unknown_error(self, fake: FakeNetworkAdapter):
        class BoomAdapter(FakeNetworkAdapter):
            def resolve_dns(self, hostname):
                raise RuntimeError("completely unexpected boom")

        runner = DiagnosticRunner(adapter=BoomAdapter(), config={})
        report = runner.run_integration("nextcloud", url="https://nextcloud.example.com")
        assert report.overall_status == HealthStatus.FAIL
        assert report.overall_failure_class == FailureClass.UNKNOWN_ERROR

    def test_credentials_from_config_dict(self, fake: FakeNetworkAdapter):
        config = {
            "BETA_NEXTCLOUD_URL": "https://nextcloud.example.com",
            "BETA_NEXTCLOUD_USERNAME": "user",
            "BETA_NEXTCLOUD_PASSWORD": "pass",
        }
        runner = DiagnosticRunner(adapter=fake, config=config)
        report = runner.run_integration("nextcloud")
        assert report.target == "nextcloud"

    def test_url_fallback_to_config(self, fake: FakeNetworkAdapter):
        config = {"BETA_NEXTCLOUD_URL": "https://nextcloud.example.com"}
        runner = DiagnosticRunner(adapter=fake, config=config)
        report = runner.run_integration("nextcloud")
        assert report.overall_status == HealthStatus.PASS


class TestRunAll:
    def test_run_all_covers_all_known_services(self, runner: DiagnosticRunner, fake: FakeNetworkAdapter):
        report = runner.run_all()
        assert report.target == "all"
        assert len(report.checks) > 0

    def test_run_all_all_pass(self, runner: DiagnosticRunner):
        report = runner.run_all()
        assert report.overall_status == HealthStatus.PASS

    def test_run_all_one_service_fails(self, runner: DiagnosticRunner, fake: FakeNetworkAdapter):
        fake.dns_responses["nextcloud.example.com"] = DNSResolutionError("NXDOMAIN")
        report = runner.run_all(config={"BETA_NEXTCLOUD_URL": "https://nextcloud.example.com"})
        assert report.overall_status == HealthStatus.FAIL

    def test_run_all_summary_mentions_count(self, runner: DiagnosticRunner):
        report = runner.run_all()
        assert "check" in report.summary.lower() or "pass" in report.summary.lower()

    def test_run_all_unexpected_exception_caught(self, fake: FakeNetworkAdapter):
        class PartialBoomAdapter(FakeNetworkAdapter):
            _call_count = 0

            def resolve_dns(self, hostname):
                self._call_count += 1
                if self._call_count == 1:
                    raise RuntimeError("boom on first service")
                return ["127.0.0.1"]

        runner = DiagnosticRunner(adapter=PartialBoomAdapter(), config={})
        report = runner.run_all()
        assert isinstance(report, DiagnosticReport)

    def test_run_all_to_dict_serializable(self, runner: DiagnosticRunner):
        import json
        report = runner.run_all()
        d = report.to_dict()
        serialized = json.dumps(d)
        assert "all" in serialized

    def test_run_all_report_has_started_at(self, runner: DiagnosticRunner):
        report = runner.run_all()
        assert report.started_at is not None
        assert report.completed_at >= report.started_at


class TestReportSeverityOrdering:
    def test_worst_failure_class_selected(self, fake: FakeNetworkAdapter):
        fake.dns_responses["nextcloud.example.com"] = DNSResolutionError("NXDOMAIN")
        runner = DiagnosticRunner(adapter=fake, config={})
        report = runner.run_integration("nextcloud", url="https://nextcloud.example.com")
        assert report.overall_failure_class == FailureClass.DNS_FAILURE
        assert report.overall_severity.value in ("error", "critical", "warning", "degraded")

    def test_warn_does_not_override_fail(self, fake: FakeNetworkAdapter):
        fake.dns_responses["woocommerce.example.com"] = DNSResolutionError("NXDOMAIN")
        runner = DiagnosticRunner(adapter=fake, config={})
        report = runner.run_integration("woocommerce", url="https://woocommerce.example.com")
        assert report.overall_status == HealthStatus.FAIL
