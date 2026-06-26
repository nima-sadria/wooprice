"""WooPrice Beta — /api/v2/safety router.

Safety Policy Engine endpoints. Gated by FEATURE_SAFETY_ENGINE.

Implementation begins in B5.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/safety", tags=["safety"])

# Endpoints implemented in B5.
