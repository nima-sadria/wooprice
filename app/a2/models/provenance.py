from sqlalchemy import ForeignKey, ForeignKeyConstraint, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..database import A2Base


class SourceRowProvenanceRecord(A2Base):
    __tablename__ = "source_row_provenance"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_id", "source_snapshot_id"],
            ["source_snapshots.source_id", "source_snapshots.snapshot_id"],
            name="fk_provenance_source_snapshot_integrity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("source_definitions.source_id"), nullable=False
    )
    source_row_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    source_snapshot_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_row_hash: Mapped[str] = mapped_column(String(64), nullable=False)
