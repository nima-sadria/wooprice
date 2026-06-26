"""WooPrice Beta — /api/v2/users router.

User management endpoints (CRUD, roles, deactivation, password reset).

Implementation begins in B10.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/users", tags=["users"])

# Endpoints implemented in B10.
