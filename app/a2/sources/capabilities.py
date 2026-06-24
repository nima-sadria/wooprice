from pydantic import BaseModel


class SourceCapabilities(BaseModel):
    supports_streaming: bool = False
    supports_checkpointing: bool = False
    supports_deletions: bool = False
    supports_incremental_sync: bool = False
    supports_snapshots: bool = False
