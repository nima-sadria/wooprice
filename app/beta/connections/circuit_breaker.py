"""CP1.2 — Circuit breaker state machine.

Per the spec: CLOSED → OPEN (after failure_threshold consecutive failures)
→ HALF_OPEN (after recovery_window_s) → CLOSED (on success) or OPEN (on failure).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from .models import CircuitState


@dataclass
class CircuitBreakerConfig:
    """Configuration for the circuit breaker."""

    failure_threshold: int = 3
    recovery_window_s: float = 30.0
    success_threshold: int = 1


class CircuitBreaker:
    """Per-connection circuit breaker.

    Thread-safety note: CP1 is single-threaded (no background polling until B6).
    Locking is deferred to B6.
    """

    def __init__(self, config: Optional[CircuitBreakerConfig] = None) -> None:
        self._config = config or CircuitBreakerConfig()
        self._state: CircuitState = CircuitState.CLOSED
        self._consecutive_failures: int = 0
        self._consecutive_successes: int = 0
        self._last_failure_time: Optional[float] = None
        self._last_failure_class: Optional[str] = None

    # ------------------------------------------------------------------
    # State property (transitions OPEN → HALF_OPEN automatically)
    # ------------------------------------------------------------------

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - (self._last_failure_time or 0.0)
            if elapsed >= self._config.recovery_window_s:
                self._state = CircuitState.HALF_OPEN
                self._consecutive_successes = 0
        return self._state

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def allow_request(self) -> bool:
        """Return True if a request should be allowed through."""
        s = self.state  # triggers automatic OPEN → HALF_OPEN transition
        if s == CircuitState.CLOSED:
            return True
        if s == CircuitState.OPEN:
            return False
        # HALF_OPEN: allow exactly one probe
        return True

    def record_success(self) -> None:
        """Record a successful call."""
        s = self.state
        if s == CircuitState.HALF_OPEN:
            self._consecutive_successes += 1
            if self._consecutive_successes >= self._config.success_threshold:
                self._state = CircuitState.CLOSED
                self._consecutive_failures = 0
                self._last_failure_time = None
                self._last_failure_class = None
        elif s == CircuitState.CLOSED:
            self._consecutive_failures = 0

    def record_failure(self, failure_class: Optional[str] = None) -> None:
        """Record a failed call."""
        s = self.state
        self._last_failure_time = time.monotonic()
        if failure_class is not None:
            self._last_failure_class = failure_class
        if s == CircuitState.HALF_OPEN:
            # Probe failed — revert to OPEN
            self._state = CircuitState.OPEN
            self._consecutive_failures = self._config.failure_threshold
        else:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._config.failure_threshold:
                self._state = CircuitState.OPEN

    def force_reset(self) -> None:
        """Force the circuit to CLOSED — used after a service recovers."""
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._consecutive_successes = 0
        self._last_failure_time = None
        self._last_failure_class = None

    @property
    def last_failure_class(self) -> Optional[str]:
        return self._last_failure_class

    @property
    def failure_count(self) -> int:
        return self._consecutive_failures
