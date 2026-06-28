"""CP1.3 — Diagnostic report models.

DiagnosticReport, DiagnosticCheckResult, DiagnosticCategory, RepairStep.
All output is secrets-safe — no credential values, no raw passwords.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from app.beta.control_plane.failure import FailureClass, Severity
from app.beta.health.models import HealthCheckResult, HealthStatus


class DiagnosticCategory(str, Enum):
    INTEGRATION = "integration"
    LOCAL = "local"
    CONFIG = "config"
    STORAGE = "storage"
    DATABASE = "database"
    DOCKER = "docker"


@dataclass
class RepairStep:
    """A single actionable repair instruction. Command is optional."""

    step_number: int
    description: str
    command: Optional[str] = None
    detail: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_number": self.step_number,
            "description": self.description,
            "command": self.command,
            "detail": self.detail,
        }


@dataclass
class DiagnosticCheckResult:
    """A single health check result enriched with diagnostic context."""

    check_name: str
    category: DiagnosticCategory
    target: str
    status: HealthStatus
    failure_class: FailureClass
    severity: Severity
    message: str
    repair_hint: str
    duration_ms: float
    checked_at: datetime
    details: dict[str, Any] = field(default_factory=dict)
    skipped_because: Optional[str] = None

    @classmethod
    def from_health_result(
        cls,
        result: HealthCheckResult,
        category: DiagnosticCategory,
    ) -> DiagnosticCheckResult:
        return cls(
            check_name=result.check_name,
            category=category,
            target=result.target,
            status=result.status,
            failure_class=result.failure_class,
            severity=result.severity,
            message=result.message,
            repair_hint=result.repair_hint,
            duration_ms=result.duration_ms,
            checked_at=result.checked_at,
            details=result.details,
            skipped_because=result.skipped_because,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_name": self.check_name,
            "category": self.category.value,
            "target": self.target,
            "status": self.status.value,
            "failure_class": self.failure_class.value,
            "severity": self.severity.value,
            "message": self.message,
            "repair_hint": self.repair_hint,
            "duration_ms": self.duration_ms,
            "checked_at": self.checked_at.isoformat(),
            "details": self.details,
            "skipped_because": self.skipped_because,
        }


@dataclass
class DiagnosticReport:
    """Full structured report returned by DiagnosticRunner."""

    target: str
    started_at: datetime
    completed_at: datetime
    overall_status: HealthStatus
    overall_failure_class: FailureClass
    overall_severity: Severity
    checks: list[DiagnosticCheckResult] = field(default_factory=list)
    repair_steps: list[RepairStep] = field(default_factory=list)
    summary: str = ""

    @property
    def duration_ms(self) -> float:
        delta = self.completed_at - self.started_at
        return delta.total_seconds() * 1000.0

    def failed_checks(self) -> list[DiagnosticCheckResult]:
        return [c for c in self.checks if c.status == HealthStatus.FAIL]

    def warn_checks(self) -> list[DiagnosticCheckResult]:
        return [c for c in self.checks if c.status == HealthStatus.WARN]

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "duration_ms": self.duration_ms,
            "overall_status": self.overall_status.value,
            "overall_failure_class": self.overall_failure_class.value,
            "overall_severity": self.overall_severity.value,
            "summary": self.summary,
            "checks": [c.to_dict() for c in self.checks],
            "repair_steps": [r.to_dict() for r in self.repair_steps],
        }
