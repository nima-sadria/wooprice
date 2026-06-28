"""CP1.2 — Health check implementations (10 types).

All checks are adapter-based: no real network calls at construction time.
Tests inject FakeNetworkAdapter; production injects a real adapter.

Check types: DNS, TCP, TLS, HTTP, AUTH, CONFIG, STORAGE, DATABASE, DOCKER, INTEGRATION
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from app.beta.control_plane.failure import FailureClass

from ..connections.adapters import (
    NetworkAdapter,
    AccessForbiddenError,
    AuthenticationError,
    ConnectionTimeoutError,
    ConnectionUnreachableError,
    DatabaseAdapterError,
    DNSResolutionError,
    DockerAdapterError,
    InvalidResponseError,
    StorageAdapterError,
    TCPConnectionError,
    TLSHandshakeError,
)
from ..connections.classifier import classify_exception, classify_http_response
from .models import CheckCategory, HealthCheckResult, HealthStatus


# ---------------------------------------------------------------------------
# 1. DNS Check
# ---------------------------------------------------------------------------


@dataclass
class DNSCheck:
    check_name: str
    hostname: str
    adapter: NetworkAdapter

    def run(self) -> HealthCheckResult:
        start = time.monotonic()
        try:
            ips = self.adapter.resolve_dns(self.hostname)
            ms = (time.monotonic() - start) * 1000
            return HealthCheckResult.ok(
                self.check_name,
                CheckCategory.DNS,
                self.hostname,
                message=f"{self.hostname} → {', '.join(ips)}",
                duration_ms=ms,
                details={"hostname": self.hostname, "resolved_ips": ips},
            )
        except DNSResolutionError as exc:
            ms = (time.monotonic() - start) * 1000
            return HealthCheckResult.fail(
                self.check_name,
                CheckCategory.DNS,
                self.hostname,
                FailureClass.DNS_FAILURE,
                message=f"Could not resolve {self.hostname}",
                duration_ms=ms,
                details={"hostname": self.hostname, "error": str(exc)},
            )
        except Exception as exc:
            ms = (time.monotonic() - start) * 1000
            fc = classify_exception(exc)
            return HealthCheckResult.fail(
                self.check_name,
                CheckCategory.DNS,
                self.hostname,
                fc,
                message=f"DNS check error: {exc}",
                duration_ms=ms,
            )


# ---------------------------------------------------------------------------
# 2. TCP Check
# ---------------------------------------------------------------------------


@dataclass
class TCPCheck:
    check_name: str
    host: str
    port: int
    timeout: float
    adapter: NetworkAdapter
    prerequisite_result: Optional[HealthCheckResult] = None

    def run(self) -> HealthCheckResult:
        if self.prerequisite_result is not None and self.prerequisite_result.is_blocking():
            return HealthCheckResult.skip(
                self.check_name,
                CheckCategory.TCP,
                f"{self.host}:{self.port}",
                skipped_because=self.prerequisite_result.check_name,
            )
        target = f"{self.host}:{self.port}"
        start = time.monotonic()
        try:
            latency_ms = self.adapter.tcp_connect(self.host, self.port, self.timeout)
            return HealthCheckResult.ok(
                self.check_name,
                CheckCategory.TCP,
                target,
                message=f"TCP connect to {target} ok ({latency_ms:.0f}ms)",
                duration_ms=latency_ms,
                details={"host": self.host, "port": self.port, "latency_ms": latency_ms},
            )
        except ConnectionTimeoutError:
            ms = (time.monotonic() - start) * 1000
            return HealthCheckResult.fail(
                self.check_name, CheckCategory.TCP, target,
                FailureClass.TIMEOUT,
                message=f"TCP connect timeout after {self.timeout}s: {target}",
                duration_ms=ms,
            )
        except (TCPConnectionError, ConnectionUnreachableError) as exc:
            ms = (time.monotonic() - start) * 1000
            return HealthCheckResult.fail(
                self.check_name, CheckCategory.TCP, target,
                FailureClass.UNREACHABLE,
                message=f"Connection refused: {target}",
                duration_ms=ms,
                details={"error": str(exc)},
            )
        except Exception as exc:
            ms = (time.monotonic() - start) * 1000
            fc = classify_exception(exc)
            return HealthCheckResult.fail(
                self.check_name, CheckCategory.TCP, target, fc,
                message=f"TCP check error: {exc}",
                duration_ms=ms,
            )


# ---------------------------------------------------------------------------
# 3. TLS Check
# ---------------------------------------------------------------------------

_TLS_WARN_DAYS = 30


@dataclass
class TLSCheck:
    check_name: str
    host: str
    port: int
    timeout: float
    adapter: NetworkAdapter
    prerequisite_result: Optional[HealthCheckResult] = None

    def run(self) -> HealthCheckResult:
        if self.prerequisite_result is not None and self.prerequisite_result.is_blocking():
            return HealthCheckResult.skip(
                self.check_name,
                CheckCategory.TLS,
                f"{self.host}:{self.port}",
                skipped_because=self.prerequisite_result.check_name,
            )
        target = f"{self.host}:{self.port}"
        start = time.monotonic()
        try:
            cert_info = self.adapter.tls_handshake(self.host, self.port, self.timeout)
            ms = cert_info.get("latency_ms") or ((time.monotonic() - start) * 1000)
            days = cert_info.get("days_until_expiry", 999)
            expiry = cert_info.get("cert_expiry", "")
            details = {
                "host": self.host,
                "port": self.port,
                "cert_subject": cert_info.get("cert_subject", ""),
                "cert_expiry": expiry,
                "days_until_expiry": days,
                "chain_valid": cert_info.get("chain_valid", True),
            }
            if days < _TLS_WARN_DAYS:
                return HealthCheckResult.warn(
                    self.check_name, CheckCategory.TLS, target,
                    message=f"TLS ok · cert expires in {days} days ({expiry})",
                    repair_hint="Renew the TLS certificate before it expires.",
                    duration_ms=ms,
                    details=details,
                )
            return HealthCheckResult.ok(
                self.check_name, CheckCategory.TLS, target,
                message=f"TLS ok · cert expires {expiry} ({days} days)",
                duration_ms=ms,
                details=details,
            )
        except TLSHandshakeError as exc:
            ms = (time.monotonic() - start) * 1000
            return HealthCheckResult.fail(
                self.check_name, CheckCategory.TLS, target,
                FailureClass.TLS_FAILURE,
                message=f"TLS handshake failed: {exc}",
                duration_ms=ms,
            )
        except Exception as exc:
            ms = (time.monotonic() - start) * 1000
            fc = classify_exception(exc)
            return HealthCheckResult.fail(
                self.check_name, CheckCategory.TLS, target, fc,
                message=f"TLS check error: {exc}",
                duration_ms=ms,
            )


# ---------------------------------------------------------------------------
# 4. HTTP Check
# ---------------------------------------------------------------------------


@dataclass
class HTTPCheck:
    check_name: str
    url: str
    method: str
    expected_status: int
    timeout: float
    adapter: NetworkAdapter
    headers: dict[str, str] = field(default_factory=dict)
    auth: Optional[tuple[str, str]] = None
    prerequisite_result: Optional[HealthCheckResult] = None

    def run(self) -> HealthCheckResult:
        if self.prerequisite_result is not None and self.prerequisite_result.is_blocking():
            return HealthCheckResult.skip(
                self.check_name,
                CheckCategory.HTTP,
                self.url,
                skipped_because=self.prerequisite_result.check_name,
            )
        start = time.monotonic()
        try:
            status_code, _ = self.adapter.http_request(
                self.method, self.url, self.timeout, self.headers, self.auth
            )
            ms = (time.monotonic() - start) * 1000
            details = {
                "url": self.url,
                "method": self.method,
                "status_code": status_code,
                "expected_status": self.expected_status,
                "response_time_ms": ms,
            }
            if status_code == self.expected_status:
                return HealthCheckResult.ok(
                    self.check_name, CheckCategory.HTTP, self.url,
                    message=f"{self.method} {self.url} → {status_code} ({ms:.0f}ms)",
                    duration_ms=ms,
                    details=details,
                )
            fc = classify_http_response(status_code)
            return HealthCheckResult.fail(
                self.check_name, CheckCategory.HTTP, self.url, fc,
                message=f"{self.method} {self.url} → {status_code} (expected {self.expected_status})",
                duration_ms=ms,
                details=details,
            )
        except ConnectionTimeoutError:
            ms = (time.monotonic() - start) * 1000
            return HealthCheckResult.fail(
                self.check_name, CheckCategory.HTTP, self.url,
                FailureClass.TIMEOUT,
                message=f"HTTP request timeout after {self.timeout}s",
                duration_ms=ms,
            )
        except Exception as exc:
            ms = (time.monotonic() - start) * 1000
            fc = classify_exception(exc)
            return HealthCheckResult.fail(
                self.check_name, CheckCategory.HTTP, self.url, fc,
                message=f"HTTP check error: {exc}",
                duration_ms=ms,
            )


# ---------------------------------------------------------------------------
# 5. Auth Check
# ---------------------------------------------------------------------------


@dataclass
class AuthCheck:
    check_name: str
    url: str
    username: str
    password: str  # handled securely; never logged; B7 will inject from SecretManager
    timeout: float
    adapter: NetworkAdapter
    service_label: str = ""
    prerequisite_result: Optional[HealthCheckResult] = None

    def run(self) -> HealthCheckResult:
        if self.prerequisite_result is not None and self.prerequisite_result.is_blocking():
            return HealthCheckResult.skip(
                self.check_name,
                CheckCategory.AUTH,
                self.url,
                skipped_because=self.prerequisite_result.check_name,
            )
        start = time.monotonic()
        try:
            authenticated, status_code = self.adapter.check_auth(
                self.url, self.username, self.password, self.timeout
            )
            ms = (time.monotonic() - start) * 1000
            # detail must never contain credentials
            label = self.service_label or self.url
            details = {
                "service": label,
                "status_code": status_code,
            }
            if authenticated:
                return HealthCheckResult.ok(
                    self.check_name, CheckCategory.AUTH, self.url,
                    message=f"Authentication ok ({label})",
                    duration_ms=ms,
                    details=details,
                )
            fc = classify_http_response(status_code)
            return HealthCheckResult.fail(
                self.check_name, CheckCategory.AUTH, self.url, fc,
                message=f"HTTP {status_code}: credentials rejected ({label})",
                duration_ms=ms,
                details=details,
            )
        except AuthenticationError:
            ms = (time.monotonic() - start) * 1000
            return HealthCheckResult.fail(
                self.check_name, CheckCategory.AUTH, self.url,
                FailureClass.UNAUTHORIZED,
                message="Credentials rejected.",
                duration_ms=ms,
            )
        except AccessForbiddenError:
            ms = (time.monotonic() - start) * 1000
            return HealthCheckResult.fail(
                self.check_name, CheckCategory.AUTH, self.url,
                FailureClass.FORBIDDEN,
                message="Access denied — account exists but permission denied.",
                duration_ms=ms,
            )
        except Exception as exc:
            ms = (time.monotonic() - start) * 1000
            # Auth check must only return UNAUTHORIZED or FORBIDDEN — never DNS/TLS/timeout.
            # Any other exception maps to INVALID_RESPONSE so the caller knows the
            # auth endpoint itself misbehaved, not the credentials.
            return HealthCheckResult.fail(
                self.check_name, CheckCategory.AUTH, self.url,
                FailureClass.INVALID_RESPONSE,
                message=f"Auth endpoint returned unexpected response: {exc}",
                duration_ms=ms,
            )


# ---------------------------------------------------------------------------
# 6. Config Check
# ---------------------------------------------------------------------------


@dataclass
class ConfigCheck:
    check_name: str
    required_keys: list[str]
    optional_keys: list[str]
    config_dict: dict[str, Any]

    def run(self) -> HealthCheckResult:
        missing_required = [k for k in self.required_keys if not self.config_dict.get(k)]
        missing_optional = [k for k in self.optional_keys if not self.config_dict.get(k)]
        details: dict[str, Any] = {
            "required_keys": self.required_keys,
            "optional_keys": self.optional_keys,
            "missing_required": missing_required,
            "missing_optional": missing_optional,
        }
        if missing_required:
            keys_str = ", ".join(missing_required)
            return HealthCheckResult.fail(
                self.check_name, CheckCategory.CONFIG, "configuration",
                FailureClass.CONFIGURATION_ERROR,
                message=f"Required configuration missing: {keys_str}",
                repair_hint=f"Set the missing keys: {keys_str}",
                details=details,
            )
        if missing_optional:
            keys_str = ", ".join(missing_optional)
            return HealthCheckResult.warn(
                self.check_name, CheckCategory.CONFIG, "configuration",
                message=f"Optional configuration missing: {keys_str}",
                repair_hint=f"Consider setting: {keys_str}",
                details=details,
            )
        return HealthCheckResult.ok(
            self.check_name, CheckCategory.CONFIG, "configuration",
            message="Configuration loaded and valid.",
            details=details,
        )


# ---------------------------------------------------------------------------
# 7. Storage Check
# ---------------------------------------------------------------------------

_WARN_FREE_GB = 1.0
_CRITICAL_FREE_GB = 0.1


@dataclass
class StorageCheck:
    check_name: str
    path: str
    adapter: NetworkAdapter

    def run(self) -> HealthCheckResult:
        start = time.monotonic()
        try:
            info = self.adapter.check_path(self.path)
            ms = (time.monotonic() - start) * 1000
            exists = info.get("exists", False)
            readable = info.get("readable", False)
            writable = info.get("writable", False)
            free_gb: float = info.get("free_gb", 0.0)
            total_gb: float = info.get("total_gb", 0.0)
            details = {
                "path": self.path,
                "exists": exists,
                "readable": readable,
                "writable": writable,
                "free_gb": free_gb,
                "total_gb": total_gb,
            }

            if not exists:
                return HealthCheckResult.fail(
                    self.check_name, CheckCategory.STORAGE, self.path,
                    FailureClass.STORAGE_ERROR,
                    message=f"{self.path}: path does not exist",
                    repair_hint=f"Create the directory: mkdir -p {self.path}",
                    details=details,
                )
            if not readable:
                return HealthCheckResult.fail(
                    self.check_name, CheckCategory.STORAGE, self.path,
                    FailureClass.PERMISSION_ERROR,
                    message=f"{self.path}: not readable (permission denied)",
                    repair_hint="Check directory permissions.",
                    details=details,
                )
            if free_gb < _CRITICAL_FREE_GB:
                return HealthCheckResult.fail(
                    self.check_name, CheckCategory.STORAGE, self.path,
                    FailureClass.STORAGE_ERROR,
                    message=f"{self.path}: critically low disk space ({free_gb:.1f}GB free)",
                    repair_hint="Free disk space immediately.",
                    details=details,
                )
            if not writable or free_gb < _WARN_FREE_GB:
                reason = "not writable" if not writable else f"low disk space ({free_gb:.1f}GB free)"
                return HealthCheckResult.warn(
                    self.check_name, CheckCategory.STORAGE, self.path,
                    message=f"{self.path}: {reason}",
                    repair_hint="Check permissions and disk space.",
                    duration_ms=ms,
                    details=details,
                )
            return HealthCheckResult.ok(
                self.check_name, CheckCategory.STORAGE, self.path,
                message=f"{self.path}: readable, writable, {free_gb:.1f}GB free",
                duration_ms=ms,
                details=details,
            )
        except StorageAdapterError as exc:
            ms = (time.monotonic() - start) * 1000
            return HealthCheckResult.fail(
                self.check_name, CheckCategory.STORAGE, self.path,
                FailureClass.STORAGE_ERROR,
                message=f"Storage check error: {exc}",
                duration_ms=ms,
            )


# ---------------------------------------------------------------------------
# 8. Database Check
# ---------------------------------------------------------------------------


@dataclass
class DatabaseCheck:
    check_name: str
    db_url: str
    timeout: float
    adapter: NetworkAdapter

    def run(self) -> HealthCheckResult:
        # Redact credentials from displayed URL
        display_url = _redact_url(self.db_url)
        start = time.monotonic()
        try:
            info = self.adapter.check_database(self.db_url, self.timeout)
            ms = (time.monotonic() - start) * 1000
            connected = info.get("connected", False)
            latency_ms: float = info.get("latency_ms", ms)
            pending = info.get("pending_migrations", False)
            details = {
                "url": display_url,
                "connected": connected,
                "latency_ms": latency_ms,
                "pending_migrations": pending,
            }
            if not connected:
                return HealthCheckResult.fail(
                    self.check_name, CheckCategory.DATABASE, display_url,
                    FailureClass.DATABASE_ERROR,
                    message=f"Database: connection refused ({display_url})",
                    duration_ms=ms,
                    details=details,
                )
            if pending:
                return HealthCheckResult.warn(
                    self.check_name, CheckCategory.DATABASE, display_url,
                    message=f"Database: connected ({latency_ms:.0f}ms) — pending migrations detected",
                    repair_hint="Run: wooprice db migrate",
                    duration_ms=ms,
                    details=details,
                )
            return HealthCheckResult.ok(
                self.check_name, CheckCategory.DATABASE, display_url,
                message=f"Database: connected ({latency_ms:.0f}ms)",
                duration_ms=ms,
                details=details,
            )
        except DatabaseAdapterError as exc:
            ms = (time.monotonic() - start) * 1000
            return HealthCheckResult.fail(
                self.check_name, CheckCategory.DATABASE, display_url,
                FailureClass.DATABASE_ERROR,
                message=f"Database error: {exc}",
                duration_ms=ms,
            )
        except Exception as exc:
            ms = (time.monotonic() - start) * 1000
            fc = classify_exception(exc)
            return HealthCheckResult.fail(
                self.check_name, CheckCategory.DATABASE, display_url, fc,
                message=f"Database check error: {exc}",
                duration_ms=ms,
            )


# ---------------------------------------------------------------------------
# 9. Docker Check (stub in CP1 — implemented in B6)
# ---------------------------------------------------------------------------


@dataclass
class DockerCheck:
    check_name: str
    adapter: NetworkAdapter

    def run(self) -> HealthCheckResult:
        return HealthCheckResult.stub_skip(
            self.check_name,
            CheckCategory.DOCKER,
            target="docker",
            reason="Docker check not available in this phase (implemented in B6).",
        )


# ---------------------------------------------------------------------------
# 10. Integration Check (orchestrates DNS → TCP → TLS → HTTP → Auth chain)
# ---------------------------------------------------------------------------


@dataclass
class IntegrationCheck:
    """Runs the full check chain for an integration service."""

    check_name: str
    service_label: str
    url: str
    timeout: float
    adapter: NetworkAdapter
    expected_http_status: int = 200
    http_method: str = "HEAD"
    auth_url: Optional[str] = None
    auth_username: Optional[str] = None
    auth_password: Optional[str] = None

    def run_chain(self) -> list[HealthCheckResult]:
        """Run DNS → TCP → TLS → HTTP → Auth chain; return all results."""
        from urllib.parse import urlparse

        parsed = urlparse(self.url)
        host = parsed.hostname or self.url
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        use_tls = parsed.scheme == "https"
        label = self.service_label

        # 1. DNS
        dns = DNSCheck(f"{label}:dns", host, self.adapter).run()
        results: list[HealthCheckResult] = [dns]

        # 2. TCP
        tcp = TCPCheck(
            f"{label}:tcp", host, port, self.timeout, self.adapter,
            prerequisite_result=dns
        ).run()
        results.append(tcp)

        # 3. TLS (only for HTTPS)
        if use_tls:
            prereq = tcp
            tls = TLSCheck(
                f"{label}:tls", host, port, self.timeout, self.adapter,
                prerequisite_result=prereq
            ).run()
            results.append(tls)
            http_prereq = tls
        else:
            http_prereq = tcp

        # 4. HTTP
        http = HTTPCheck(
            f"{label}:http", self.url, self.http_method,
            self.expected_http_status, self.timeout, self.adapter,
            prerequisite_result=http_prereq
        ).run()
        results.append(http)

        # 5. Auth (only if credentials supplied)
        if self.auth_username is not None and self.auth_password is not None:
            auth_url = self.auth_url or self.url
            auth = AuthCheck(
                f"{label}:auth", auth_url, self.auth_username,
                self.auth_password, self.timeout, self.adapter,
                service_label=label,
                prerequisite_result=http
            ).run()
            results.append(auth)

        return results

    def run(self) -> HealthCheckResult:
        """Return a single summary HealthCheckResult for the integration chain."""
        chain_results = self.run_chain()
        # The worst-status result determines the summary
        status_order = {
            HealthStatus.FAIL: 3,
            HealthStatus.WARN: 2,
            HealthStatus.SKIP: 1,
            HealthStatus.UNKNOWN: 0,
            HealthStatus.PASS: 0,
        }
        worst = max(chain_results, key=lambda r: status_order.get(r.status, 0))
        from .aggregation import aggregate_results
        summary = aggregate_results(chain_results)
        details = {
            "service": self.service_label,
            "url": self.url,
            "chain": [r.to_dict() for r in chain_results],
            "overall_status": summary.overall_status.value,
        }
        if worst.status == HealthStatus.PASS or all(
            r.status in (HealthStatus.PASS, HealthStatus.WARN) for r in chain_results
        ):
            if worst.status == HealthStatus.WARN:
                return HealthCheckResult.warn(
                    self.check_name, CheckCategory.INTEGRATION, self.url,
                    message=f"{self.service_label}: degraded ({worst.message})",
                    repair_hint=worst.repair_hint,
                    details=details,
                )
            return HealthCheckResult.ok(
                self.check_name, CheckCategory.INTEGRATION, self.url,
                message=f"{self.service_label}: all checks passed",
                details=details,
            )
        return HealthCheckResult.fail(
            self.check_name, CheckCategory.INTEGRATION, self.url,
            worst.failure_class,
            message=f"{self.service_label}: {worst.message}",
            repair_hint=worst.repair_hint,
            details=details,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _redact_url(url: str) -> str:
    """Remove credentials from a URL for safe display."""
    from urllib.parse import urlparse, urlunparse
    parsed = urlparse(url)
    safe = parsed._replace(netloc=parsed.hostname or "")
    if parsed.port:
        safe = safe._replace(netloc=f"{parsed.hostname}:{parsed.port}")
    return urlunparse(safe)
