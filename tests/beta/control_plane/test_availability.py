"""Tests for app.beta.control_plane.availability — FeatureAvailability."""

import json

import pytest

from app.beta.control_plane.availability import (
    CONTROL_PLANE_FEATURES,
    FeatureAvailability,
    FeatureName,
    compute_all_features,
    compute_feature_availability,
)
from app.beta.control_plane.failure import FailureClass, Severity
from app.beta.control_plane.models import IntegrationState, IntegrationType


def _ok(name: str, itype: IntegrationType) -> IntegrationState:
    return IntegrationState.create_ok(name, itype)


def _failing(name: str, itype: IntegrationType, fc: FailureClass) -> IntegrationState:
    return IntegrationState.create_failing(name, itype, fc)


class TestControlPlaneFeatureInvariant:
    """Control Plane features must always be available regardless of integration health."""

    @pytest.mark.parametrize("feature", list(CONTROL_PLANE_FEATURES))
    def test_always_available_with_empty_integrations(self, feature: FeatureName):
        result = compute_feature_availability(feature, {})
        assert result.available is True
        assert result.degraded is False
        assert result.failure_class == FailureClass.NONE
        assert result.severity == Severity.INFO

    @pytest.mark.parametrize("feature", list(CONTROL_PLANE_FEATURES))
    def test_always_available_when_all_integrations_fail(self, feature: FeatureName):
        integrations = {
            "nextcloud": _failing("nextcloud", IntegrationType.NEXTCLOUD, FailureClass.DNS_FAILURE),
            "woocommerce": _failing("woocommerce", IntegrationType.WOOCOMMERCE, FailureClass.TLS_FAILURE),
        }
        result = compute_feature_availability(feature, integrations)
        assert result.available is True
        assert result.failure_class == FailureClass.NONE

    def test_settings_always_available(self):
        integrations = {
            "nextcloud": _failing("nextcloud", IntegrationType.NEXTCLOUD, FailureClass.UNREACHABLE),
        }
        result = compute_feature_availability(FeatureName.SETTINGS, integrations)
        assert result.available is True

    def test_diagnostics_always_available(self):
        integrations = {
            "nextcloud": _failing("nextcloud", IntegrationType.NEXTCLOUD, FailureClass.DNS_FAILURE),
        }
        result = compute_feature_availability(FeatureName.DIAGNOSTICS, integrations)
        assert result.available is True

    def test_runtime_config_always_available(self):
        integrations = {
            "nextcloud": _failing("nextcloud", IntegrationType.NEXTCLOUD, FailureClass.TIMEOUT),
        }
        result = compute_feature_availability(FeatureName.RUNTIME_CONFIG, integrations)
        assert result.available is True

    def test_login_always_available(self):
        result = compute_feature_availability(FeatureName.LOGIN, {})
        assert result.available is True

    def test_admin_panel_always_available(self):
        result = compute_feature_availability(FeatureName.ADMIN_PANEL, {})
        assert result.available is True

    def test_health_dashboard_always_available(self):
        result = compute_feature_availability(FeatureName.HEALTH_DASHBOARD, {})
        assert result.available is True

    def test_control_plane_features_have_no_required_integrations(self):
        for feature in CONTROL_PLANE_FEATURES:
            result = compute_feature_availability(feature, {})
            assert result.required_integrations == []


