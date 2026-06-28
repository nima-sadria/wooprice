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


# ---------------------------------------------------------------------------
# Real production adapter (CP1.3)
# ---------------------------------------------------------------------------


class RealNetworkAdapter(NetworkAdapter):
    """Production adapter that issues actual OS-level and HTTP calls.

    SYNCHRONOUS BLOCKING IMPLEMENTATION — all methods block the calling thread.
    Safe for CLI use.  Must NOT be called from async FastAPI route handlers
    until replaced by an async adapter in B6 (AsyncNetworkAdapter / asyncpg).

    Uses stdlib (socket, ssl) for transport checks and httpx for HTTP/auth.
    Credentials passed to http_request/check_auth are never logged.

    B6 replacement note: implement AsyncNetworkAdapter(NetworkAdapter) with
    async def counterparts; swap at the DI boundary in ConnectionManager.
    """

    def resolve_dns(self, hostname: str) -> list[str]:
        import socket
        try:
            info = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
            return list({addr[4][0] for addr in info})
        except socket.gaierror as exc:
            raise DNSResolutionError(str(exc)) from exc

    def tcp_connect(self, host: str, port: int, timeout: float) -> float:
        import socket
        import time
        t0 = time.monotonic()
        try:
            with socket.create_connection((host, port), timeout=timeout):
                pass
            return (time.monotonic() - t0) * 1000.0
        except socket.timeout as exc:
            raise ConnectionTimeoutError(f"TCP connect timeout: {host}:{port}") from exc
        except ConnectionRefusedError as exc:
            raise TCPConnectionError(f"Connection refused: {host}:{port}") from exc
        except OSError as exc:
            raise ConnectionUnreachableError(str(exc)) from exc

    def tls_handshake(self, host: str, port: int, timeout: float) -> dict:
        import datetime
        import socket
        import ssl
        import time
        t0 = time.monotonic()
        ctx = ssl.create_default_context()
        try:
            raw = socket.create_connection((host, port), timeout=timeout)
            with ctx.wrap_socket(raw, server_hostname=host) as conn:
                cert = conn.getpeercert()
            latency_ms = (time.monotonic() - t0) * 1000.0
            expiry_str: str = cert.get("notAfter", "") if cert else ""
            expiry_dt = None
            if expiry_str:
                expiry_dt = datetime.datetime.strptime(
                    expiry_str, "%b %d %H:%M:%S %Y %Z"
                ).replace(tzinfo=datetime.timezone.utc)
            days = (
                (expiry_dt - datetime.datetime.now(tz=datetime.timezone.utc)).days
                if expiry_dt
                else -1
            )
            subject = (
                dict(x[0] for x in cert.get("subject", []))
                if cert
                else {}
            )
            return {
                "cert_subject": subject.get("commonName", ""),
                "cert_expiry": expiry_dt.date().isoformat() if expiry_dt else "",
                "days_until_expiry": days,
                "chain_valid": True,
                "latency_ms": latency_ms,
            }
        except ssl.SSLError as exc:
            raise TLSHandshakeError(str(exc)) from exc
        except socket.timeout as exc:
            raise ConnectionTimeoutError(f"TLS timeout: {host}:{port}") from exc
        except OSError as exc:
            raise ConnectionUnreachableError(str(exc)) from exc

    def http_request(
        self,
        method: str,
        url: str,
        timeout: float,
        headers: dict[str, str],
        auth: Optional[tuple[str, str]],
    ) -> tuple[int, bytes]:
        import httpx
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                r = client.request(method, url, headers=headers, auth=auth)
                return (r.status_code, r.content)
        except httpx.TimeoutException as exc:
            raise ConnectionTimeoutError(str(exc)) from exc
        except httpx.ConnectError as exc:
            msg = str(exc)
            if "getaddrinfo" in msg.lower() or "nodename" in msg.lower() or "name or service" in msg.lower():
                raise DNSResolutionError(msg) from exc
            raise TCPConnectionError(msg) from exc
        except httpx.HTTPError as exc:
            raise InvalidResponseError(str(exc)) from exc

    def check_auth(
        self,
        url: str,
        username: str,
        password: str,
        timeout: float,
    ) -> tuple[bool, int]:
        import httpx
        try:
            with httpx.Client(timeout=timeout) as client:
                r = client.get(url, auth=(username, password))
                if r.status_code == 401:
                    raise AuthenticationError("HTTP 401: credentials rejected")
                if r.status_code == 403:
                    raise AccessForbiddenError("HTTP 403: access denied")
                return (r.status_code < 400, r.status_code)
        except httpx.TimeoutException as exc:
            raise ConnectionTimeoutError(str(exc)) from exc
        except httpx.ConnectError as exc:
            raise TCPConnectionError(str(exc)) from exc

    def check_path(self, path: str) -> dict:
        import os
        import shutil
        from pathlib import Path as _Path
        p = _Path(path)
        if not p.exists():
            raise StorageAdapterError(f"Path does not exist: {path}")
        try:
            readable = os.access(path, os.R_OK)
            writable = os.access(path, os.W_OK)
            usage = shutil.disk_usage(path)
            return {
                "exists": True,
                "readable": readable,
                "writable": writable,
                "free_gb": usage.free / (1024 ** 3),
                "total_gb": usage.total / (1024 ** 3),
            }
        except OSError as exc:
            raise StorageAdapterError(str(exc)) from exc

    def check_database(self, url: str, timeout: float) -> dict:
        # Synchronous psycopg2 — blocks the event loop.  Replace with asyncpg in B6.
        import time
        t0 = time.monotonic()
        try:
            import psycopg2
            import psycopg2.Error as _PGError
        except ImportError as exc:
            raise DatabaseAdapterError("psycopg2 not installed") from exc
        try:
            conn = psycopg2.connect(url, connect_timeout=max(1, int(timeout)))
            cur = conn.cursor()
            cur.execute("SELECT 1")
            latency_ms = (time.monotonic() - t0) * 1000.0
            conn.close()
            return {"connected": True, "latency_ms": latency_ms, "pending_migrations": False}
        except _PGError as exc:
            raise DatabaseAdapterError(str(exc)) from exc
        except OSError as exc:
            raise DatabaseAdapterError(str(exc)) from exc

    def check_docker(self) -> dict:
        # Linux-only assumption: /var/run/docker.sock.
        # B6 replacement note: make socket_path configurable or use docker-py SDK
        # so this works on macOS (~/Library/Containers/…) and Windows (named pipe).
        import os
        socket_path = "/var/run/docker.sock"
        if not os.path.exists(socket_path):
            raise DockerAdapterError(f"Docker socket not found at {socket_path}")
        return {"available": True, "socket_path": socket_path}
