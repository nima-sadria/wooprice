"""CP1.2 — Health Engine models.

HealthStatus, CheckCategory, HealthCheckResult.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from app.beta.control_plane.failure import FailureClass, Severity


class HealthStatus(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"
    UNKNOWN = "unknown"


class CheckCategory(str, Enum):
    DNS = "dns"
    TCP = "tcp"
    TLS = "tls"
    HTTP = "http"
    AUTH = "auth"
    CONFIG = "config"
    STORAGE = "storage"
    DATABASE = "database"
    DOCKER = "docker"
    INTEGRATION = "integration"


# Maps HealthStatus → worst-case Severity for aggregation
_STATUS_SEVERITY: dict[HealthStatus, Severity] = {
    HealthStatus.PASS: Severity.INFO,
    HealthStatus.WARN: Severity.WARNING,
    HealthStatus.FAIL: Severity.ERROR,
    HealthStatus.SKIP: Severity.INFO,
    HealthStatus.UNKNOWN: Severity.INFO,
}


@dataclass
class HealthCheckResult:
    """Structured result of a single health check."""

    check_name: str
    category: CheckCategory
    target: str
    status: HealthStatus
    severity: Severity
    failure_class: FailureClass
    message: str
    repair_hint: str
    duration_ms: float
    checked_at: datetime
    details: dict[str, Any] = field(default_factory=dict)
    skipped_because: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_name": self.check_name,
            "category": self.category.value,
            "target": self.target,
            "status": self.status.value,
            "severity": self.severity.value,
            "failure_class": self.failure_class.value,
            "message": self.message,
            "repair_hint": self.repair_hint,
            "duration_ms": self.duration_ms,
            "checked_at": self.checked_at.isoformat(),
            "details": self.details,
            "skipped_because": self.skipped_because,
        }

    # ------------------------------------------------------------------
    # Factory constructors
    # ------------------------------------------------------------------

    @classmethod
    def ok(
        cls,
        check_name: str,
        category: CheckCategory,
        target: str,
        message: str,
        duration_ms: float = 0.0,
        details: Optional[dict[str, Any]] = None,
    ) -> HealthCheckResult:
        return cls(
            check_name=check_name,
            category=category,
            target=target,
            status=HealthStatus.PASS,
            severity=Severity.INFO,
            failure_class=FailureClass.NONE,
            message=message,
            repair_hint="",
            duration_ms=duration_ms,
            checked_at=datetime.now(tz=timezone.utc),
            details=details or {},
        )

    @classmethod
    def warn(
        cls,
        check_name: str,
        category: CheckCategory,
        target: str,
        message: str,
        repair_hint: str = "",
        duration_ms: float = 0.0,
        details: Optional[dict[str, Any]] = None,
        failure_class: FailureClass = FailureClass.NONE,
    ) -> HealthCheckResult:
        return cls(
            check_name=check_name,
            category=category,
            target=target,
            status=HealthStatus.WARN,
            severity=Severity.WARNING,
            failure_class=failure_class,
            message=message,
            repair_hint=repair_hint,
            duration_ms=duration_ms,
            checked_at=datetime.now(tz=timezone.utc),
            details=details or {},
        )

    @classmethod
    def fail(
        cls,
        check_name: str,
        category: CheckCategory,
        target: str,
        failure_class: FailureClass,
        message: str,
        repair_hint: str = "",
        duration_ms: float = 0.0,
        details: Optional[dict[str, Any]] = None,
    ) -> HealthCheckResult:
        meta = failure_class.meta
        return cls(
            check_name=check_name,
            category=category,
            target=target,
            status=HealthStatus.FAIL,
            severity=meta.severity_default,
            failure_class=failure_class,
            message=message,
            repair_hint=repair_hint or meta.operator_hint,
            duration_ms=duration_ms,
            checked_at=datetime.now(tz=timezone.utc),
            details=details or {},
        )

    @classmethod
    def skip(
        cls,
        check_name: str,
        category: CheckCategory,
        target: str,
        skipped_because: str,
        message: str = "",
    ) -> HealthCheckResult:
        return cls(
            check_name=check_name,
            category=category,
            target=target,
            status=HealthStatus.SKIP,
            severity=Severity.INFO,
            failure_class=FailureClass.NONE,
            message=message or f"Skipped — prerequisite '{skipped_because}' did not pass.",
            repair_hint="",
            duration_ms=0.0,
            checked_at=datetime.now(tz=timezone.utc),
            details={},
            skipped_because=skipped_because,
        )

    @classmethod
    def stub_skip(
        cls,
        check_name: str,
        category: CheckCategory,
        target: str = "",
        reason: str = "Not available in this phase.",
    ) -> HealthCheckResult:
        """Stub result for checks not yet implemented (e.g. Docker in CP1)."""
        return cls(
            check_name=check_name,
            category=category,
            target=target,
            status=HealthStatus.SKIP,
            severity=Severity.INFO,
            failure_class=FailureClass.NONE,
            message=reason,
            repair_hint="",
            duration_ms=0.0,
            checked_at=datetime.now(tz=timezone.utc),
            details={},
            skipped_because="not_implemented",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def is_blocking(self) -> bool:
        """True if this result should cause downstream checks to be skipped.

        Both FAIL and SKIP are blocking — a skipped prerequisite means the
        downstream check cannot proceed either.
        """
        return self.status in (HealthStatus.FAIL, HealthStatus.SKIP)
