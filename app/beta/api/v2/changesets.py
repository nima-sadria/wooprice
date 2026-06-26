"""WooPrice Beta — /api/v2/changesets router.

Change Set Engine endpoints. Gated by FEATURE_CHANGE_SETS.

Implementation begins in B6.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/changesets", tags=["changesets"])

# Endpoints implemented in B6.
