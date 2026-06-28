"""CP1.2 — Connection Manager models.

ConnectionType, ConnectionStatus, CircuitState enums and ConnectionDefinition,
ConnectionResult dataclasses.  No credentials are stored here — transport only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from app.beta.control_plane.failure import FailureClass, Severity


class ConnectionType(str, Enum):
    NEXTCLOUD = "nextcloud"
    WOOCOMMERCE = "woocommerce"
    CURRENCY_API = "currency_api"
    SMTP = "smtp"
    GENERIC_HTTP = "generic_http"
    DATABASE = "database"


class ConnectionStatus(str, Enum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    DISABLED = "disabled"
    SKIPPED = "skipped"


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class ConnectionDefinition:
    """Parameters for a single registered connection."""

    name: str
    connection_type: ConnectionType
    enabled: bool
    required: bool
    endpoint: str
    timeout_seconds: float = 10.0
    retry_attempts: int = 2
    retry_backoff_seconds: float = 0.5
    cache_ttl_seconds: float = 60.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.timeout_seconds > 60.0:
            raise ValueError("timeout_seconds must not exceed 60 (hard limit).")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive.")


@dataclass
class ConnectionResult:
    """Result of a single connection probe."""

    name: str
    connection_type: ConnectionType
    status: ConnectionStatus
    reachable: Optional[bool]
    authenticated: Optional[bool]
    latency_ms: Optional[float]
    failure_class: FailureClass
    severity: Severity
    message: str
    repair_hint: str
    checked_at: datetime
    retryable: bool
    circuit_state: CircuitState
    from_cache: bool = False
    attempt_number: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "connection_type": self.connection_type.value,
            "status": self.status.value,
            "reachable": self.reachable,
            "authenticated": self.authenticated,
            "latency_ms": self.latency_ms,
            "failure_class": self.failure_class.value,
            "severity": self.severity.value,
            "message": self.message,
            "repair_hint": self.repair_hint,
            "checked_at": self.checked_at.isoformat(),
            "retryable": self.retryable,
            "circuit_state": self.circuit_state.value,
            "from_cache": self.from_cache,
            "attempt_number": self.attempt_number,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConnectionResult:
        return cls(
            name=data["name"],
            connection_type=ConnectionType(data["connection_type"]),
            status=ConnectionStatus(data["status"]),
            reachable=data.get("reachable"),
            authenticated=data.get("authenticated"),
            latency_ms=data.get("latency_ms"),
            failure_class=FailureClass(data["failure_class"]),
            severity=Severity(data["severity"]),
            message=data["message"],
            repair_hint=data.get("repair_hint", ""),
            checked_at=datetime.fromisoformat(data["checked_at"]),
            retryable=data.get("retryable", False),
            circuit_state=CircuitState(data["circuit_state"]),
            from_cache=data.get("from_cache", False),
            attempt_number=data.get("attempt_number", 1),
        )

    @classmethod
    def disabled(cls, definition: ConnectionDefinition) -> ConnectionResult:
        return cls(
            name=definition.name,
            connection_type=definition.connection_type,
            status=ConnectionStatus.DISABLED,
            reachable=None,
            authenticated=None,
            latency_ms=None,
            failure_class=FailureClass.NONE,
            severity=Severity.INFO,
            message="Connection is disabled.",
            repair_hint="Enable the connection in configuration to use it.",
            checked_at=datetime.now(tz=timezone.utc),
            retryable=False,
            circuit_state=CircuitState.CLOSED,
        )

    @classmethod
    def circuit_open(
        cls,
        definition: ConnectionDefinition,
        last_failure_class: FailureClass,
    ) -> ConnectionResult:
        meta = last_failure_class.meta
        return cls(
            name=definition.name,
            connection_type=definition.connection_type,
            status=ConnectionStatus.FAILED,
            reachable=None,
            authenticated=None,
            latency_ms=None,
            failure_class=last_failure_class,
            severity=Severity.ERROR,
            message="Circuit breaker is OPEN — connection suspended after repeated failures.",
            repair_hint=meta.operator_hint,
            checked_at=datetime.now(tz=timezone.utc),
            retryable=False,
            circuit_state=CircuitState.OPEN,
        )
