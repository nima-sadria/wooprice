"""WooPrice Beta — in-memory per-IP login rate limiter (BU2).

Sliding-window counter: max 5 login attempts per IP per 60 seconds.
No Redis dependency; state is per-process and lost on restart (acceptable
for Beta).  Thread-safe via a Lock so this works from async FastAPI handlers.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

_MAX_ATTEMPTS = 5
_WINDOW_SECONDS = 60

_attempts: dict[str, deque[float]] = defaultdict(deque)
_lock = Lock()


def check_rate_limit(ip: str) -> bool:
    """Return True if this IP is within the allowed rate, False if blocked."""
    now = time.monotonic()
    with _lock:
        dq = _attempts[ip]
        while dq and dq[0] < now - _WINDOW_SECONDS:
            dq.popleft()
        return len(dq) < _MAX_ATTEMPTS


def record_attempt(ip: str) -> None:
    """Record one login attempt for this IP."""
    with _lock:
        _attempts[ip].append(time.monotonic())


def clear_all() -> None:
    """Reset all counters.  Test use only."""
    with _lock:
        _attempts.clear()
