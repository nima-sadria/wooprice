"""WooPrice Beta — /api/v2/config router.

Configuration management endpoints (read-only). Admin permission required.

Implementation begins in B5 (CLI Foundation).
The Runtime Configuration API was moved out of B3 scope by CHAT2 architecture
decision: B3 Configuration Foundation is framework-independent Core only.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/config", tags=["config"])

# Endpoints implemented in B5.
