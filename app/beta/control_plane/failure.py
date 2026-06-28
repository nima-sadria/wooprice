"""Control Plane failure taxonomy — FailureClass enum and Severity levels.

Every integration check returns exactly one FailureClass. Collapsing DNS or TLS
failures into generic messages is prohibited at every layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

_SEVERITY_ORDER: dict[str, int] = {
    "info": 0,
    "warning": 1,
    "degraded": 2,
    "error": 3,
    "critical": 4,
}


class Severity(str, Enum):
    """Ordered severity levels for integration failures and health states."""

    INFO = "info"
    WARNING = "warning"
    DEGRADED = "degraded"
    ERROR = "error"
    CRITICAL = "critical"

    def __lt__(self, other: object) -> bool:
        if isinstance(other, Severity):
            return _SEVERITY_ORDER[self.value] < _SEVERITY_ORDER[other.value]
        return NotImplemented

    def __le__(self, other: object) -> bool:
        if isinstance(other, Severity):
            return _SEVERITY_ORDER[self.value] <= _SEVERITY_ORDER[other.value]
        return NotImplemented

    def __gt__(self, other: object) -> bool:
        if isinstance(other, Severity):
            return _SEVERITY_ORDER[self.value] > _SEVERITY_ORDER[other.value]
        return NotImplemented

    def __ge__(self, other: object) -> bool:
        if isinstance(other, Severity):
            return _SEVERITY_ORDER[self.value] >= _SEVERITY_ORDER[other.value]
        return NotImplemented

    @classmethod
    def highest(cls, severities: Iterable[Severity]) -> Severity:
        """Return the highest severity from an iterable. Returns INFO if empty."""
        result = cls.INFO
        for s in severities:
            if s > result:
                result = s
        return result


@dataclass(frozen=True)
class FailureClassMeta:
    """Static metadata for a single FailureClass value."""

    code: str
    label: str
    severity_default: Severity
    user_message: str
    operator_hint: str
    retryable: bool
    security_sensitive: bool


class FailureClass(str, Enum):
    """Typed failure classification used across all Control Plane health checks.

    Each member exposes its metadata via properties so callers never need
    the lookup dict directly.
    """

    NONE = "none"
    DNS_FAILURE = "dns_failure"
    TCP_FAILURE = "tcp_failure"
    TLS_FAILURE = "tls_failure"
    TIMEOUT = "timeout"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    UNREACHABLE = "unreachable"
    INVALID_RESPONSE = "invalid_response"
    CONFIGURATION_ERROR = "configuration_error"
    PERMISSION_ERROR = "permission_error"
    STORAGE_ERROR = "storage_error"
    DATABASE_ERROR = "database_error"
    DOCKER_ERROR = "docker_error"
    PLUGIN_ERROR = "plugin_error"
    UNKNOWN_ERROR = "unknown_error"

    @property
    def meta(self) -> FailureClassMeta:
        return _FAILURE_METADATA[self.value]

    @property
    def label(self) -> str:
        return self.meta.label

    @property
    def severity_default(self) -> Severity:
        return self.meta.severity_default

    @property
    def user_message(self) -> str:
        return self.meta.user_message

    @property
    def operator_hint(self) -> str:
        return self.meta.operator_hint

    @property
    def retryable(self) -> bool:
        return self.meta.retryable

    @property
    def security_sensitive(self) -> bool:
        return self.meta.security_sensitive


# Metadata table — keyed by string value to avoid forward-reference issues.
_FAILURE_METADATA: dict[str, FailureClassMeta] = {
    "none": FailureClassMeta(
        code="none",
        label="No Failure",
        severity_default=Severity.INFO,
        user_message="Service is operating normally.",
        operator_hint="No action required.",
        retryable=False,
        security_sensitive=False,
    ),
    "dns_failure": FailureClassMeta(
        code="dns_failure",
        label="DNS Resolution Failure",
        severity_default=Severity.ERROR,
        user_message="The service cannot be reached. The server name could not be found.",
        operator_hint=(
            "DNS resolution failed for the integration hostname. "
            "Verify the service URL is correct and that DNS resolves on this server. "
            "Run: nslookup <hostname>. Update the URL via 'wooprice configure set'."
        ),
        retryable=False,
        security_sensitive=False,
    ),
    "tcp_failure": FailureClassMeta(
        code="tcp_failure",
        label="TCP Connection Failure",
        severity_default=Severity.ERROR,
        user_message="The service could not be reached at the network level.",
        operator_hint=(
            "DNS resolved but the TCP connection failed. "
            "Check firewall rules, port configuration, and whether the remote service "
            "is accepting connections on the expected port."
        ),
        retryable=True,
        security_sensitive=False,
    ),
    "tls_failure": FailureClassMeta(
        code="tls_failure",
        label="TLS / Certificate Failure",
        severity_default=Severity.ERROR,
        user_message="The secure connection to the service could not be established.",
        operator_hint=(
            "TLS handshake failed or the server certificate is invalid or expired. "
            "Check certificate expiry, certificate chain validity, and hostname match. "
            "If using a self-signed certificate, verify trust configuration."
        ),
        retryable=False,
        security_sensitive=False,
    ),
    "timeout": FailureClassMeta(
        code="timeout",
        label="Connection Timeout",
        severity_default=Severity.WARNING,
        user_message="The service did not respond in time.",
        operator_hint=(
            "The connection or read timed out. The service may be overloaded, "
            "a firewall may be silently dropping packets, or the timeout setting "
            "may be too short. Check server load and network path, then retry."
        ),
        retryable=True,
        security_sensitive=False,
    ),
    "unauthorized": FailureClassMeta(
        code="unauthorized",
        label="Authentication Failure",
        severity_default=Severity.ERROR,
        user_message="Access was denied. The provided credentials were not accepted.",
        operator_hint=(
            "HTTP 401: the service rejected the credentials. "
            "Verify the username and password/API key in .env are correct "
            "and that the account is active and not locked."
        ),
        retryable=False,
        security_sensitive=True,
    ),
    "forbidden": FailureClassMeta(
        code="forbidden",
        label="Access Forbidden",
        severity_default=Severity.ERROR,
        user_message="Access was denied. The account does not have the required permissions.",
        operator_hint=(
            "HTTP 403: credentials are valid but the account lacks required permissions. "
            "Verify the account has admin or API access on the remote service."
        ),
        retryable=False,
        security_sensitive=True,
    ),
    "unreachable": FailureClassMeta(
        code="unreachable",
        label="Service Unreachable",
        severity_default=Severity.ERROR,
        user_message="The service is not responding.",
        operator_hint=(
            "Connection refused or no route to host. "
            "Verify the service is running, the correct port is configured, "
            "and no firewall is blocking the connection."
        ),
        retryable=True,
        security_sensitive=False,
    ),
    "invalid_response": FailureClassMeta(
        code="invalid_response",
        label="Invalid Response",
        severity_default=Severity.ERROR,
        user_message="The service returned an unexpected response.",
        operator_hint=(
            "The server responded but with an unexpected status code or body. "
            "The service may have been updated and the API path changed. "
            "Test the URL manually with curl or a browser."
        ),
        retryable=False,
        security_sensitive=False,
    ),
    "configuration_error": FailureClassMeta(
        code="configuration_error",
        label="Configuration Error",
        severity_default=Severity.CRITICAL,
        user_message="The application configuration is invalid or incomplete.",
        operator_hint=(
            "A required configuration value is missing, malformed, or invalid. "
            "Run 'wooprice configure verify' to identify the problem, "
            "then correct the value in .env or via 'wooprice configure set'."
        ),
        retryable=False,
        security_sensitive=False,
    ),
    "permission_error": FailureClassMeta(
        code="permission_error",
        label="File System Permission Error",
        severity_default=Severity.ERROR,
        user_message="The application cannot access a required file or directory.",
        operator_hint=(
            "A required path is not readable or writable by the application user. "
            "Check file system permissions for the application user on BETA_STORAGE_PATH."
        ),
        retryable=False,
        security_sensitive=False,
    ),
    "storage_error": FailureClassMeta(
        code="storage_error",
        label="Storage Error",
        severity_default=Severity.CRITICAL,
        user_message="The application cannot access its storage.",
        operator_hint=(
            "BETA_STORAGE_PATH is missing, not mounted, or the disk is full. "
            "Check mount points and available disk space. "
            "Run: df -h && ls -la $BETA_STORAGE_PATH"
        ),
        retryable=False,
        security_sensitive=False,
    ),
    "database_error": FailureClassMeta(
        code="database_error",
        label="Database Error",
        severity_default=Severity.CRITICAL,
        user_message="The database is not available.",
        operator_hint=(
            "The PostgreSQL database is not reachable or authentication failed. "
            "Check that the database container is running and BETA_DATABASE_URL is correct. "
            "Run: docker compose ps db"
        ),
        retryable=True,
        security_sensitive=False,
    ),
    "docker_error": FailureClassMeta(
        code="docker_error",
        label="Docker Runtime Error",
        severity_default=Severity.ERROR,
        user_message="A container or the Docker runtime is not operating normally.",
        operator_hint=(
            "Check container status with 'docker compose ps'. "
            "Inspect logs with 'docker compose logs <service>'."
        ),
        retryable=True,
        security_sensitive=False,
    ),
    "plugin_error": FailureClassMeta(
        code="plugin_error",
        label="Plugin Error",
        severity_default=Severity.WARNING,
        user_message="A plugin is not operating normally.",
        operator_hint=(
            "A plugin has failed or been quarantined. "
            "Check the plugin manager for details and consider disabling the affected plugin."
        ),
        retryable=False,
        security_sensitive=False,
    ),
    "unknown_error": FailureClassMeta(
        code="unknown_error",
        label="Unknown Error",
        severity_default=Severity.ERROR,
        user_message="An unexpected error occurred.",
        operator_hint=(
            "An unclassified error occurred. "
            "Check the application logs for details. "
            "If the error persists, run 'wooprice diagnostics run'."
        ),
        retryable=False,
        security_sensitive=False,
    ),
}
