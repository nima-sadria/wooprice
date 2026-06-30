"""Persistence helpers for Integration Platform connector instances."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy.orm import Session

from app.beta.integrations.contracts import ConnectorSettingValue
from app.beta.integrations.models import ConnectorInstance, ConnectorSetting

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
