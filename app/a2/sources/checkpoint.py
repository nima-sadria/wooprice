from datetime import datetime
from typing import Literal

from pydantic import BaseModel

CheckpointType = Literal["etag", "mtime", "fingerprint", "sequence"]


class SourceCheckpoint(BaseModel):
    source_id: str
    checkpoint_value: str
    checkpointed_at: datetime
    checkpoint_type: CheckpointType

    model_config = {"frozen": True}
