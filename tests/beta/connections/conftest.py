"""Shared fixtures for connection manager tests.

FakeNetworkAdapter provides controlled, in-memory responses with NO real
network calls.  Tests configure it via its public attributes before calling
the system under test.
"""

from __future__ import annotations

from typing import Optional
import pytest

from app.beta.connections.adapters import (
    NetworkAdapter,
    DNSResolutionError,
    TCPConnectionError,
    TLSHandshakeError,
    ConnectionTimeoutError,
    ConnectionUnreachableError,
    AuthenticationError,
    AccessForbiddenError,
    InvalidResponseError,
    StorageAdapterError,
    DatabaseAdapterError,
    DockerAdapterError,
)
from app.beta.connections.models import (
    ConnectionDefinition,
    ConnectionType,
)


class FakeNetworkAdapter(NetworkAdapter):
    """Controllable fake adapter for unit tests — no real network calls."""

    def __init__(self) -> None:
        # DNS: hostname → list[str] IPs, or Exception to raise
        self.dns_responses: dict[str, list[str] | Exception] = {}
        self.dns_default: list[str] | Exception = ["127.0.0.1"]

        # TCP: (host, port) → float latency_ms, or Exception
        self.tcp_responses: dict[tuple[str, int], float | Exception] = {}
        self.tcp_default: float | Exception = 5.0

        # TLS: (host, port) → dict cert_info, or Exception
        self.tls_responses: dict[tuple[str, int], dict | Exception] = {}
        self.tls_default: dict | Exception = {
            "cert_subject": "example.com",
            "cert_expiry": "2030-01-01",
            "days_until_expiry": 999,
            "chain_valid": True,
            "latency_ms": 3.0,
        }

        # HTTP: url → (status_code, body), or Exception
        self.http_responses: dict[str, tuple[int, bytes] | Exception] = {}
        self.http_default: tuple[int, bytes] | Exception = (200, b"ok")

        # Auth: url → (bool authenticated, int status_code), or Exception
        self.auth_responses: dict[str, tuple[bool, int] | Exception] = {}
        self.auth_default: tuple[bool, int] | Exception = (True, 200)

        # Path: path → dict, or Exception
        self.path_responses: dict[str, dict | Exception] = {}
        self.path_default: dict | Exception = {
            "exists": True,
            "readable": True,
            "writable": True,
            "free_gb": 50.0,
            "total_gb": 100.0,
        }

        # DB: url → dict, or Exception
        self.db_responses: dict[str, dict | Exception] = {}
        self.db_default: dict | Exception = {
            "connected": True,
            "latency_ms": 3.0,
            "pending_migrations": False,
        }

        # Docker: dict or Exception
        self.docker_response: dict | Exception = {
            "available": True,
            "socket_path": "/var/run/docker.sock",
        }

    def _resolve(self, store: dict, key, default):
        val = store.get(key, default)
        if isinstance(val, Exception):
            raise val
        return val

    def resolve_dns(self, hostname: str) -> list[str]:
        return self._resolve(self.dns_responses, hostname, self.dns_default)

    def tcp_connect(self, host: str, port: int, timeout: float) -> float:
        return self._resolve(self.tcp_responses, (host, port), self.tcp_default)

    def tls_handshake(self, host: str, port: int, timeout: float) -> dict:
        return self._resolve(self.tls_responses, (host, port), self.tls_default)

    def http_request(
        self,
        method: str,
        url: str,
        timeout: float,
        headers: dict,
        auth,
    ) -> tuple[int, bytes]:
        return self._resolve(self.http_responses, url, self.http_default)

    def check_auth(
        self,
        url: str,
        username: str,
        password: str,
        timeout: float,
    ) -> tuple[bool, int]:
        return self._resolve(self.auth_responses, url, self.auth_default)

    def check_path(self, path: str) -> dict:
        return self._resolve(self.path_responses, path, self.path_default)

    def check_database(self, url: str, timeout: float) -> dict:
        return self._resolve(self.db_responses, url, self.db_default)

    def check_docker(self) -> dict:
        val = self.docker_response
        if isinstance(val, Exception):
            raise val
        return val


@pytest.fixture
def fake_adapter() -> FakeNetworkAdapter:
    return FakeNetworkAdapter()


@pytest.fixture
def nextcloud_def() -> ConnectionDefinition:
    return ConnectionDefinition(
        name="nextcloud",
        connection_type=ConnectionType.NEXTCLOUD,
        enabled=True,
        required=True,
        endpoint="https://nextcloud.example.com",
        timeout_seconds=10.0,
        retry_attempts=2,
        retry_backoff_seconds=0.0,  # no actual delay in tests
    )


@pytest.fixture
def woo_def() -> ConnectionDefinition:
    return ConnectionDefinition(
        name="woocommerce",
        connection_type=ConnectionType.WOOCOMMERCE,
        enabled=True,
        required=True,
        endpoint="https://shop.example.com",
        timeout_seconds=10.0,
        retry_attempts=1,
        retry_backoff_seconds=0.0,
    )


@pytest.fixture
def disabled_def() -> ConnectionDefinition:
    return ConnectionDefinition(
        name="smtp",
        connection_type=ConnectionType.SMTP,
        enabled=False,
        required=False,
        endpoint="smtp://mail.example.com",
        timeout_seconds=5.0,
    )
