"""WooPrice Beta — /api/v2/rules router.

Rule Engine management endpoints. Gated by FEATURE_RULE_ENGINE.

Implementation begins in B5.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/rules", tags=["rules"])

# Endpoints implemented in B5.
