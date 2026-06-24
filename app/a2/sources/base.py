from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Optional

from .capabilities import SourceCapabilities
from .checkpoint import SourceCheckpoint
from .provenance import SourceRowProvenance
from .snapshot import SourceSnapshot


@dataclass
class SourceRow:
    row_ref: str
    raw_data: dict[str, Any]
    row_hash: str
    provenance: SourceRowProvenance


@dataclass
class SourceValidationResult:
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def hash_row(raw_data: dict[str, Any]) -> str:
    """Deterministic SHA-256 hash of a row's raw data."""
    serialized = json.dumps(raw_data, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()


class SourceAdapter(ABC):
    """
    Abstract base for all A2 source adapters.

    Implementations must be source-agnostic at the interface boundary:
    compatible with spreadsheet, database, and API sources.

    Adapter responsibility ends at: Source → Validation → Snapshot → Provenance → Row Streaming.
    Nothing beyond that boundary belongs in A2.2.
    """

    @abstractmethod
    async def connect(self) -> None:
        """Establish a connection to the source system."""
        ...

    @abstractmethod
    async def validate_source(self) -> SourceValidationResult:
        """
        Validate that the source is reachable, readable, and structurally sound.

        Duplicate row identifiers MUST be reported as validation errors, not warnings.
        Rows without a stable identifier MUST be reported as validation errors.
        """
        ...

    @abstractmethod
    async def fetch_snapshot(self) -> SourceSnapshot:
        """
        Generate an immutable snapshot descriptor for the current source state.

        The snapshot captures structural metadata (schema_hash, row_count,
        source_fingerprint) suitable for future reconciliation and Change Set
        generation in A2.5.  The snapshot does NOT contain row data.
        """
        ...

    @abstractmethod
    def stream_rows(self) -> AsyncIterator[SourceRow]:
        """
        Yield rows one at a time from the source.

        Each row carries a stable row_ref, raw_data, row_hash, and provenance.
        Row position MUST NOT be used as an identifier.
        """
        ...

    @abstractmethod
    def get_capabilities(self) -> SourceCapabilities:
        """Return the capability declaration for this adapter type."""
        ...

    @abstractmethod
    async def get_checkpoint(self) -> Optional[SourceCheckpoint]:
        """
        Return the current checkpoint marker for incremental sync support,
        or None if no checkpoint is available.
        """
        ...

    @abstractmethod
    async def advance_checkpoint(self, checkpoint: SourceCheckpoint) -> None:
        """Persist an updated checkpoint after a successful sync."""
        ...
