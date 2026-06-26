"""WooPrice Beta — /api/v2/flags router.

Feature flag management endpoints. Admin permission required.

Implementation begins in B11.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/flags", tags=["flags"])

# Endpoints implemented in B11.
