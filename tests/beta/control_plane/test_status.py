"""Tests for app.beta.control_plane.status — ControlPlaneStatus."""

import json
from datetime import datetime, timezone

import pytest

from app.beta.control_plane.availability import FeatureName
from app.beta.control_plane.failure import FailureClass, Severity
from app.beta.control_plane.models import IntegrationState, IntegrationType
from app.beta.control_plane.status import ControlPlaneStatus

FIXED_TS = datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc)

_SECRET_PATTERNS = [
    "password", "secret", "token", "credential",
    "nc_pass", "cs_test", "ck_test", "jwt",
]


def _ok(name: str, itype: IntegrationType = IntegrationType.NEXTCLOUD) -> IntegrationState:
    return IntegrationState.create_ok(name, itype, checked_at=FIXED_TS)


def _failing(
    name: str,
    itype: IntegrationType,
    fc: FailureClass = FailureClass.DNS_FAILURE,
) -> IntegrationState:
    return IntegrationState.create_failing(name, itype, fc, checked_at=FIXED_TS)


class TestControlPlaneAlwaysAvailable:
    """Core invariant: Control Plane is available regardless of integration health."""

    def test_available_with_no_integrations(self):
        status = ControlPlaneStatus.compute({}, generated_at=FIXED_TS)
        assert status.available is True

    def test_available_with_all_integrations_ok(self):
        integrations = {
            "nextcloud": _ok("nextcloud", IntegrationType.NEXTCLOUD),
            "woocommerce": _ok("woocommerce", IntegrationType.WOOCOMMERCE),
        }
        status = ControlPlaneStatus.compute(integrations, generated_at=FIXED_TS)
        assert status.available is True

    def test_available_when_all_external_integrations_fail(self):
        integrations = {
            "nextcloud": _failing("nextcloud", IntegrationType.NEXTCLOUD, FailureClass.DNS_FAILURE),
            "woocommerce": _failing("woocommerce", IntegrationType.WOOCOMMERCE, FailureClass.TLS_FAILURE),
        }
        status = ControlPlaneStatus.compute(integrations, generated_at=FIXED_TS)
        assert status.available is True

    def test_available_with_database_and_storage_failures(self):
        integrations = {
            "db": _failing("db", IntegrationType.DATABASE, FailureClass.DATABASE_ERROR),
            "storage": _failing("storage", IntegrationType.STORAGE, FailureClass.STORAGE_ERROR),
        }
        status = ControlPlaneStatus.compute(integrations, generated_at=FIXED_TS)
        assert status.available is True


class TestDegradedMode:
    def test_not_degraded_when_all_ok(self):
        integrations = {
            "nextcloud": _ok("nextcloud", IntegrationType.NEXTCLOUD),
        }
        status = ControlPlaneStatus.compute(integrations, generated_at=FIXED_TS)
        assert status.degraded is False

    def test_degraded_when_one_integration_fails(self):
        integrations = {
            "nextcloud": _failing("nextcloud", IntegrationType.NEXTCLOUD, FailureClass.DNS_FAILURE),
            "woocommerce": _ok("woocommerce", IntegrationType.WOOCOMMERCE),
        }
        status = ControlPlaneStatus.compute(integrations, generated_at=FIXED_TS)
        assert status.degraded is True

    def test_degraded_when_all_integrations_fail(self):
        integrations = {
            "nextcloud": _failing("nextcloud", IntegrationType.NEXTCLOUD, FailureClass.DNS_FAILURE),
            "woocommerce": _failing("woocommerce", IntegrationType.WOOCOMMERCE, FailureClass.TLS_FAILURE),
        }
        status = ControlPlaneStatus.compute(integrations, generated_at=FIXED_TS)
        assert status.degraded is True

    def test_not_degraded_with_empty_integrations(self):
        status = ControlPlaneStatus.compute({}, generated_at=FIXED_TS)
        assert status.degraded is False

    def test_not_degraded_when_failing_integration_is_disabled(self):
        state = IntegrationState(
            name="nextcloud",
            integration_type=IntegrationType.NEXTCLOUD,
            enabled=False,
            configured=True,
            reachable=False,
            authenticated=None,
            last_success_at=None,
            last_checked_at=FIXED_TS,
            failure_class=FailureClass.DNS_FAILURE,
            severity=Severity.ERROR,
            message="DNS failed.",
            repair_hint="check url",
        )
        status = ControlPlaneStatus.compute({"nextcloud": state}, generated_at=FIXED_TS)
        assert status.degraded is False


