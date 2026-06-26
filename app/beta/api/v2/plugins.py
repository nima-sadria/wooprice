"""WooPrice Beta — /api/v2/plugins router.

Plugin management endpoints. Gated by FEATURE_PLUGIN_SYSTEM.
Admin permission required for all operations.

Implementation begins in B12.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/plugins", tags=["plugins"])

# Endpoints implemented in B12.
