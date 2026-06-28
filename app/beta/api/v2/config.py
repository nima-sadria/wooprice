"""WooPrice Beta — /api/v2/config router (CP1.3 contract stubs).

Runtime configuration read and update endpoints.
Admin permission required for write operations.

Contract shape defined in CP1.3.  Live implementation in B8 (UI) when the
RuntimeConfigService is wired into the FastAPI application lifecycle.

Authentication note: All endpoints require a valid JWT.
Auth middleware implemented in B7.
"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/config", tags=["config"])


class ConfigRecordShape(BaseModel):
    field_name: str
    current_value: str
    is_editable: bool
    is_secret: bool
    is_installer_only: bool
    description: str


class ConfigSetRequest(BaseModel):
    value: str


class ConfigSetResponse(BaseModel):
    success: bool
    field_name: str
    new_value: str
    error: Optional[str]


@router.get("", response_model=list[ConfigRecordShape])
async def list_editable_config() -> list[ConfigRecordShape]:
    """Return all editable runtime configuration fields.

    JWT authentication required (enforced in B7).
    Live implementation in B8.
    """
    raise NotImplementedError("Config list endpoint implemented in B8.")


@router.get("/{field_name}", response_model=ConfigRecordShape)
async def get_config_field(field_name: str) -> ConfigRecordShape:
    """Return a single configuration field value.

    JWT authentication required (enforced in B7).
    Live implementation in B8.
    """
    raise NotImplementedError("Config get endpoint implemented in B8.")


@router.put("/{field_name}", response_model=ConfigSetResponse)
async def set_config_field(field_name: str, body: ConfigSetRequest) -> ConfigSetResponse:
    """Update an editable runtime configuration field.

    Admin permission required (enforced in B7).
    Validates before writing. Rejects secrets and installer-only fields.
    Live implementation in B8.
    """
    raise NotImplementedError("Config set endpoint implemented in B8.")
