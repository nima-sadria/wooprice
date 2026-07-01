"""Persistence helpers for Integration Platform connector instances."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy.orm import Session

from app.beta.integrations.contracts import ConnectorSettingValue
from app.beta.integrations.models import (
    ConnectorInstance,
    ConnectorProductRecord,
    ConnectorSetting,
    ConnectorSourceRecord,
    ConnectorTelemetryEvent,
)

_UTC = timezone.utc


def _utcnow() -> datetime:
    return datetime.now(_UTC).replace(tzinfo=None)


class ConnectorRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_instances(self) -> list[ConnectorInstance]:
        return (
            self.db.query(ConnectorInstance)
            .order_by(ConnectorInstance.connector_type.asc(), ConnectorInstance.name.asc())
            .all()
        )

    def get_instance(self, connector_id: str) -> ConnectorInstance | None:
        return self.db.get(ConnectorInstance, connector_id)

    def add_instance(self, instance: ConnectorInstance) -> ConnectorInstance:
        self.db.add(instance)
        self.db.commit()
        self.db.refresh(instance)
        return instance

    def add_source_for_instance(self, instance: ConnectorInstance) -> ConnectorSourceRecord:
        existing = (
            self.db.query(ConnectorSourceRecord)
            .filter(ConnectorSourceRecord.connector_id == instance.id)
            .first()
        )
        if existing is not None:
            return existing
        source = ConnectorSourceRecord(
            connector_id=instance.id,
            name=instance.name,
            source_type=instance.connector_type,
            status=instance.status,
            product_count=0,
        )
        self.db.add(source)
        self.db.commit()
        self.db.refresh(source)
        return source

    def upsert_settings(
        self,
        connector: ConnectorInstance,
        settings: Iterable[ConnectorSettingValue],
    ) -> ConnectorInstance:
        existing = {s.key: s for s in connector.settings}
        now = _utcnow()
        for item in settings:
            row = existing.get(item.key)
            stored_value = None if item.secret else item.value
            configured = item.configured or item.value not in (None, "")
            if row is None:
                row = ConnectorSetting(
                    connector_id=connector.id,
                    key=item.key,
                    value_json=stored_value,
                    secret=item.secret,
                    configured=configured,
                    updated_at=now,
                )
                self.db.add(row)
            else:
                row.value_json = stored_value
                row.secret = item.secret
                row.configured = configured
                row.updated_at = now
        connector.updated_at = now
        self.db.commit()
        self.db.refresh(connector)
        return connector

    def list_sources(self) -> list[ConnectorSourceRecord]:
        return (
            self.db.query(ConnectorSourceRecord)
            .order_by(ConnectorSourceRecord.name.asc())
            .all()
        )

    def list_products(
        self,
        search: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[ConnectorProductRecord], int]:
        query = self.db.query(ConnectorProductRecord)
        if search:
            pattern = f"%{search}%"
            query = query.filter(
                (ConnectorProductRecord.name.ilike(pattern))
                | (ConnectorProductRecord.sku.ilike(pattern))
                | (ConnectorProductRecord.external_id.ilike(pattern))
            )
        total = query.count()
        items = (
            query.order_by(ConnectorProductRecord.name.asc(), ConnectorProductRecord.id.asc())
            .offset(max(page - 1, 0) * page_size)
            .limit(page_size)
            .all()
        )
        return items, total

    def count_products(self) -> int:
        return self.db.query(ConnectorProductRecord).count()

    def record_telemetry(
        self,
        connector_id: str,
        event_name: str,
        message: str,
        severity: str = "info",
        metadata: dict | None = None,
    ) -> ConnectorTelemetryEvent:
        event = ConnectorTelemetryEvent(
            connector_id=connector_id,
            event_name=event_name,
            severity=severity,
            message=message,
            metadata_json=metadata or {},
        )
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)
        return event

    def list_telemetry(self, connector_id: str | None = None, limit: int = 100) -> tuple[list[ConnectorTelemetryEvent], int]:
        query = self.db.query(ConnectorTelemetryEvent)
        if connector_id:
            query = query.filter(ConnectorTelemetryEvent.connector_id == connector_id)
        total = query.count()
        items = (
            query.order_by(ConnectorTelemetryEvent.created_at.desc(), ConnectorTelemetryEvent.id.desc())
            .limit(limit)
            .all()
        )
        return items, total
