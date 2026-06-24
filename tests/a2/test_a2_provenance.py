"""Unit tests — SourceRowProvenance."""
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

import pytest

from app.a2.sources.provenance import SourceRowProvenance


def _make():
    return SourceRowProvenance(
        source_id="src-001",
        source_row_ref="12345",
        source_snapshot_id="snap-001",
        source_row_hash="deadbeef",
    )


def test_provenance_fields():
    p = _make()
    assert p.source_id == "src-001"
    assert p.source_row_ref == "12345"
    assert p.source_snapshot_id == "snap-001"
    assert p.source_row_hash == "deadbeef"


def test_provenance_immutable():
    p = _make()
    with pytest.raises(Exception):
        p.source_row_hash = "changed"  # type: ignore[misc]


def test_provenance_equality():
    assert _make() == _make()
