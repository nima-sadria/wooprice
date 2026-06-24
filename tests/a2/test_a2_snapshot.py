"""Unit tests — SourceSnapshot."""
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

from app.a2.sources.snapshot import SourceSnapshot


def _make():
    return SourceSnapshot(
        snapshot_id="snap-001",
        source_id="src-001",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        schema_hash="abc123",
        row_count=10,
        source_fingerprint="fp-xyz",
    )


def test_snapshot_fields():
    s = _make()
    assert s.snapshot_id == "snap-001"
    assert s.source_id == "src-001"
    assert s.row_count == 10
    assert s.schema_hash == "abc123"
    assert s.source_fingerprint == "fp-xyz"


def test_snapshot_immutable():
    s = _make()
    with pytest.raises(Exception):
        s.row_count = 99  # type: ignore[misc]


def test_snapshot_identity_stable():
    s1 = _make()
    s2 = _make()
    assert s1.snapshot_id == s2.snapshot_id
    assert s1 == s2