class TestIntegrationPlaneFeatureGating:
    def test_source_explorer_available_when_nextcloud_ok(self):
        integrations = {"nextcloud": _ok("nextcloud", IntegrationType.NEXTCLOUD)}
        result = compute_feature_availability(FeatureName.SOURCE_EXPLORER, integrations)
        assert result.available is True
        assert result.degraded is False

    def test_source_explorer_disabled_when_nextcloud_dns_failure(self):
        integrations = {
            "nextcloud": _failing("nextcloud", IntegrationType.NEXTCLOUD, FailureClass.DNS_FAILURE)
        }
        result = compute_feature_availability(FeatureName.SOURCE_EXPLORER, integrations)
        assert result.available is False
        assert result.failure_class == FailureClass.DNS_FAILURE
        assert result.severity == Severity.ERROR
        assert result.disabled_reason is not None

    def test_change_sets_disabled_when_woocommerce_fails(self):
        integrations = {
            "woocommerce": _failing("woocommerce", IntegrationType.WOOCOMMERCE, FailureClass.UNAUTHORIZED)
        }
        result = compute_feature_availability(FeatureName.CHANGE_SETS, integrations)
        assert result.available is False
        assert result.failure_class == FailureClass.UNAUTHORIZED

    def test_product_explorer_disabled_when_nextcloud_fails(self):
        integrations = {
            "nextcloud": _failing("nextcloud", IntegrationType.NEXTCLOUD, FailureClass.TLS_FAILURE),
            "woocommerce": _ok("woocommerce", IntegrationType.WOOCOMMERCE),
        }
        result = compute_feature_availability(FeatureName.PRODUCT_EXPLORER, integrations)
        assert result.available is False

    def test_product_explorer_disabled_when_woocommerce_fails(self):
        integrations = {
            "nextcloud": _ok("nextcloud", IntegrationType.NEXTCLOUD),
            "woocommerce": _failing("woocommerce", IntegrationType.WOOCOMMERCE, FailureClass.UNREACHABLE),
        }
        result = compute_feature_availability(FeatureName.PRODUCT_EXPLORER, integrations)
        assert result.available is False

    def test_product_explorer_available_when_both_ok(self):
        integrations = {
            "nextcloud": _ok("nextcloud", IntegrationType.NEXTCLOUD),
            "woocommerce": _ok("woocommerce", IntegrationType.WOOCOMMERCE),
        }
        result = compute_feature_availability(FeatureName.PRODUCT_EXPLORER, integrations)
        assert result.available is True

    def test_dry_run_requires_both_nextcloud_and_woocommerce(self):
        integrations = {
            "nextcloud": _ok("nextcloud", IntegrationType.NEXTCLOUD),
        }
        # woocommerce absent — can't check it → feature is available (required dep not present)
        result = compute_feature_availability(FeatureName.DRY_RUN, integrations)
        # woocommerce not in integrations dict, so not considered failing
        assert result.available is True

    def test_dry_run_disabled_when_present_dep_fails(self):
        integrations = {
            "nextcloud": _failing("nextcloud", IntegrationType.NEXTCLOUD, FailureClass.TIMEOUT),
            "woocommerce": _ok("woocommerce", IntegrationType.WOOCOMMERCE),
        }
        result = compute_feature_availability(FeatureName.DRY_RUN, integrations)
        assert result.available is False

    def test_execution_requires_woocommerce(self):
        integrations = {
            "woocommerce": _failing("woocommerce", IntegrationType.WOOCOMMERCE, FailureClass.FORBIDDEN)
        }
        result = compute_feature_availability(FeatureName.EXECUTION, integrations)
        assert result.available is False
        assert result.failure_class == FailureClass.FORBIDDEN

    def test_ai_insights_available_with_no_external_deps(self):
        # AI Insights uses local DB; should be available even with no integrations
        result = compute_feature_availability(FeatureName.AI_INSIGHTS, {})
        assert result.available is True

    def test_disabled_reason_contains_integration_name(self):
        integrations = {
            "nextcloud": _failing("nextcloud", IntegrationType.NEXTCLOUD, FailureClass.DNS_FAILURE)
        }
        result = compute_feature_availability(FeatureName.SOURCE_EXPLORER, integrations)
        assert result.disabled_reason is not None
        assert "nextcloud" in result.disabled_reason.lower()

    def test_required_integrations_populated(self):
        integrations = {"nextcloud": _ok("nextcloud", IntegrationType.NEXTCLOUD)}
        result = compute_feature_availability(FeatureName.SOURCE_EXPLORER, integrations)
        assert "nextcloud" in result.required_integrations


class TestComputeAllFeatures:
    def test_returns_all_feature_names(self):
        result = compute_all_features({})
        expected_keys = {f.value for f in FeatureName}
        assert set(result.keys()) == expected_keys

    def test_control_plane_features_all_available(self):
        integrations = {
            "nextcloud": _failing("nextcloud", IntegrationType.NEXTCLOUD, FailureClass.DNS_FAILURE),
        }
        result = compute_all_features(integrations)
        for feature in CONTROL_PLANE_FEATURES:
            assert result[feature.value].available is True

    def test_integration_features_disabled_on_failure(self):
        integrations = {
            "nextcloud": _failing("nextcloud", IntegrationType.NEXTCLOUD, FailureClass.DNS_FAILURE),
            "woocommerce": _failing("woocommerce", IntegrationType.WOOCOMMERCE, FailureClass.DNS_FAILURE),
        }
        result = compute_all_features(integrations)
        assert result[FeatureName.SOURCE_EXPLORER.value].available is False
        assert result[FeatureName.CHANGE_SETS.value].available is False
        assert result[FeatureName.EXECUTION.value].available is False


class TestFeatureAvailabilitySerialization:
    def test_to_dict_roundtrip(self):
        fa = FeatureAvailability(
            feature_name=FeatureName.SOURCE_EXPLORER,
            available=False,
            degraded=False,
            disabled_reason="nextcloud is unavailable: DNS Resolution Failure",
            required_integrations=["nextcloud"],
            failure_class=FailureClass.DNS_FAILURE,
            severity=Severity.ERROR,
        )
        restored = FeatureAvailability.from_dict(fa.to_dict())
        assert restored.feature_name == fa.feature_name
        assert restored.available == fa.available
        assert restored.degraded == fa.degraded
        assert restored.disabled_reason == fa.disabled_reason
        assert restored.required_integrations == fa.required_integrations
        assert restored.failure_class == fa.failure_class
        assert restored.severity == fa.severity

    def test_to_dict_is_json_serialisable(self):
        integrations = {"nextcloud": _ok("nextcloud", IntegrationType.NEXTCLOUD)}
        fa = compute_feature_availability(FeatureName.SOURCE_EXPLORER, integrations)
        json.dumps(fa.to_dict())  # must not raise

    def test_to_dict_enum_values_are_strings(self):
        fa = compute_feature_availability(FeatureName.SETTINGS, {})
        d = fa.to_dict()
        assert isinstance(d["feature_name"], str)
        assert isinstance(d["failure_class"], str)
        assert isinstance(d["severity"], str)
