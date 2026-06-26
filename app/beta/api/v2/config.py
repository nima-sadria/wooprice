"""WooPrice Beta — /api/v2/config router.

Configuration management endpoints (read-only). Admin permission required.

Implementation begins in B3.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/config", tags=["config"])

# Endpoints implemented in B3.
