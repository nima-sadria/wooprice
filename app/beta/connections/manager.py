"""CP1.2 — Connection Manager.

Orchestrates retry, circuit breaker, cache, and failure classification for
all outbound connection probes.  Credentials are never stored here.
"""

from __future__ import annotations

import random
import time
from datetime import datetime, timezone
from typing import Callable, Optional
from urllib.parse import urlparse

from app.beta.control_plane.failure import FailureClass, Severity

from .adapters import NetworkAdapter
from .cache import ConnectionCache
from .circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from .classifier import classify_exception, classify_http_response, is_retryable
from .models import (
    CircuitState,
    ConnectionDefinition,
    ConnectionResult,
    ConnectionStatus,
    ConnectionType,
)


class ConnectionManager:
    """Singleton-style service that manages all outbound connection checks.

    Usage:
        manager = ConnectionManager(adapter=my_adapter)
        manager.register(definition)
        result = manager.check("nextcloud")
    """

    def __init__(
        self,
        adapter: NetworkAdapter,
        cache: Optional[ConnectionCache] = None,
        circuit_config: Optional[CircuitBreakerConfig] = None,
        sleep_fn: Optional[Callable[[float], None]] = None,
    ) -> None:
        self._adapter = adapter
        self._cache = cache or ConnectionCache()
        self._circuit_config = circuit_config or CircuitBreakerConfig()
        # Injected sleep function; replaced in tests to avoid real delays
        self._sleep: Callable[[float], None] = sleep_fn or time.sleep

        self._definitions: dict[str, ConnectionDefinition] = {}
        self._circuit_breakers: dict[str, CircuitBreaker] = {}

    # ------------------------------------------------------------------
    # Registry
    # ------------------------------------------------------------------

    def register(self, definition: ConnectionDefinition) -> None:
        """Register a connection definition (idempotent by name)."""
        self._definitions[definition.name] = definition
        if definition.name not in self._circuit_breakers:
            self._circuit_breakers[definition.name] = CircuitBreaker(self._circuit_config)

    def list_connections(self) -> list[ConnectionDefinition]:
        return list(self._definitions.values())

    def get_definition(self, name: str) -> Optional[ConnectionDefinition]:
        return self._definitions.get(name)

    # ------------------------------------------------------------------
    # Cache access
    # ------------------------------------------------------------------

    def get_cached(self, name: str) -> Optional[ConnectionResult]:
        """Return the cached result for name without triggering a new check."""
        return self._cache.get(name)

    def invalidate(self, name: str) -> None:
        """Invalidate cache and reset circuit breaker for name."""
        self._cache.invalidate(name)
        cb = self._circuit_breakers.get(name)
        if cb is not None:
            cb.force_reset()

    # ------------------------------------------------------------------
    # Public check API
    # ------------------------------------------------------------------

    def check(self, name: str) -> ConnectionResult:
        """Check a registered connection with circuit breaker and cache.

        Returns a cached result if one is fresh.  Returns an immediate FAILED
        result if the circuit breaker is OPEN (no network call).
        """
        definition = self._require_definition(name)

        if not definition.enabled:
            return ConnectionResult.disabled(definition)

        cb = self._circuit_breakers[name]

        if not cb.allow_request():
            last_fc = FailureClass(cb.last_failure_class) if cb.last_failure_class else FailureClass.UNKNOWN_ERROR
            return ConnectionResult.circuit_open(definition, last_fc)

        cached = self._cache.get(name)
        if cached is not None:
            result = _mark_from_cache(cached)
            return result

        result = self._check_with_retry(definition)

        if result.status == ConnectionStatus.HEALTHY:
            cb.record_success()
            # Only cache successful results (spec: "successful connection probes are cached")
            self._cache.set(name, result, definition.cache_ttl_seconds)
        else:
            cb.record_failure(result.failure_class.value)

        return result

    def check_bypass_circuit(self, name: str) -> ConnectionResult:
        """Check a connection, bypassing the circuit breaker.

        Used by the diagnostic runner and CLI on-demand tests (per spec §7.3).
        The cache is also bypassed; the result is written back to cache.
        """
        definition = self._require_definition(name)

        if not definition.enabled:
            return ConnectionResult.disabled(definition)

        result = self._check_with_retry(definition)

        if result.status == ConnectionStatus.HEALTHY:
            cb = self._circuit_breakers[name]
            cb.record_success()
            self._cache.set(name, result, definition.cache_ttl_seconds)

        return result

    def check_all(self) -> dict[str, ConnectionResult]:
        """Check all registered connections and return a name-keyed dict."""
        return {name: self.check(name) for name in self._definitions}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_definition(self, name: str) -> ConnectionDefinition:
        d = self._definitions.get(name)
        if d is None:
            raise KeyError(f"Connection '{name}' is not registered.")
        return d

    def _check_with_retry(self, definition: ConnectionDefinition) -> ConnectionResult:
        """Run the connection check with exponential backoff retry."""
        last_result: Optional[ConnectionResult] = None
        max_attempts = max(1, definition.retry_attempts)

        for attempt in range(1, max_attempts + 1):
            result = self._perform_check(definition, attempt)

            if result.status == ConnectionStatus.HEALTHY:
                return result

            if not result.retryable:
                return result

            last_result = result

            if attempt < max_attempts:
                delay = _backoff_delay(definition.retry_backoff_seconds, attempt)
                self._sleep(delay)

        return last_result or self._perform_check(definition, 1)

    def _perform_check(
        self, definition: ConnectionDefinition, attempt: int = 1
    ) -> ConnectionResult:
        """Execute a single check against the endpoint."""
        parsed = urlparse(definition.endpoint)
        host = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        use_tls = parsed.scheme == "https"
        timeout = definition.timeout_seconds
        start = time.monotonic()

        if not host:
            return _make_failed(
                definition,
                FailureClass.CONFIGURATION_ERROR,
                "No hostname in configured endpoint URL.",
                attempt=attempt,
            )

        try:
            # DNS
            self._adapter.resolve_dns(host)

            # TCP
            latency_ms = self._adapter.tcp_connect(host, port, timeout)

            # TLS
            if use_tls:
                self._adapter.tls_handshake(host, port, timeout)

            # HTTP probe
            status_code, _ = self._adapter.http_request(
                "HEAD", definition.endpoint, timeout, {}, None
            )

            elapsed_ms = (time.monotonic() - start) * 1000
            fc = classify_http_response(status_code)

            if fc == FailureClass.NONE:
                return ConnectionResult(
                    name=definition.name,
                    connection_type=definition.connection_type,
                    status=ConnectionStatus.HEALTHY,
                    reachable=True,
                    authenticated=None,
                    latency_ms=latency_ms,
                    failure_class=FailureClass.NONE,
                    severity=Severity.INFO,
                    message=f"Connection healthy ({latency_ms:.0f}ms).",
                    repair_hint="",
                    checked_at=datetime.now(tz=timezone.utc),
                    retryable=False,
                    circuit_state=CircuitState.CLOSED,
                    attempt_number=attempt,
                )
            else:
                meta = fc.meta
                reachable = fc not in {
                    FailureClass.UNAUTHORIZED,
                    FailureClass.FORBIDDEN,
                }
                return ConnectionResult(
                    name=definition.name,
                    connection_type=definition.connection_type,
                    status=ConnectionStatus.FAILED,
                    reachable=reachable,
                    authenticated=None,
                    latency_ms=elapsed_ms,
                    failure_class=fc,
                    severity=meta.severity_default,
                    message=meta.user_message,
                    repair_hint=meta.operator_hint,
                    checked_at=datetime.now(tz=timezone.utc),
                    retryable=is_retryable(fc),
                    circuit_state=CircuitState.CLOSED,
                    attempt_number=attempt,
                )

        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            fc = classify_exception(exc)
            return _make_failed(
                definition,
                fc,
                _exception_message(exc, fc, host),
                latency_ms=elapsed_ms,
                attempt=attempt,
            )


