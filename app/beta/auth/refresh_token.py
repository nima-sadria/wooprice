"""WooPrice Beta — opaque refresh token utilities (BU2).

Refresh tokens are random URL-safe strings.  Only the SHA-256 hash is
stored in the database; the raw token is returned to the client and never
persisted.
"""

from __future__ import annotations

import hashlib
import secrets


def generate_refresh_token() -> tuple[str, str]:
    """Return (raw_token, sha256_hex_hash).  Store hash; send raw to client."""
    raw = secrets.token_urlsafe(64)
    return raw, _hash(raw)


def hash_refresh_token(raw: str) -> str:
    return _hash(raw)


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
