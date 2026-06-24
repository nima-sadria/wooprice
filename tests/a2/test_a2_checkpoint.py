"""Unit tests — SourceCheckpoint."""
import os
os.environ.setdefault("A2_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("NEXTCLOUD_URL", "http://example.invalid")
os.environ.setdefault("NEXTCLOUD_USER", "x")
os.environ.setdefault("NEXTCLOUD_PASSWORD", "x")
os.environ.setdefault("NEXTCLOUD_FILE_PATH", "/x.xlsx")
os.environ.setdefault("WC_URL", "http://example.invalid")
os.environ.setdefault("WC_KEY", "x")
os.environ.setdefault("WC_SECRET", "x")

from datetime import datetime, timezone

import pytest

from app.a2.sources.checkpoint import SourceCheckpoint


def _make(checkpoint_type="etag"):
    return SourceCheckpoint(
        source_id="src-001",
        checkpoint_value='"abc123etag"',
        checkpointed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        checkpoint_type=checkpoint_type,
    )


def test_checkpoint_fields():
    c = _make()
    assert c.source_id == "src-001"
    assert c.checkpoint_value == '"abc123etag"'
    assert c.checkpoint_type == "etag"


def test_checkpoint_immutable():
    c = _make()
    with pytest.raises(Exception):
        c.checkpoint_value = "changed"  # type: ignore[misc]


def test_valid_checkpoint_types():
    for ct in ("etag", "mtime", "fingerprint", "sequence"):
        c = _make(checkpoint_type=ct)
        assert c.checkpoint_type == ct


def test_invalid_checkpoint_type_rejected():
    with pytest.raises(Exception):
        SourceCheckpoint(
            source_id="x",
            checkpoint_value="v",
            checkpointed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            checkpoint_type="invalid_type",  # type: ignore[arg-type]
        )
