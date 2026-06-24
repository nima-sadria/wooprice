from datetime import timezone
from typing import Optional

from sqlalchemy.orm import Session

from ..models.checkpoint import SourceCheckpointRecord
from ..sources.checkpoint import SourceCheckpoint


class CheckpointRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get(self, source_id: str) -> Optional[SourceCheckpoint]:
        record = self._db.get(SourceCheckpointRecord, source_id)
        if record is None:
            return None
        checkpointed_at = record.checkpointed_at
        if checkpointed_at.tzinfo is None:
            checkpointed_at = checkpointed_at.replace(tzinfo=timezone.utc)
        return SourceCheckpoint(
            source_id=record.source_id,
            checkpoint_value=record.checkpoint_value,
            checkpointed_at=checkpointed_at,
            checkpoint_type=record.checkpoint_type,  # type: ignore[arg-type]
        )

    def save(self, checkpoint: SourceCheckpoint) -> SourceCheckpointRecord:
        record = self._db.get(SourceCheckpointRecord, checkpoint.source_id)
        if record is None:
            record = SourceCheckpointRecord(source_id=checkpoint.source_id)
            self._db.add(record)
        record.checkpoint_value = checkpoint.checkpoint_value
        record.checkpointed_at = checkpoint.checkpointed_at
        record.checkpoint_type = checkpoint.checkpoint_type
        self._db.flush()
        return record

    def delete(self, source_id: str) -> bool:
        record = self._db.get(SourceCheckpointRecord, source_id)
        if record is None:
            return False
        self._db.delete(record)
        self._db.flush()
        return True
