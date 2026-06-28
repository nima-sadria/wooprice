"""Control Plane feature availability model.

FeatureAvailability maps each application feature to its current availability state
based on the health of required integrations. Control Plane features are always
available. Integration Plane features are gated on their required integrations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .failure import FailureClass, Severity
from .models import IntegrationState


class FeatureName(str, Enum):
    """All features known to the Control Plane availability system."""

    # Control Plane — must remain available at all times
    LOGIN = "login"
    SETTINGS = "settings"
    RUNTIME_CONFIG = "runtime_config"
    DIAGNOSTICS = "diagnostics"
    HEALTH_DASHBOARD = "health_dashboard"
    LOGS_VIEWER = "logs_viewer"
    ADMIN_PANEL = "admin_panel"
    FEATURE_FLAGS = "feature_flags"
    PLUGIN_MANAGER = "plugin_manager"
    BACKUP_RESTORE = "backup_restore"
    UPDATE_CONTROLS = "update_controls"

    # Integration Plane — may be disabled when dependencies are unavailable
    PRODUCT_EXPLORER = "product_explorer"
    SOURCE_EXPLORER = "source_explorer"
    CHANGE_SETS = "change_sets"
    DRY_RUN = "dry_run"
    EXECUTION = "execution"
    SCHEDULER = "scheduler"
    AI_INSIGHTS = "ai_insights"


# Features that belong to the Control Plane (invariant: always available).
CONTROL_PLANE_FEATURES: frozenset[FeatureName] = frozenset({
    FeatureName.LOGIN,
    FeatureName.SETTINGS,
    FeatureName.RUNTIME_CONFIG,
    FeatureName.DIAGNOSTICS,
    FeatureName.HEALTH_DASHBOARD,
    FeatureName.LOGS_VIEWER,
    FeatureName.ADMIN_PANEL,
    FeatureName.FEATURE_FLAGS,
    FeatureName.PLUGIN_MANAGER,
    FeatureName.BACKUP_RESTORE,
    FeatureName.UPDATE_CONTROLS,
})

# Integration dependencies for each Integration Plane feature.
# Values are logical integration names (IntegrationState.name).
_FEATURE_REQUIREMENTS: dict[FeatureName, list[str]] = {
    FeatureName.PRODUCT_EXPLORER: ["nextcloud", "woocommerce"],
    FeatureName.SOURCE_EXPLORER: ["nextcloud"],
    FeatureName.CHANGE_SETS: ["woocommerce"],
    FeatureName.DRY_RUN: ["nextcloud", "woocommerce"],
    FeatureName.EXECUTION: ["woocommerce"],
    FeatureName.SCHEDULER: ["woocommerce"],
    FeatureName.AI_INSIGHTS: [],  # uses local DB only; available even offline
}


@dataclass
class FeatureAvailability:
    """Availability state for one application feature.

    Fields:
        feature_name          — which feature this describes
        available             — feature can be used (may be degraded)
        degraded              — feature is available but with reduced functionality
        disabled_reason       — human-readable explanation when not available
        required_integrations — integration names this feature depends on
        failure_class         — cause of unavailability; NONE when available
        severity              — severity of the unavailability; INFO when ok
    """

    feature_name: FeatureName
    available: bool
    degraded: bool
    disabled_reason: Optional[str]
    required_integrations: list[str]
    failure_class: FailureClass
    severity: Severity

    def to_dict(self) -> dict:
        return {
            "feature_name": self.feature_name.value,
            "available": self.available,
            "degraded": self.degraded,
            "disabled_reason": self.disabled_reason,
            "required_integrations": list(self.required_integrations),
            "failure_class": self.failure_class.value,
            "severity": self.severity.value,
        }

    @classmethod
    def from_dict(cls, data: dict) -> FeatureAvailability:
        return cls(
            feature_name=FeatureName(data["feature_name"]),
            available=data["available"],
            degraded=data["degraded"],
            disabled_reason=data.get("disabled_reason"),
            required_integrations=list(data.get("required_integrations", [])),
            failure_class=FailureClass(data["failure_class"]),
            severity=Severity(data["severity"]),
        )


def compute_feature_availability(
    feature: FeatureName,
    integrations: dict[str, IntegrationState],
) -> FeatureAvailability:
    """Compute FeatureAvailability from the current integration snapshot.

    Control Plane features are always available and never degraded.
    Integration Plane features are disabled when any required integration is failing.
    """
    if feature in CONTROL_PLANE_FEATURES:
        return FeatureAvailability(
            feature_name=feature,
            available=True,
            degraded=False,
            disabled_reason=None,
            required_integrations=[],
            failure_class=FailureClass.NONE,
            severity=Severity.INFO,
        )

    required_names = _FEATURE_REQUIREMENTS.get(feature, [])

    failing: list[IntegrationState] = [
        integrations[req]
        for req in required_names
        if req in integrations and integrations[req].is_failing()
    ]

    if not failing:
        return FeatureAvailability(
            feature_name=feature,
            available=True,
            degraded=False,
            disabled_reason=None,
            required_integrations=required_names,
            failure_class=FailureClass.NONE,
            severity=Severity.INFO,
        )

    worst = max(failing, key=lambda s: s.severity)
    return FeatureAvailability(
        feature_name=feature,
        available=False,
        degraded=False,
        disabled_reason=(
            f"{worst.name} is unavailable: {worst.failure_class.label}"
        ),
        required_integrations=required_names,
        failure_class=worst.failure_class,
        severity=worst.severity,
    )


def compute_all_features(
    integrations: dict[str, IntegrationState],
) -> dict[str, FeatureAvailability]:
    """Compute FeatureAvailability for every known feature."""
    return {
        feature.value: compute_feature_availability(feature, integrations)
        for feature in FeatureName
    }
