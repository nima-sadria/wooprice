"""CP1.2 — In-memory connection result cache.

OD1 (CHAT2 2026-06-28): CP1 uses in-memory cache only.
No Redis, no file, no database.  Cache is lost on process restart.
"""

from __future__ import annotations

import time
from typing import Optional

from .models import ConnectionResult

_DEFAULT_TTL_S = 60.0


class ConnectionCache:
    """TTL-based in-memory cache for ConnectionResult values."""

    def __init__(self, default_ttl_seconds: float = _DEFAULT_TTL_S) -> None:
        self._default_ttl = default_ttl_seconds
        # {name: (result, expiry_monotonic)}
        self._store: dict[str, tuple[ConnectionResult, float]] = {}

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def get(self, name: str) -> Optional[ConnectionResult]:
        """Return cached result for name, or None if missing / expired."""
        entry = self._store.get(name)
        if entry is None:
            return None
        result, expiry = entry
        if time.monotonic() > expiry:
            del self._store[name]
            return None
        return result

    def set(
        self,
        name: str,
        result: ConnectionResult,
        ttl_seconds: Optional[float] = None,
    ) -> None:
        """Store result with the given TTL (defaults to constructor default)."""
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        expiry = time.monotonic() + ttl
        self._store[name] = (result, expiry)

    def invalidate(self, name: str) -> None:
        """Remove entry for name (no-op if not present)."""
        self._store.pop(name, None)

    def clear(self) -> None:
        """Remove all entries."""
        self._store.clear()

    # ------------------------------------------------------------------
    # Introspection (for tests and diagnostics)
    # ------------------------------------------------------------------

    def size(self) -> int:
        """Number of entries currently in cache (may include expired)."""
        return len(self._store)

    def has(self, name: str) -> bool:
        """True if name is in cache and not yet expired."""
        return self.get(name) is not None

    def remaining_ttl(self, name: str) -> Optional[float]:
        """Remaining TTL in seconds for name, or None if not cached."""
        entry = self._store.get(name)
        if entry is None:
            return None
        _, expiry = entry
        remaining = expiry - time.monotonic()
        return max(0.0, remaining)
