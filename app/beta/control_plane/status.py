"""Control Plane status aggregator.

ControlPlaneStatus is the top-level view of system health. The Control Plane
is always marked available=True regardless of integration health — that is the
core architectural invariant established by the production incident post-mortem.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from .availability import (
    FeatureAvailability,
    compute_all_features,
)
from .failure import FailureClass, Severity
from .models import EXTERNAL_INTEGRATION_TYPES, IntegrationState


@dataclass
class ControlPlaneStatus:
    """Aggregated Control Plane health view.

    Invariants (enforced by compute()):
        available  — always True; Control Plane never depends on Integration Plane
        degraded   — True iff at least one enabled integration is failing
        offline_mode — True iff all enabled external integrations are unreachable
        safe_mode  — True only when set explicitly by the caller; never inferred

    Fields:
        available        — Control Plane surfaces are accessible (always True)
        degraded         — at least one enabled integration is failing
        safe_mode        — operator-initiated safe mode (explicit only)
        offline_mode     — all external integrations are unreachable
        integrations     — map of integration name → IntegrationState
        features         — map of feature name → FeatureAvailability
        highest_severity — worst severity across all integrations and features
        summary          — human-readable one-line status
        generated_at     — UTC timestamp of this snapshot
    """

    available: bool
    degraded: bool
    safe_mode: bool
    offline_mode: bool
    integrations: dict[str, IntegrationState]
    features: dict[str, FeatureAvailability]
    highest_severity: Severity
    summary: str
    generated_at: datetime

    def to_dict(self) -> dict:
        return {
            "available": self.available,
            "degraded": self.degraded,
            "safe_mode": self.safe_mode,
            "offline_mode": self.offline_mode,
            "integrations": {
                k: v.to_dict() for k, v in self.integrations.items()
            },
            "features": {
                k: v.to_dict() for k, v in self.features.items()
            },
            "highest_severity": self.highest_severity.value,
            "summary": self.summary,
            "generated_at": self.generated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> ControlPlaneStatus:
        integrations = {
            k: IntegrationState.from_dict(v)
            for k, v in data.get("integrations", {}).items()
        }
        features = {
            k: FeatureAvailability.from_dict(v)
            for k, v in data.get("features", {}).items()
        }
        return cls(
            available=data["available"],
            degraded=data["degraded"],
            safe_mode=data["safe_mode"],
            offline_mode=data["offline_mode"],
            integrations=integrations,
            features=features,
            highest_severity=Severity(data["highest_severity"]),
            summary=data["summary"],
            generated_at=datetime.fromisoformat(data["generated_at"]),
        )

    @classmethod
    def compute(
        cls,
        integrations: dict[str, IntegrationState],
        features: Optional[dict[str, FeatureAvailability]] = None,
        safe_mode: bool = False,
        generated_at: Optional[datetime] = None,
    ) -> ControlPlaneStatus:
        """Compute ControlPlaneStatus from current integration snapshots.

        Args:
            integrations  — current state for each integration (name → state)
            features      — pre-computed features; computed from integrations if None
            safe_mode     — explicit operator flag; never inferred from health state
            generated_at  — override snapshot timestamp (useful in tests)
        """
        now = generated_at or datetime.now(tz=timezone.utc)

        enabled = [s for s in integrations.values() if s.enabled]
        failing = [s for s in enabled if s.is_failing()]

        external_enabled = [
            s for s in enabled
            if s.integration_type in EXTERNAL_INTEGRATION_TYPES
        ]
        external_failing = [s for s in external_enabled if s.is_failing()]

        degraded = len(failing) > 0
        offline_mode = (
            len(external_enabled) > 0
            and len(external_failing) == len(external_enabled)
        )

        resolved_features = features if features is not None else compute_all_features(integrations)

        int_severities = [s.severity for s in integrations.values()]
        feat_severities = [f.severity for f in resolved_features.values()]
        highest = Severity.highest(int_severities + feat_severities)

        if not degraded:
            summary = "All systems operational."
        elif offline_mode:
            summary = (
                "All external integrations are unreachable. "
                "Administrative features remain available."
            )
        else:
            names = ", ".join(s.name for s in failing)
            summary = (
                f"Degraded: {names} unavailable. "
                "Administrative features remain available."
            )

        return cls(
            available=True,
            degraded=degraded,
            safe_mode=safe_mode,
            offline_mode=offline_mode,
            integrations=integrations,
            features=resolved_features,
            highest_severity=highest,
            summary=summary,
            generated_at=now,
        )
