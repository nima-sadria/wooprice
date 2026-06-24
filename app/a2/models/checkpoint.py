from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from ..database import A2Base


class SourceCheckpointRecord(A2Base):
    __tablename__ = "source_checkpoints"

    source_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("source_definitions.source_id"), primary_key=True
    )
    checkpoint_value: Mapped[str] = mapped_column(String(512), nullable=False)
    checkpointed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    checkpoint_type: Mapped[str] = mapped_column(String(32), nullable=False)
