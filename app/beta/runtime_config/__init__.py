"""WooPrice Beta — Runtime Configuration package (CP1.3).

RuntimeConfigService is the write path for editable non-secret fields.
Separate from B3 ConfigurationManager (read-only immutable schema).
"""

from .record import (
    EDITABLE_FIELDS,
    INSTALLER_ONLY_FIELDS,
    SECRET_RUNTIME_FIELDS,
    ConfigChangeEvent,
    ConfigRecord,
)
from .service import RuntimeConfigService, SetResult, ValidationResult

__all__ = [
    "EDITABLE_FIELDS",
    "INSTALLER_ONLY_FIELDS",
    "SECRET_RUNTIME_FIELDS",
    "ConfigChangeEvent",
    "ConfigRecord",
    "RuntimeConfigService",
    "SetResult",
    "ValidationResult",
]
