"""WooPrice Beta /api/v2/config router.

Read-only settings surface for Integration Platform connector settings. Writes
remain disabled in this wiring increment.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.beta.database import get_db
from app.beta.integrations.service import IntegrationService

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
async def list_editable_config(db: Session = Depends(get_db)) -> list[ConfigRecordShape]:
    records: list[ConfigRecordShape] = []
    for connector in IntegrationService(db).settings_summary():
        for setting in connector.settings:
            records.append(
                ConfigRecordShape(
                    field_name=f"connector.{connector.connector_id}.{setting.key}",
                    current_value="configured" if setting.secret and setting.configured else str(setting.value or ""),
                    is_editable=False,
                    is_secret=setting.secret,
                    is_installer_only=False,
                    description=f"{connector.name} connector setting",
                )
            )
    return records


@router.get("/{field_name}", response_model=ConfigRecordShape)
async def get_config_field(field_name: str, db: Session = Depends(get_db)) -> ConfigRecordShape:
    records = await list_editable_config(db)
    for record in records:
        if record.field_name == field_name:
            return record
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Configuration field not found.")


@router.put("/{field_name}", response_model=ConfigSetResponse)
async def set_config_field(field_name: str, body: ConfigSetRequest) -> ConfigSetResponse:
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        "Runtime connector settings writes are disabled in FlowHub Beta.",
    )
