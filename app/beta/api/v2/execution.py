"""WooPrice Beta — /api/v2/execution router.

Execution Engine endpoints. Gated by FEATURE_EXECUTION.

Implementation begins in B7.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/execution", tags=["execution"])

# Endpoints implemented in B7.
