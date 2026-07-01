"""WooPrice Beta /api/v2/sources router.

Source inspection endpoints backed by Integration Platform connector records.
This router does not call source systems directly.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.beta.database import get_db
from app.beta.integrations.contracts import ConnectorSourceListResponse
from app.beta.integrations.service import IntegrationService

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("", response_model=ConnectorSourceListResponse)
async def list_sources(db: Session = Depends(get_db)) -> ConnectorSourceListResponse:
    return IntegrationService(db).list_sources()
