"""Integration Platform foundation service."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.beta.integrations.contracts import (
    ConnectorCapabilityDocument,
    ConnectorCreateRequest,
    ConnectorHealthStatus,
    ConnectorIdentity,
    ConnectorInstanceShape,
    ConnectorSettingValue,
)
from app.beta.integrations.models import ConnectorInstance
from app.beta.integrations.registry import registry
from app.beta.integrations.repository import ConnectorRepository


def _instance_to_shape(instance: ConnectorInstance) -> ConnectorInstanceShape:
    definition = registry.get_definition(instance.connector_type)
    if definition is None:
        capabilities = {}
    else:
        capabilities = definition.connector.capabilities.model_dump()

    settings = [
        ConnectorSettingValue(
            key=s.key,
            value=None if s.secret else s.value_json,
            secret=s.secret,
            configured=s.configured,
        )
        for s in sorted(instance.settings, key=lambda item: item.key)
    ]
    return ConnectorInstanceShape(
        connector=ConnectorCapabilityDocument(
            identity=ConnectorIdentity(
                id=instance.id,
                name=instance.name,
                type=instance.connector_type,
                version=instance.version,
                enabled=instance.enabled,
                read_only=instance.read_only,
            ),
            capabilities=capabilities,
            status=ConnectorHealthStatus(instance.status),
        ),
        settings=settings,
        created_at=instance.created_at.isoformat(),
        updated_at=instance.updated_at.isoformat(),
    )


class IntegrationService:
    def __init__(self, db: Session):
        self.repo = ConnectorRepository(db)

    def list_registry(self):
        return registry.list_definitions()

    def get_registry_definition(self, connector_type: str):
        definition = registry.get_definition(connector_type)
        if definition is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Connector type not found.")
        return definition

    def list_instances(self) -> list[ConnectorInstanceShape]:
        return [_instance_to_shape(i) for i in self.repo.list_instances()]

    def create_instance(self, body: ConnectorCreateRequest) -> ConnectorInstanceShape:
        definition = self.get_registry_definition(body.connector_type)
        connector_id = body.id or definition.connector.identity.id
        existing = self.repo.get_instance(connector_id)
        if existing is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Connector instance already exists.")

        instance = ConnectorInstance(
            id=connector_id,
            name=body.name or definition.connector.identity.name,
            connector_type=definition.connector.identity.type,
            version=definition.connector.identity.version,
            enabled=body.enabled,
            read_only=True if body.read_only is False else body.read_only,
            status=ConnectorHealthStatus.DISABLED.value,
        )
        return _instance_to_shape(self.repo.add_instance(instance))

    def get_instance(self, connector_id: str) -> ConnectorInstanceShape:
        instance = self.repo.get_instance(connector_id)
        if instance is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Connector instance not found.")
        return _instance_to_shape(instance)

    def update_settings(
        self,
        connector_id: str,
        settings: list[ConnectorSettingValue],
    ) -> ConnectorInstanceShape:
        instance = self.repo.get_instance(connector_id)
        if instance is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Connector instance not found.")
        return _instance_to_shape(self.repo.upsert_settings(instance, settings))
