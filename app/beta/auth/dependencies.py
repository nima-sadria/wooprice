"""WooPrice Beta — FastAPI auth dependency (BU2).

get_current_user() extracts and validates the Bearer access token from the
Authorization header and returns the corresponding BetaUser.  Raises 401
on any validation failure so that protected routes never see unauthenticated
callers.
"""

from __future__ import annotations

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.beta.database import get_db

from .jwt_service import decode_access_token
from .models import BetaUser
from .repository import get_user_by_id

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

_401 = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> BetaUser:
    if not token:
        raise _401
    try:
        payload = decode_access_token(token)
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = get_user_by_id(db, int(payload["sub"]))
    if not user or not user.is_active:
        raise _401
    return user
