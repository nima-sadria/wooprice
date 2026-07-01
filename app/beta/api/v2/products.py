"""WooPrice Beta /api/v2/products router.

Read-only product inspection endpoints backed by Integration Platform Data
Layer records. This router does not call WooCommerce, Nextcloud, or any
external connector directly.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.beta.database import get_db
from app.beta.integrations.contracts import ConnectorProductListResponse
from app.beta.integrations.service import IntegrationService

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=ConnectorProductListResponse)
async def list_products(
    search: str = "",
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
) -> ConnectorProductListResponse:
    return IntegrationService(db).list_products(search=search, page=page, page_size=page_size)
