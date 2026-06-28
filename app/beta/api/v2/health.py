"""WooPrice Beta — /api/v2/health router (CP1.3 contract stubs).

OD3 split (CHAT2 decision 2026-06-28):
  GET /api/health        — public minimal (load balancers, uptime monitors)
  GET /api/v2/health     — authenticated full ControlPlaneStatus
  POST /api/v2/health/check — admin: trigger on-demand check

The public endpoint is in app/beta/api/health.py.
This file defines the authenticated v2 contract.

Authentication note: All endpoints in this router require a valid JWT.
Auth middleware is implemented in B7. Stubs are unauthenticated in CP1.
"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/health", tags=["health"])


class IntegrationStateShape(BaseModel):
    status: str
    failure_class: str
    last_ok_at: Optional[str]
    last_checked_at: Optional[str]


class ControlPlaneStatusShape(BaseModel):
    timestamp: str
    overall_health: str
    local_auth_available: bool
    config_readable: bool
    config_writable: bool
    database_available: bool
    storage_available: bool
    integration_states: dict[str, IntegrationStateShape]
    feature_availability: dict[str, bool]


class OnDemandCheckRequest(BaseModel):
    target: str = "all"


@router.get("", response_model=ControlPlaneStatusShape)
async def get_health_full() -> ControlPlaneStatusShape:
    """Return full ControlPlaneStatus including per-service integration states.

    JWT authentication required (enforced in B7).
    Live implementation in B6.
    """
    raise NotImplementedError("Full health endpoint implemented in B6.")


@router.post("/check")
async def trigger_health_check(body: OnDemandCheckRequest) -> dict:
    """Trigger an on-demand health check for a specific target or all targets.

    Admin permission required (enforced in B7).
    Live implementation in B6.
    """
    raise NotImplementedError("On-demand health check endpoint implemented in B6.")