class TestOfflineMode:
    def test_offline_when_all_external_integrations_fail(self):
        integrations = {
            "nextcloud": _failing("nextcloud", IntegrationType.NEXTCLOUD, FailureClass.UNREACHABLE),
            "woocommerce": _failing("woocommerce", IntegrationType.WOOCOMMERCE, FailureClass.UNREACHABLE),
        }
        status = ControlPlaneStatus.compute(integrations, generated_at=FIXED_TS)
        assert status.offline_mode is True

    def test_not_offline_when_one_external_ok(self):
        integrations = {
            "nextcloud": _failing("nextcloud", IntegrationType.NEXTCLOUD, FailureClass.DNS_FAILURE),
            "woocommerce": _ok("woocommerce", IntegrationType.WOOCOMMERCE),
        }
        status = ControlPlaneStatus.compute(integrations, generated_at=FIXED_TS)
        assert status.offline_mode is False

    def test_not_offline_with_no_external_integrations(self):
        integrations = {
            "db": _failing("db", IntegrationType.DATABASE, FailureClass.DATABASE_ERROR),
        }
        status = ControlPlaneStatus.compute(integrations, generated_at=FIXED_TS)
        assert status.offline_mode is False

    def test_not_offline_with_empty_integrations(self):
        status = ControlPlaneStatus.compute({}, generated_at=FIXED_TS)
        assert status.offline_mode is False

    def test_offline_does_not_affect_available(self):
        integrations = {
            "nextcloud": _failing("nextcloud", IntegrationType.NEXTCLOUD, FailureClass.DNS_FAILURE),
        }
        status = ControlPlaneStatus.compute(integrations, generated_at=FIXED_TS)
        assert status.offline_mode is True
        assert status.available is True  # invariant holds in offline mode

    def test_external_and_local_both_failing_is_offline(self):
        """Offline mode counts only external integrations."""
        integrations = {
            "nextcloud": _failing("nextcloud", IntegrationType.NEXTCLOUD, FailureClass.DNS_FAILURE),
            "db": _failing("db", IntegrationType.DATABASE, FailureClass.DATABASE_ERROR),
        }
        status = ControlPlaneStatus.compute(integrations, generated_at=FIXED_TS)
        # Only nextcloud is external; it's failing → offline_mode=True
        assert status.offline_mode is True


class TestSafeMode:
    def test_safe_mode_false_by_default(self):
        status = ControlPlaneStatus.compute({}, generated_at=FIXED_TS)
        assert status.safe_mode is False

    def test_safe_mode_set_explicitly(self):
        status = ControlPlaneStatus.compute({}, safe_mode=True, generated_at=FIXED_TS)
        assert status.safe_mode is True

    def test_safe_mode_not_inferred_from_offline(self):
        integrations = {
            "nextcloud": _failing("nextcloud", IntegrationType.NEXTCLOUD, FailureClass.DNS_FAILURE),
        }
        status = ControlPlaneStatus.compute(integrations, generated_at=FIXED_TS)
        assert status.safe_mode is False  # offline does not imply safe_mode

    def test_safe_mode_not_inferred_from_degraded(self):
        integrations = {
            "nextcloud": _failing("nextcloud", IntegrationType.NEXTCLOUD, FailureClass.TIMEOUT),
        }
        status = ControlPlaneStatus.compute(integrations, generated_at=FIXED_TS)
        assert status.safe_mode is False

    def test_safe_mode_and_degraded_can_coexist(self):
        integrations = {
            "nextcloud": _failing("nextcloud", IntegrationType.NEXTCLOUD, FailureClass.DNS_FAILURE),
        }
        status = ControlPlaneStatus.compute(integrations, safe_mode=True, generated_at=FIXED_TS)
        assert status.safe_mode is True
        assert status.degraded is True


class TestHighestSeverityAggregation:
    def test_info_when_all_healthy(self):
        integrations = {
            "nextcloud": _ok("nextcloud", IntegrationType.NEXTCLOUD),
        }
        status = ControlPlaneStatus.compute(integrations, generated_at=FIXED_TS)
        assert status.highest_severity == Severity.INFO

    def test_error_from_dns_failure(self):
        integrations = {
            "nextcloud": _failing("nextcloud", IntegrationType.NEXTCLOUD, FailureClass.DNS_FAILURE),
        }
        status = ControlPlaneStatus.compute(integrations, generated_at=FIXED_TS)
        assert status.highest_severity == Severity.ERROR

    def test_critical_from_configuration_error(self):
        integrations = {
            "nextcloud": _failing("nextcloud", IntegrationType.NEXTCLOUD, FailureClass.CONFIGURATION_ERROR),
        }
        status = ControlPlaneStatus.compute(integrations, generated_at=FIXED_TS)
        assert status.highest_severity == Severity.CRITICAL

    def test_highest_wins_across_mixed_severities(self):
        integrations = {
            "nextcloud": _failing("nextcloud", IntegrationType.NEXTCLOUD, FailureClass.TIMEOUT),       # WARNING
            "woocommerce": _failing("woocommerce", IntegrationType.WOOCOMMERCE, FailureClass.DNS_FAILURE),  # ERROR
        }
        status = ControlPlaneStatus.compute(integrations, generated_at=FIXED_TS)
        assert status.highest_severity == Severity.ERROR

    def test_critical_beats_all_other_severities(self):
        integrations = {
            "nextcloud": _failing("nextcloud", IntegrationType.NEXTCLOUD, FailureClass.DATABASE_ERROR),  # CRITICAL
            "woocommerce": _failing("woocommerce", IntegrationType.WOOCOMMERCE, FailureClass.DNS_FAILURE),  # ERROR
        }
        status = ControlPlaneStatus.compute(integrations, generated_at=FIXED_TS)
        assert status.highest_severity == Severity.CRITICAL


