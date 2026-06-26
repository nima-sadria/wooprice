"""WooPrice Beta — /api/v2/scheduler router.

Scheduling Engine endpoints. Gated by FEATURE_SCHEDULER.

Implementation begins in B8.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/scheduler", tags=["scheduler"])

# Endpoints implemented in B8.
