"""WooPrice Beta — JWT access token service (BU2).

Access tokens are short-lived JWTs (15 min) signed with BETA_JWT_SECRET.
Refresh tokens are opaque random bytes stored hashed in the DB (see refresh_token.py).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

_UTC = timezone.utc

import jwt

_ALGORITHM = "HS256"
_ACCESS_TOKEN_EXPIRE_MINUTES = 15
_SECRET_ENV = "BETA_JWT_SECRET"


def _secret() -> str:
    s = os.environ.get(_SECRET_ENV, "")
    if not s:
        raise RuntimeError(f"{_SECRET_ENV} is not configured")
    return s


def create_access_token(user_id: int, username: str, role: str) -> str:
    now = datetime.now(_UTC).replace(tzinfo=None)  # naive UTC for PyJWT compat
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=_ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, _secret(), algorithm=_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Return decoded payload.  Raises jwt.InvalidTokenError if invalid/expired."""
    payload: dict = jwt.decode(token, _secret(), algorithms=[_ALGORITHM])
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("Not an access token")
    return payload
