"""CP1.2 — Health check aggregation logic.

Aggregates a list of HealthCheckResult into a SystemHealthSummary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from app.beta.control_plane.failure import FailureClass, Severity

from .models import CheckCategory, HealthCheckResult, HealthStatus


# Severity ordering contribution from each HealthStatus
_STATUS_TO_SEVERITY: dict[HealthStatus, Severity] = {
    HealthStatus.PASS: Severity.INFO,
    HealthStatus.WARN: Severity.WARNING,
    HealthStatus.FAIL: Severity.ERROR,
    HealthStatus.SKIP: Severity.INFO,
    HealthStatus.UNKNOWN: Severity.INFO,
}


@dataclass
class SystemHealthSummary:
    """Aggregated system health across all checks."""

    overall_status: HealthStatus
    highest_severity: Severity
    total_checks: int
    passed: int
    warned: int
    failed: int
    skipped: int
    unknown: int
    results: list[HealthCheckResult] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))

    def to_dict(self) -> dict:
        return {
            "overall_status": self.overall_status.value,
            "highest_severity": self.highest_severity.value,
            "total_checks": self.total_checks,
            "passed": self.passed,
            "warned": self.warned,
            "failed": self.failed,
            "skipped": self.skipped,
            "unknown": self.unknown,
            "generated_at": self.generated_at.isoformat(),
            "results": [r.to_dict() for r in self.results],
        }


def aggregate_results(results: list[HealthCheckResult]) -> SystemHealthSummary:
    """Compute the SystemHealthSummary from a list of HealthCheckResult.

    Rules:
    - overall_status is FAIL if any result is FAIL
    - overall_status is WARN if any result is WARN (and none are FAIL)
    - overall_status is PASS if all non-SKIP results pass
    - SKIP and UNKNOWN results are not counted against overall health
    - highest_severity uses Severity.highest() from CP1.1
    """
    if not results:
        return SystemHealthSummary(
            overall_status=HealthStatus.UNKNOWN,
            highest_severity=Severity.INFO,
            total_checks=0,
            passed=0,
            warned=0,
            failed=0,
            skipped=0,
            unknown=0,
            results=[],
        )

    passed = sum(1 for r in results if r.status == HealthStatus.PASS)
    warned = sum(1 for r in results if r.status == HealthStatus.WARN)
    failed = sum(1 for r in results if r.status == HealthStatus.FAIL)
    skipped = sum(1 for r in results if r.status == HealthStatus.SKIP)
    unknown = sum(1 for r in results if r.status == HealthStatus.UNKNOWN)

    severities = [_STATUS_TO_SEVERITY[r.status] for r in results]
    highest = Severity.highest(severities)

    if failed > 0:
        overall = HealthStatus.FAIL
    elif warned > 0:
        overall = HealthStatus.WARN
    elif unknown > 0 and passed == 0:
        overall = HealthStatus.UNKNOWN
    elif passed > 0 or skipped == len(results):
        overall = HealthStatus.PASS
    else:
        overall = HealthStatus.UNKNOWN

    return SystemHealthSummary(
        overall_status=overall,
        highest_severity=highest,
        total_checks=len(results),
        passed=passed,
        warned=warned,
        failed=failed,
        skipped=skipped,
        unknown=unknown,
        results=list(results),
    )


def worst_result(results: list[HealthCheckResult]) -> Optional[HealthCheckResult]:
    """Return the result with the highest-priority failure status, or None."""
    if not results:
        return None
    order = {
        HealthStatus.FAIL: 4,
        HealthStatus.WARN: 3,
        HealthStatus.UNKNOWN: 2,
        HealthStatus.SKIP: 1,
        HealthStatus.PASS: 0,
    }
    return max(results, key=lambda r: order.get(r.status, 0))


def filter_by_category(
    results: list[HealthCheckResult],
    category: CheckCategory,
) -> list[HealthCheckResult]:
    return [r for r in results if r.category == category]


def filter_failed(results: list[HealthCheckResult]) -> list[HealthCheckResult]:
    return [r for r in results if r.status == HealthStatus.FAIL]
