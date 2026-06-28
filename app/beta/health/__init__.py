"""CP1.2 — Health Engine package.

Public API:
    HealthEngine        — orchestrator for health checks
    HealthCheckResult   — structured result of a single health check
    HealthStatus        — enum: PASS / WARN / FAIL / SKIP / UNKNOWN
    CheckCategory       — enum: DNS / TCP / TLS / HTTP / AUTH / CONFIG / STORAGE / DATABASE / DOCKER / INTEGRATION
    SystemHealthSummary — aggregated health across all checks
    aggregate_results   — aggregate a list of HealthCheckResult
"""

from .aggregation import SystemHealthSummary, aggregate_results
from .engine import HealthEngine
from .models import CheckCategory, HealthCheckResult, HealthStatus

__all__ = [
    "CheckCategory",
    "HealthCheckResult",
    "HealthEngine",
    "HealthStatus",
    "SystemHealthSummary",
    "aggregate_results",
]
