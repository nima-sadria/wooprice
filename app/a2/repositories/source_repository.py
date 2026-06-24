from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from ..models.source import SourceDefinition


class SourceRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get(self, source_id: str) -> Optional[SourceDefinition]:
        return self._db.get(SourceDefinition, source_id)

    def list_active(self) -> list[SourceDefinition]:
        return (
            self._db.query(SourceDefinition)
            .filter(SourceDefinition.is_active.is_(True))
            .all()
        )

    def create(
        self,
        *,
        source_id: str,
        source_type: str,
        display_name: str,
        config_json: str = "{}",
    ) -> SourceDefinition:
        now = datetime.now(tz=timezone.utc)
        record = SourceDefinition(
            source_id=source_id,
            source_type=source_type,
            display_name=display_name,
            config_json=config_json,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        self._db.add(record)
        self._db.flush()
        return record

    def deactivate(self, source_id: str) -> bool:
        record = self.get(source_id)
        if record is None:
            return False
        record.is_active = False
        record.updated_at = datetime.now(tz=timezone.utc)
        self._db.flush()
        return True
