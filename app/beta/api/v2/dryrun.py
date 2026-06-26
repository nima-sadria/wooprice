"""WooPrice Beta — /api/v2/dryrun router.

Dry Run Engine endpoints. Gated by FEATURE_DRY_RUN.

Implementation begins in B6.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/dryrun", tags=["dryrun"])

# Endpoints implemented in B6.
