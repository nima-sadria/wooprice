"""WooPrice Beta — Control Plane package.

Exports the public surface for CP1.1: core models, failure taxonomy,
feature availability, and status aggregation.

CP1.2 will add: ConnectionManager, HealthEngine.
CP1.3 will add: DiagnosticRunner, RuntimeConfigService, CLI/API contracts.
"""

from .availability import (
    CONTROL_PLANE_FEATURES,
    FeatureAvailability,
    FeatureName,
    compute_all_features,
    compute_feature_availability,
)
from .failure import FailureClass, FailureClassMeta, Severity
from .models import EXTERNAL_INTEGRATION_TYPES, IntegrationState, IntegrationType
from .status import ControlPlaneStatus

__all__ = [
    # Failure taxonomy
    "FailureClass",
    "FailureClassMeta",
    "Severity",
    # Integration state
    "IntegrationType",
    "IntegrationState",
    "EXTERNAL_INTEGRATION_TYPES",
    # Feature availability
    "FeatureName",
    "FeatureAvailability",
    "CONTROL_PLANE_FEATURES",
    "compute_feature_availability",
    "compute_all_features",
    # Status
    "ControlPlaneStatus",
]
