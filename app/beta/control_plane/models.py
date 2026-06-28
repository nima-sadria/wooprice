"""Control Plane integration state model.

IntegrationState represents a point-in-time snapshot of one external service's
health. It carries the typed failure class so UI and CLI layers never need to
interpret raw exception messages.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from .failure import FailureClass, Severity


class IntegrationType(str, Enum):
    """Category of integration, used to determine offline-mode computation."""

    # External network integrations (count toward offline_mode)
    NEXTCLOUD = "nextcloud"
    WOOCOMMERCE = "woocommerce"
    CURRENCY_API = "currency_api"
    SMTP = "smtp"
    GENERIC_HTTP = "generic_http"

    # Local infrastructure (do not count toward offline_mode)
    DATABASE = "database"
    STORAGE = "storage"
    DOCKER = "docker"
    SCHEDULER = "scheduler"
    PLUGIN = "plugin"


# Types that represent external network services for offline-mode logic.
EXTERNAL_INTEGRATION_TYPES: frozenset[IntegrationType] = frozenset({
    IntegrationType.NEXTCLOUD,
    IntegrationType.WOOCOMMERCE,
    IntegrationType.CURRENCY_API,
    IntegrationType.SMTP,
    IntegrationType.GENERIC_HTTP,
})


@dataclass
class IntegrationState:
    """Point-in-time health snapshot for one integration.

    Fields:
        name             — logical identifier (e.g. "nextcloud", "woocommerce")
        integration_type — category for plane logic
        enabled          — operator has enabled this integration in config
        configured       — required config values are present and valid
        reachable        — TCP/TLS check passed; None = not yet checked
        authenticated    — auth check passed; None = not attempted
        last_success_at  — UTC timestamp of last successful health check
        last_checked_at  — UTC timestamp of most recent check attempt
        failure_class    — typed failure; NONE when healthy
        severity         — derived from failure_class or overridden by checker
        message          — operator-safe description; never contains secrets
        repair_hint      — actionable repair guidance; never contains secrets
    """

    name: str
    integration_type: IntegrationType
    enabled: bool
    configured: bool
    reachable: Optional[bool]
    authenticated: Optional[bool]
    last_success_at: Optional[datetime]
    last_checked_at: Optional[datetime]
    failure_class: FailureClass
    severity: Severity
    message: str
    repair_hint: str

    def is_operational(self) -> bool:
        """True iff all checks explicitly passed (reachable=True, auth passed, no failure)."""
        return (
            self.enabled
            and self.configured
            and self.reachable is True
            and self.authenticated is True
            and self.failure_class == FailureClass.NONE
        )

    def is_failing(self) -> bool:
        """True iff enabled and at least one check explicitly failed.

        None values (not yet checked) do not count as failures. This prevents
        unchecked integrations from incorrectly triggering degraded mode at
        startup before the first health check run.
        """
        if not self.enabled:
            return False
        if not self.configured:
            return True
        if self.reachable is False:
            return True
        if self.authenticated is False:
            return True
        if self.failure_class != FailureClass.NONE:
            return True
        return False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "integration_type": self.integration_type.value,
            "enabled": self.enabled,
            "configured": self.configured,
            "reachable": self.reachable,
            "authenticated": self.authenticated,
            "last_success_at": (
                self.last_success_at.isoformat() if self.last_success_at else None
            ),
            "last_checked_at": (
                self.last_checked_at.isoformat() if self.last_checked_at else None
            ),
            "failure_class": self.failure_class.value,
            "severity": self.severity.value,
            "message": self.message,
            "repair_hint": self.repair_hint,
        }

    @classmethod
    def from_dict(cls, data: dict) -> IntegrationState:
        return cls(
            name=data["name"],
            integration_type=IntegrationType(data["integration_type"]),
            enabled=data["enabled"],
            configured=data["configured"],
            reachable=data.get("reachable"),
            authenticated=data.get("authenticated"),
            last_success_at=(
                datetime.fromisoformat(data["last_success_at"])
                if data.get("last_success_at")
                else None
            ),
            last_checked_at=(
                datetime.fromisoformat(data["last_checked_at"])
                if data.get("last_checked_at")
                else None
            ),
            failure_class=FailureClass(data["failure_class"]),
            severity=Severity(data["severity"]),
            message=data["message"],
            repair_hint=data["repair_hint"],
        )

    @classmethod
    def create_ok(
        cls,
        name: str,
        integration_type: IntegrationType,
        checked_at: Optional[datetime] = None,
    ) -> IntegrationState:
        """Factory: healthy integration snapshot."""
        now = checked_at or datetime.now(tz=timezone.utc)
        return cls(
            name=name,
            integration_type=integration_type,
            enabled=True,
            configured=True,
            reachable=True,
            authenticated=True,
            last_success_at=now,
            last_checked_at=now,
            failure_class=FailureClass.NONE,
            severity=Severity.INFO,
            message="Integration is operating normally.",
            repair_hint="",
        )

    @classmethod
    def create_failing(
        cls,
        name: str,
        integration_type: IntegrationType,
        failure_class: FailureClass,
        message: str = "",
        checked_at: Optional[datetime] = None,
        last_success_at: Optional[datetime] = None,
    ) -> IntegrationState:
        """Factory: failing integration snapshot with typed failure class."""
        fc_meta = failure_class.meta
        network_failures = {
            FailureClass.DNS_FAILURE,
            FailureClass.TCP_FAILURE,
            FailureClass.UNREACHABLE,
            FailureClass.TIMEOUT,
        }
        reachable = None if failure_class not in network_failures else False
        if failure_class == FailureClass.TLS_FAILURE:
            reachable = None  # TCP worked; TLS layer failed — ambiguous
        if failure_class in (FailureClass.UNAUTHORIZED, FailureClass.FORBIDDEN):
            reachable = True

        return cls(
            name=name,
            integration_type=integration_type,
            enabled=True,
            configured=True,
            reachable=reachable,
            authenticated=None,
            last_success_at=last_success_at,
            last_checked_at=checked_at or datetime.now(tz=timezone.utc),
            failure_class=failure_class,
            severity=fc_meta.severity_default,
            message=message or fc_meta.user_message,
            repair_hint=fc_meta.operator_hint,
        )
