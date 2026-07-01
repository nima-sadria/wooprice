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
    ConnectorProductListResponse,
    ConnectorProductShape,
    ConnectorSourceListResponse,
    ConnectorSourceShape,
    ConnectorSettingValue,
    ConnectorTelemetryResponse,
    ConnectorTelemetryShape,
    IntegrationSettingsSummary,
    WorkspaceIntegrationSummary,
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


def _source_to_shape(source) -> ConnectorSourceShape:
    return ConnectorSourceShape(
        id=str(source.id),
        connector_id=source.connector_id,
        name=source.name,
        type=source.source_type,
        status=ConnectorHealthStatus(source.status),
        last_synced_at=source.last_synced_at.isoformat() if source.last_synced_at else None,
        product_count=source.product_count,
    )


def _product_to_shape(product) -> ConnectorProductShape:
    return ConnectorProductShape(
        id=str(product.id),
        connector_id=product.connector_id,
        external_id=product.external_id,
        name=product.name,
        sku=product.sku,
        current_price=product.current_price,
        inventory_quantity=product.inventory_quantity,
        category_names=product.category_names or [],
        updated_at=product.updated_at.isoformat() if product.updated_at else None,
    )


def _telemetry_to_shape(event) -> ConnectorTelemetryShape:
    return ConnectorTelemetryShape(
        id=event.id,
        connector_id=event.connector_id,
        event_name=event.event_name,
        severity=event.severity,
        message=event.message,
        created_at=event.created_at.isoformat(),
        metadata=event.metadata_json or {},
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
        instance = self.repo.add_instance(instance)
        self.repo.add_source_for_instance(instance)
        self.repo.record_telemetry(
            connector_id=instance.id,
            event_name="connector_created",
            message=f"Connector '{instance.name}' was created in read-only mode.",
            metadata={"connector_type": instance.connector_type},
        )
        return _instance_to_shape(instance)

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
        updated = self.repo.upsert_settings(instance, settings)
        self.repo.record_telemetry(
            connector_id=connector_id,
            event_name="connector_settings_updated",
            message="Connector settings were updated; secret values remain masked.",
            metadata={"updated_keys": [item.key for item in settings]},
        )
        return _instance_to_shape(updated)

    def list_sources(self) -> ConnectorSourceListResponse:
        return ConnectorSourceListResponse(items=[_source_to_shape(s) for s in self.repo.list_sources()])

    def list_products(self, search: str = "", page: int = 1, page_size: int = 50) -> ConnectorProductListResponse:
        page = max(page, 1)
        page_size = min(max(page_size, 1), 200)
        items, total = self.repo.list_products(search=search, page=page, page_size=page_size)
        return ConnectorProductListResponse(
            items=[_product_to_shape(item) for item in items],
            total=total,
            page=page,
            page_size=page_size,
        )

    def workspace_summary(self) -> WorkspaceIntegrationSummary:
        sources = self.repo.list_sources()
        connectors = self.repo.list_instances()
        return WorkspaceIntegrationSummary(
            source_count=len(sources),
            product_count=self.repo.count_products(),
            connector_count=len(connectors),
        )

    def settings_summary(self) -> list[IntegrationSettingsSummary]:
        return [
            IntegrationSettingsSummary(
                connector_id=instance.connector.identity.id,
                connector_type=instance.connector.identity.type,
                name=instance.connector.identity.name,
                settings=instance.settings,
            )
            for instance in self.list_instances()
        ]

    def telemetry(self, connector_id: str | None = None, limit: int = 100) -> ConnectorTelemetryResponse:
        items, total = self.repo.list_telemetry(connector_id=connector_id, limit=min(max(limit, 1), 500))
        return ConnectorTelemetryResponse(items=[_telemetry_to_shape(item) for item in items], total=total)
