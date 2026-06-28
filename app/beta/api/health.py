"""WooPrice Beta — /api/health router.

Public health probe used by load balancers, Nginx Proxy Manager, and the CLI.
No authentication required.  Returns minimal status — no internal details exposed.
"""

from fastapi import APIRouter

router = APIRouter()

_VERSION = "0.1.0-dev"


@router.get("/health")
async def health() -> dict:
    """Minimal liveness probe.  Always returns 200 OK when the app is running."""
    return {"status": "ok", "env": "beta", "version": _VERSION}
