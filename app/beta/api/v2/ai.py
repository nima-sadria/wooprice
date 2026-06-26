"""WooPrice Beta — /api/v2/ai router.

AI Foundation advisory endpoints. Gated by FEATURE_AI.
No AI endpoint triggers execution.

Implementation begins in B9.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/ai", tags=["ai"])

# Endpoints implemented in B9.