# ---------------------------------------------------------------------------
# Module-level helpers (stateless)
# ---------------------------------------------------------------------------


def _make_failed(
    definition: ConnectionDefinition,
    failure_class: FailureClass,
    message: str,
    latency_ms: Optional[float] = None,
    attempt: int = 1,
) -> ConnectionResult:
    meta = failure_class.meta
    # Determine reachability from failure class
    reachable: Optional[bool] = None
    if failure_class in {FailureClass.DNS_FAILURE, FailureClass.TCP_FAILURE,
                         FailureClass.UNREACHABLE, FailureClass.TIMEOUT}:
        reachable = False
    elif failure_class in {FailureClass.UNAUTHORIZED, FailureClass.FORBIDDEN}:
        reachable = True

    return ConnectionResult(
        name=definition.name,
        connection_type=definition.connection_type,
        status=ConnectionStatus.FAILED,
        reachable=reachable,
        authenticated=None,
        latency_ms=latency_ms,
        failure_class=failure_class,
        severity=meta.severity_default,
        message=message,
        repair_hint=meta.operator_hint,
        checked_at=datetime.now(tz=timezone.utc),
        retryable=is_retryable(failure_class),
        circuit_state=CircuitState.CLOSED,
        attempt_number=attempt,
    )


def _exception_message(exc: Exception, fc: FailureClass, host: str) -> str:
    """Build a user-facing message from an exception, never exposing secrets."""
    base = fc.meta.user_message
    raw = str(exc)
    # Only include the raw message if it is safe (no credential patterns)
    if raw and "password" not in raw.lower() and "secret" not in raw.lower():
        return f"{base} ({raw})"
    return base


def _backoff_delay(base_s: float, attempt: int) -> float:
    """Exponential backoff with ±25% jitter."""
    delay = base_s * (2 ** (attempt - 1))
    jitter = delay * 0.25 * (random.random() * 2 - 1)
    return max(0.0, delay + jitter)


def _mark_from_cache(result: ConnectionResult) -> ConnectionResult:
    """Return a shallow copy of result with from_cache=True."""
    import dataclasses
    return dataclasses.replace(result, from_cache=True)
