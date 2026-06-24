from datetime import datetime

from pydantic import BaseModel


class SourceSnapshot(BaseModel):
    snapshot_id: str
    source_id: str
    created_at: datetime
    schema_hash: str
    row_count: int
    source_fingerprint: str

    model_config = {"frozen": True}
