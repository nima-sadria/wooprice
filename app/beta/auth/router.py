"""WooPrice Beta — auth API router (BU2).

Public routes  (no auth required):
  POST /api/auth/login    — issue access + refresh tokens
  POST /api/auth/refresh  — rotate refresh token, issue new access token

Protected routes (Bearer access token required):
  POST /api/auth/logout   — revoke refresh token, audit
  GET  /api/auth/me       — return current user profile

Security properties:
  - Argon2 password verification
  - In-memory rate limiting (5 attempts / 60 s per IP)
  - Audit event written for every login attempt, logout, and refresh
  - Refresh token rotation on every /refresh call
  - Secrets are never echoed in responses or logs
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

_UTC = timezone.utc


def _utcnow() -> datetime:
    return datetime.now(_UTC).replace(tzinfo=None)

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.beta.database import get_db

from .dependencies import get_current_user
from .jwt_service import create_access_token
from .models import BetaUser
from .password import verify_password
from .rate_limiter import check_rate_limit, record_attempt
from .refresh_token import generate_refresh_token, hash_refresh_token
from .repository import (
    create_audit_event,
    get_active_refresh_token,
    get_user_by_id,
    get_user_by_username,
    revoke_refresh_token,
    store_refresh_token,
)

router = APIRouter()

_REFRESH_EXPIRE_DAYS = 30

_ROLE_PERMISSIONS: dict[str, dict[str, bool]] = {
    "admin": {
        "can_access_site": True,
        "can_fetch": True,
        "can_view_logs": True,
        "can_view_settings": True,
    },
    "viewer": {
        "can_access_site": True,
        "can_view_logs": True,
    },
}


# ── Request / Response schemas ────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class MeResponse(BaseModel):
    username: str
    role: str
    is_admin: bool
    is_super_admin: bool
    permissions: dict[str, bool]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _client_ip(request: Request) -> str:
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _issue_tokens(db: Session, user: BetaUser) -> TokenResponse:
    access = create_access_token(user.id, user.username, user.role)
    raw_refresh, refresh_hash = generate_refresh_token()
    expires_at = _utcnow() + timedelta(days=_REFRESH_EXPIRE_DAYS)
    store_refresh_token(db, user_id=user.id, token_hash=refresh_hash, expires_at=expires_at)
    return TokenResponse(token=access, refresh_token=raw_refresh)


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/auth/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> TokenResponse:
    ip = _client_ip(request)

    if not check_rate_limit(ip):
        create_audit_event(db, username=body.username, event="login_rate_limited", ip_address=ip)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please wait and try again.",
        )

    record_attempt(ip)

    user = get_user_by_username(db, body.username)
    if not user or not user.is_active or not verify_password(body.password, user.hashed_password):
        create_audit_event(db, username=body.username, event="login_failed", ip_address=ip)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials.")

    tokens = _issue_tokens(db, user)
    create_audit_event(db, username=user.username, event="login_success", ip_address=ip)
    return tokens


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    body: RefreshRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: BetaUser = Depends(get_current_user),
) -> None:
    ip = _client_ip(request)
    revoke_refresh_token(db, hash_refresh_token(body.refresh_token))
    create_audit_event(db, username=current_user.username, event="logout", ip_address=ip)


@router.post("/auth/refresh", response_model=TokenResponse)
async def refresh(
    body: RefreshRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> TokenResponse:
    ip = _client_ip(request)
    token_hash = hash_refresh_token(body.refresh_token)
    stored = get_active_refresh_token(db, token_hash)

    if not stored or stored.expires_at < _utcnow():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token.",
        )

    user = get_user_by_id(db, stored.user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive.",
        )

    # Token rotation: revoke old token, issue fresh pair
    revoke_refresh_token(db, token_hash)
    tokens = _issue_tokens(db, user)
    create_audit_event(db, username=user.username, event="token_refresh", ip_address=ip)
    return tokens


@router.get("/auth/me", response_model=MeResponse)
async def me(current_user: BetaUser = Depends(get_current_user)) -> MeResponse:
    permissions = _ROLE_PERMISSIONS.get(current_user.role, _ROLE_PERMISSIONS["viewer"])
    return MeResponse(
        username=current_user.username,
        role=current_user.role,
        is_admin=current_user.role == "admin",
        is_super_admin=False,
        permissions=permissions,
    )
