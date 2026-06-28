"""CP1.2 — Network adapter interface and custom exception hierarchy.

All outbound network activity goes through NetworkAdapter so that unit tests
can inject a FakeNetworkAdapter without real network calls.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


# ---------------------------------------------------------------------------
# Custom exception hierarchy
# ---------------------------------------------------------------------------


class NetworkAdapterError(Exception):
    """Base for all adapter-raised errors."""


class DNSResolutionError(NetworkAdapterError):
    """DNS lookup failed (NXDOMAIN, server unreachable, timeout)."""


class TCPConnectionError(NetworkAdapterError):
    """TCP connection refused or no route to host."""


class TLSHandshakeError(NetworkAdapterError):
    """TLS handshake failed or certificate is invalid."""


class ConnectionTimeoutError(NetworkAdapterError):
    """Operation exceeded the configured timeout."""


class ConnectionUnreachableError(NetworkAdapterError):
    """Host is not reachable at the network layer."""


class AuthenticationError(NetworkAdapterError):
    """Credentials were presented and rejected (HTTP 401 equivalent)."""


class AccessForbiddenError(NetworkAdapterError):
    """Access denied — account valid but permission denied (HTTP 403)."""


class InvalidResponseError(NetworkAdapterError):
    """Unexpected or malformed HTTP response."""


class StorageAdapterError(NetworkAdapterError):
    """Storage path access failed."""


class DatabaseAdapterError(NetworkAdapterError):
    """Database connection or query failed."""


class DockerAdapterError(NetworkAdapterError):
    """Docker socket unavailable or daemon not running."""


# ---------------------------------------------------------------------------
# Abstract adapter interface
# ---------------------------------------------------------------------------


class NetworkAdapter(ABC):
    """Abstract interface for all outbound network calls.

    Implementations supply the real OS/HTTP layer.  Tests supply a fake that
    returns controlled results without touching the network.
    """

    @abstractmethod
    def resolve_dns(self, hostname: str) -> list[str]:
        """Resolve hostname to a list of IP address strings.

        Raises DNSResolutionError on failure.
        """

    @abstractmethod
    def tcp_connect(self, host: str, port: int, timeout: float) -> float:
        """Attempt a TCP connection and return round-trip latency in milliseconds.

        Raises TCPConnectionError, ConnectionTimeoutError, or
        ConnectionUnreachableError on failure.
        """

    @abstractmethod
    def tls_handshake(self, host: str, port: int, timeout: float) -> dict:
        """Perform a TLS handshake and return certificate metadata dict.

        Returned dict keys: cert_subject, cert_expiry (ISO date str),
        days_until_expiry (int), chain_valid (bool), latency_ms (float).

        Raises TLSHandshakeError, ConnectionTimeoutError on failure.
        """

    @abstractmethod
    def http_request(
        self,
        method: str,
        url: str,
        timeout: float,
        headers: dict[str, str],
        auth: Optional[tuple[str, str]],
    ) -> tuple[int, bytes]:
        """Send an HTTP request and return (status_code, body_bytes).

        Raises ConnectionTimeoutError, DNSResolutionError, TCPConnectionError,
        TLSHandshakeError, or InvalidResponseError on failure.

        auth is (username, password) for HTTP Basic Auth, or None.
        Credentials must never be logged or included in exceptions.
        """

    @abstractmethod
    def check_auth(
        self,
        url: str,
        username: str,
        password: str,
        timeout: float,
    ) -> tuple[bool, int]:
        """Perform an authenticated probe and return (authenticated, status_code).

        Credentials must never be logged or included in exceptions.
        Raises AuthenticationError (401), AccessForbiddenError (403).
        """

    @abstractmethod
    def check_path(self, path: str) -> dict:
        """Check a filesystem path and return metadata dict.

        Returned dict keys: exists (bool), readable (bool), writable (bool),
        free_gb (float), total_gb (float).

        Raises StorageAdapterError on unexpected OS error.
        """

    @abstractmethod
    def check_database(self, url: str, timeout: float) -> dict:
        """Check database connectivity and return metadata dict.

        Returned dict keys: connected (bool), latency_ms (float),
        pending_migrations (bool).

        Raises DatabaseAdapterError on failure.
        """

    @abstractmethod
    def check_docker(self) -> dict:
        """Check Docker daemon availability and return metadata dict.

        Returned dict keys: available (bool), socket_path (str).

        Raises DockerAdapterError on failure.
        """
