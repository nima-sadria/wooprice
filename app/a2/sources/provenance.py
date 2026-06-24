from pydantic import BaseModel


class SourceRowProvenance(BaseModel):
    source_id: str
    source_row_ref: str
    source_snapshot_id: str
    source_row_hash: str

    model_config = {"frozen": True}
