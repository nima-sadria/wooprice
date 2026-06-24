import re
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, event
from sqlalchemy.orm import Mapped, mapped_column

from ..database import A2Base

_SECRET_KEY_RE = re.compile(r"\b(password|passwd|token|secret|credential|api_key|apikey)\b", re.I)


class SourceDefinition(A2Base):
    __tablename__ = "source_definitions"

    source_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    non_secret_config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


@event.listens_for(SourceDefinition, "before_insert")
@event.listens_for(SourceDefinition, "before_update")
def _reject_secret_keys(mapper, connection, target):
    import json as _json
    raw = target.non_secret_config_json or "{}"
    try:
        data = _json.loads(raw)
    except ValueError:
        return
    for key in data:
        if _SECRET_KEY_RE.search(key):
            raise ValueError(
                f"non_secret_config_json must not contain secret key '{key}'. "
                "Use a secret reference (e.g. secret_ref) instead."
            )
