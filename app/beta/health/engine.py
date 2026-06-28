"""CP1.2 — Health Engine.

Orchestrates health checks and delegates to individual check implementations.
Framework-independent — no FastAPI, no Typer, no CLI imports.
"""

from __future__ import annotations

from typing import Optional

from ..connections.adapters import NetworkAdapter
from .aggregation import SystemHealthSummary, aggregate_results
from .checks import (
    AuthCheck,
    ConfigCheck,
    DatabaseCheck,
    DNSCheck,
    DockerCheck,
    HTTPCheck,
    IntegrationCheck,
    StorageCheck,
    TCPCheck,
    TLSCheck,
)
from .models import CheckCategory, HealthCheckResult


class HealthEngine:
    """Orchestrator for health checks.

    Accepts an injected NetworkAdapter so that all checks are testable
    without real network calls.

    Usage:
        engine = HealthEngine(adapter=fake_adapter)
        result = engine.run(DNSCheck("dns:nc", "nextcloud.example.com", adapter))
        results = engine.run_integration_chain("nextcloud", "https://nc.example.com")
        summary = engine.summarize(results)
    """

    def __init__(
        self,
        adapter: NetworkAdapter,
        connection_manager: Optional[object] = None,
    ) -> None:
        self._adapter = adapter
        self._connection_manager = connection_manager  # reserved for B13 integration

    # ------------------------------------------------------------------
    # Single check execution
    # ------------------------------------------------------------------

    def run(self, check: object) -> HealthCheckResult:
        """Execute a single check object that has a .run() method."""
        return check.run()  # type: ignore[union-attr]

    def run_many(self, checks: list) -> list[HealthCheckResult]:
        """Execute multiple checks and return all results."""
        return [self.run(c) for c in checks]

    # ------------------------------------------------------------------
    # Integration chain
    # ------------------------------------------------------------------

    def run_integration_chain(
        self,
        service_name: str,
        url: str,
        timeout: float = 10.0,
        expected_http_status: int = 200,
        auth_url: Optional[str] = None,
        auth_username: Optional[str] = None,
        auth_password: Optional[str] = None,
    ) -> list[HealthCheckResult]:
        """Run DNS → TCP → TLS → HTTP → Auth chain for an integration service.

        Returns the individual step results (not a summary).
        """
        check = IntegrationCheck(
            check_name=f"integration:{service_name}",
            service_label=service_name,
            url=url,
            timeout=timeout,
            adapter=self._adapter,
            expected_http_status=expected_http_status,
            auth_url=auth_url,
            auth_username=auth_username,
            auth_password=auth_password,
        )
        return check.run_chain()

    # ------------------------------------------------------------------
    # Local checks
    # ------------------------------------------------------------------

    def run_dns_check(self, hostname: str, name: str = "dns") -> HealthCheckResult:
        return DNSCheck(name, hostname, self._adapter).run()

    def run_tcp_check(
        self,
        host: str,
        port: int,
        timeout: float = 10.0,
        name: str = "tcp",
        prerequisite: Optional[HealthCheckResult] = None,
    ) -> HealthCheckResult:
        return TCPCheck(name, host, port, timeout, self._adapter, prerequisite).run()

    def run_tls_check(
        self,
        host: str,
        port: int = 443,
        timeout: float = 10.0,
        name: str = "tls",
        prerequisite: Optional[HealthCheckResult] = None,
    ) -> HealthCheckResult:
        return TLSCheck(name, host, port, timeout, self._adapter, prerequisite).run()

    def run_storage_check(
        self, path: str, name: str = "storage"
    ) -> HealthCheckResult:
        return StorageCheck(name, path, self._adapter).run()

    def run_database_check(
        self, db_url: str, timeout: float = 5.0, name: str = "database"
    ) -> HealthCheckResult:
        return DatabaseCheck(name, db_url, timeout, self._adapter).run()

    def run_docker_check(self, name: str = "docker") -> HealthCheckResult:
        return DockerCheck(name, self._adapter).run()

    def run_config_check(
        self,
        required_keys: list[str],
        config_dict: dict,
        optional_keys: Optional[list[str]] = None,
        name: str = "config",
    ) -> HealthCheckResult:
        return ConfigCheck(name, required_keys, optional_keys or [], config_dict).run()

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    def summarize(self, results: list[HealthCheckResult]) -> SystemHealthSummary:
        return aggregate_results(results)
