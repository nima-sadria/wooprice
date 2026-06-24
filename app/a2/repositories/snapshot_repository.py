from typing import Optional

from sqlalchemy.orm import Session

from ..models.provenance import SourceRowProvenanceRecord
from ..models.snapshot import SourceSnapshotRecord
from ..sources.provenance import SourceRowProvenance
from ..sources.snapshot import SourceSnapshot


class SnapshotRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def save_snapshot(self, snapshot: SourceSnapshot) -> SourceSnapshotRecord:
        record = SourceSnapshotRecord(
            snapshot_id=snapshot.snapshot_id,
            source_id=snapshot.source_id,
            created_at=snapshot.created_at,
            schema_hash=snapshot.schema_hash,
            row_count=snapshot.row_count,
            source_fingerprint=snapshot.source_fingerprint,
        )
        self._db.add(record)
        self._db.flush()
        return record

    def get_snapshot(self, snapshot_id: str) -> Optional[SourceSnapshotRecord]:
        return self._db.get(SourceSnapshotRecord, snapshot_id)

    def list_snapshots(self, source_id: str) -> list[SourceSnapshotRecord]:
        return (
            self._db.query(SourceSnapshotRecord)
            .filter(SourceSnapshotRecord.source_id == source_id)
            .order_by(SourceSnapshotRecord.created_at.desc())
            .all()
        )

    def save_provenance(
        self, provenance: SourceRowProvenance
    ) -> SourceRowProvenanceRecord:
        record = SourceRowProvenanceRecord(
            source_id=provenance.source_id,
            source_row_ref=provenance.source_row_ref,
            source_snapshot_id=provenance.source_snapshot_id,
            source_row_hash=provenance.source_row_hash,
        )
        self._db.add(record)
        self._db.flush()
        return record

    def list_provenance(self, snapshot_id: str) -> list[SourceRowProvenanceRecord]:
        return (
            self._db.query(SourceRowProvenanceRecord)
            .filter(SourceRowProvenanceRecord.source_snapshot_id == snapshot_id)
            .all()
        )
