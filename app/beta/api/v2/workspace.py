"""WooPrice Beta /api/v2/workspace router.

Read-only workspace summary backed by Integration Platform state. No Apply,
Scheduler, or pricing automation endpoints are exposed here.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.beta.database import get_db
from app.beta.integrations.contracts import WorkspaceIntegrationSummary
from app.beta.integrations.service import IntegrationService

router = APIRouter(prefix="/workspace", tags=["workspace"])


@router.get("", response_model=WorkspaceIntegrationSummary)
async def get_workspace_summary(db: Session = Depends(get_db)) -> WorkspaceIntegrationSummary:
    return IntegrationService(db).workspace_summary()