class TestSummaryText:
    def test_summary_operational_when_healthy(self):
        status = ControlPlaneStatus.compute({}, generated_at=FIXED_TS)
        assert "operational" in status.summary.lower()

    def test_summary_mentions_degraded_integration(self):
        # Two external integrations: one ok, one failing → degraded (not offline)
        integrations = {
            "nextcloud": _failing("nextcloud", IntegrationType.NEXTCLOUD, FailureClass.DNS_FAILURE),
            "woocommerce": _ok("woocommerce", IntegrationType.WOOCOMMERCE),
        }
        status = ControlPlaneStatus.compute(integrations, generated_at=FIXED_TS)
        assert status.offline_mode is False  # precondition
        assert "nextcloud" in status.summary.lower()

    def test_summary_mentions_admin_available_in_degraded(self):
        integrations = {
            "nextcloud": _failing("nextcloud", IntegrationType.NEXTCLOUD, FailureClass.DNS_FAILURE),
        }
        status = ControlPlaneStatus.compute(integrations, generated_at=FIXED_TS)
        # Invariant must be surfaced to user
        assert "administrative" in status.summary.lower() or "admin" in status.summary.lower()

    def test_offline_summary_references_external_integrations(self):
        integrations = {
            "nextcloud": _failing("nextcloud", IntegrationType.NEXTCLOUD, FailureClass.UNREACHABLE),
            "woocommerce": _failing("woocommerce", IntegrationType.WOOCOMMERCE, FailureClass.UNREACHABLE),
        }
        status = ControlPlaneStatus.compute(integrations, generated_at=FIXED_TS)
        assert "external" in status.summary.lower() or "unreachable" in status.summary.lower()


class TestControlPlaneStatusSerialization:
    def test_to_dict_roundtrip_all_ok(self):
        integrations = {
            "nextcloud": _ok("nextcloud", IntegrationType.NEXTCLOUD),
        }
        status = ControlPlaneStatus.compute(integrations, generated_at=FIXED_TS)
        restored = ControlPlaneStatus.from_dict(status.to_dict())
        assert restored.available == status.available
        assert restored.degraded == status.degraded
        assert restored.safe_mode == status.safe_mode
        assert restored.offline_mode == status.offline_mode
        assert restored.highest_severity == status.highest_severity
        assert restored.summary == status.summary
        assert "nextcloud" in restored.integrations

    def test_to_dict_roundtrip_with_failure(self):
        integrations = {
            "nextcloud": _failing("nextcloud", IntegrationType.NEXTCLOUD, FailureClass.DNS_FAILURE),
        }
        status = ControlPlaneStatus.compute(integrations, generated_at=FIXED_TS)
        restored = ControlPlaneStatus.from_dict(status.to_dict())
        assert restored.degraded is True
        assert restored.integrations["nextcloud"].failure_class == FailureClass.DNS_FAILURE

    def test_to_dict_is_json_serialisable(self):
        integrations = {
            "nextcloud": _ok("nextcloud", IntegrationType.NEXTCLOUD),
            "woocommerce": _failing("woocommerce", IntegrationType.WOOCOMMERCE, FailureClass.TLS_FAILURE),
        }
        status = ControlPlaneStatus.compute(integrations, generated_at=FIXED_TS)
        json.dumps(status.to_dict())  # must not raise

    def test_to_dict_no_secrets_in_output(self):
        integrations = {
            "nextcloud": _ok("nextcloud", IntegrationType.NEXTCLOUD),
        }
        status = ControlPlaneStatus.compute(integrations, generated_at=FIXED_TS)
        serialised = json.dumps(status.to_dict()).lower()
        for pat in _SECRET_PATTERNS:
            assert pat not in serialised, f"Secret pattern '{pat}' found in serialised output"

    def test_to_dict_enum_values_are_strings(self):
        status = ControlPlaneStatus.compute({}, generated_at=FIXED_TS)
        d = status.to_dict()
        assert isinstance(d["highest_severity"], str)

    def test_to_dict_features_included(self):
        status = ControlPlaneStatus.compute({}, generated_at=FIXED_TS)
        d = status.to_dict()
        assert isinstance(d["features"], dict)
        assert FeatureName.SETTINGS.value in d["features"]

    def test_to_dict_integrations_included(self):
        integrations = {"nextcloud": _ok("nextcloud", IntegrationType.NEXTCLOUD)}
        status = ControlPlaneStatus.compute(integrations, generated_at=FIXED_TS)
        d = status.to_dict()
        assert "nextcloud" in d["integrations"]

    def test_generated_at_in_output(self):
        status = ControlPlaneStatus.compute({}, generated_at=FIXED_TS)
        d = status.to_dict()
        assert "generated_at" in d
        assert "2026-06-28" in d["generated_at"]
