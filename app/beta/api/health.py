"""WooPrice Beta — /api/health router.

Health probe: returns environment label, version, and service status.
No authentication required. Used by load balancers and the CLI.

Implementation begins in B4.
"""

from fastapi import APIRouter

router = APIRouter()

# GET /api/health — implementation begins in B4.
