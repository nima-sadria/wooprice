"""Integration Platform Foundation API.

These endpoints expose registry, connector status, and settings contracts only.
They do not execute writes, Apply, Scheduler runs, or pricing automation.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.beta.database import get_db
from app.beta.integrations.contracts import (
    ConnectorCreateRequest,
    ConnectorDefinition,
    ConnectorInstanceShape,
    ConnectorListResponse,
    ConnectorRegistryResponse,
    ConnectorSettingValue,
    ConnectorSettingsUpdateRequest,
    ConnectorTelemetryResponse,
)
from app.beta.integrations.service import IntegrationService

router = APIRouter(prefix="/integrations", tags=["integrations"])


def _service(db: Session = Depends(get_db)) -> IntegrationService:
    return IntegrationService(db)


@router.get("/registry", response_model=ConnectorRegistryResponse)
async def list_connector_registry(
    service: IntegrationService = Depends(_service),
) -> ConnectorRegistryResponse:
    return ConnectorRegistryResponse(items=service.list_registry())


@router.get("/registry/{connector_type}", response_model=ConnectorDefinition)
async def get_connector_definition(
    connector_type: str,
    service: IntegrationService = Depends(_service),
) -> ConnectorDefinition:
    return service.get_registry_definition(connector_type)


@router.get("/connectors", response_model=ConnectorListResponse)
async def list_connectors(
    service: IntegrationService = Depends(_service),
) -> ConnectorListResponse:
    return ConnectorListResponse(items=service.list_instances())


@router.post("/connectors", response_model=ConnectorInstanceShape, status_code=201)
async def create_connector(
    body: ConnectorCreateRequest,
    service: IntegrationService = Depends(_service),
) -> ConnectorInstanceShape:
    return service.create_instance(body)


@router.get("/connectors/{connector_id}", response_model=ConnectorInstanceShape)
async def get_connector(
    connector_id: str,
    service: IntegrationService = Depends(_service),
) -> ConnectorInstanceShape:
    return service.get_instance(connector_id)


@router.get("/connectors/{connector_id}/status", response_model=ConnectorInstanceShape)
async def get_connector_status(
    connector_id: str,
    service: IntegrationService = Depends(_service),
) -> ConnectorInstanceShape:
    return service.get_instance(connector_id)


@router.get("/connectors/{connector_id}/settings", response_model=list[ConnectorSettingValue])
async def get_connector_settings(
    connector_id: str,
    service: IntegrationService = Depends(_service),
) -> list[ConnectorSettingValue]:
    return service.get_instance(connector_id).settings


@router.patch("/connectors/{connector_id}/settings", response_model=ConnectorInstanceShape)
async def update_connector_settings(
    connector_id: str,
    body: ConnectorSettingsUpdateRequest,
    service: IntegrationService = Depends(_service),
) -> ConnectorInstanceShape:
    return service.update_settings(connector_id, body.settings)


@router.get("/telemetry", response_model=ConnectorTelemetryResponse)
async def list_connector_telemetry(
    connector_id: str | None = None,
    limit: int = 100,
    service: IntegrationService = Depends(_service),
) -> ConnectorTelemetryResponse:
    return service.telemetry(connector_id=connector_id, limit=limit)
