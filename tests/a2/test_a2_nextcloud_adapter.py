"""
Integration tests — NextcloudSourceAdapter.

All HTTP calls are mocked; no live Nextcloud instance required.
"""
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

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.a2.sources.adapters.nextcloud import NextcloudSourceAdapter
from tests.a2.helpers import _make_xlsx


def _adapter(**kwargs):
    defaults = dict(
        source_id="test-src",
        url="http://nc.example.invalid",
        username="user",
        password="pass",
        file_path="/prices.xlsx",
    )
    defaults.update(kwargs)
    return NextcloudSourceAdapter(**defaults)


def _mock_response(xlsx_bytes: bytes, etag: str = '"etag-abc"'):
    resp = MagicMock()
    resp.content = xlsx_bytes
    resp.headers = {"etag": etag, "last-modified": "Tue, 24 Jun 2026 00:00:00 GMT"}
    resp.raise_for_status = MagicMock()
    return resp


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


# ── connect() ─────────────────────────────────────────────────────────────────

def test_connect_downloads_file():
    xlsx = _make_xlsx([("Prod A", 101, "50000"), ("Prod B", 102, "80000")])
    adapter = _adapter()
    with patch.object(adapter, "_fetch_file_and_meta", new=AsyncMock(return_value=(xlsx, {"etag": '"e1"'}))):
        _run(adapter.connect())
    assert adapter._xlsx_bytes == xlsx
    assert adapter._meta["etag"] == '"e1"'


# ── validate_source() ─────────────────────────────────────────────────────────

def test_validate_valid_source():
    xlsx = _make_xlsx([("A", 1, "100"), ("B", 2, "200")])
    adapter = _adapter()
    adapter._xlsx_bytes = xlsx
    adapter._meta = {"etag": '"e"'}
    result = _run(adapter.validate_source())
    assert result.is_valid is True
    assert result.errors == []


def test_validate_fails_before_connect():
    adapter = _adapter()
    result = _run(adapter.validate_source())
    assert result.is_valid is False
    assert any("connect()" in e for e in result.errors)


def test_validate_detects_duplicate_ids():
    xlsx = _make_xlsx([("A", 10, "100"), ("B", 10, "200")])
    adapter = _adapter()
    adapter._xlsx_bytes = xlsx
    adapter._meta = {}
    result = _run(adapter.validate_source())
    assert result.is_valid is False
    assert any("10" in e for e in result.errors)


def test_validate_duplicate_is_error_not_warning():
    xlsx = _make_xlsx([("A", 99, "100"), ("B", 99, "200")])
    adapter = _adapter()
    adapter._xlsx_bytes = xlsx
    adapter._meta = {}
    result = _run(adapter.validate_source())
    assert result.is_valid is False
    assert result.warnings == []


def test_validate_missing_product_id_is_error():
    xlsx = _make_xlsx([("A", None, "100"), ("B", 2, "200")])
    adapter = _adapter()
    adapter._xlsx_bytes = xlsx
    adapter._meta = {}
    result = _run(adapter.validate_source())
    assert result.is_valid is False
    assert any("no product identifier" in e.lower() for e in result.errors)


def test_validate_non_integer_id_is_error():
    xlsx = _make_xlsx([("A", "not-an-id", "100")])
    adapter = _adapter()
    adapter._xlsx_bytes = xlsx
    adapter._meta = {}
    result = _run(adapter.validate_source())
    assert result.is_valid is False


# ── fetch_snapshot() ──────────────────────────────────────────────────────────

def test_fetch_snapshot_valid_source():
    xlsx = _make_xlsx([("A", 1, "100"), ("B", 2, "200")])
    adapter = _adapter()
    adapter._xlsx_bytes = xlsx
    adapter._meta = {"etag": '"e"', "last_modified": ""}
    snap = _run(adapter.fetch_snapshot())
    assert snap.source_id == "test-src"
    assert snap.row_count == 2
    assert len(snap.snapshot_id) == 36  # UUID
    assert snap.schema_hash
    assert snap.source_fingerprint


def test_fetch_snapshot_raises_on_invalid_source():
    xlsx = _make_xlsx([("A", 5, "100"), ("B", 5, "200")])  # duplicate
    adapter = _adapter()
    adapter._xlsx_bytes = xlsx
    adapter._meta = {}
    with pytest.raises(ValueError, match="validation error"):
        _run(adapter.fetch_snapshot())


def test_fetch_snapshot_raises_before_connect():
    adapter = _adapter()
    with pytest.raises(RuntimeError, match="connect()"):
        _run(adapter.fetch_snapshot())


def test_snapshot_ids_are_unique():
    xlsx = _make_xlsx([("A", 1, "100")])
    adapter = _adapter()
    adapter._xlsx_bytes = xlsx
    adapter._meta = {"etag": '"e"', "last_modified": ""}
    s1 = _run(adapter.fetch_snapshot())
    s2 = _run(adapter.fetch_snapshot())
    assert s1.snapshot_id != s2.snapshot_id


# ── stream_rows (via _stream_rows_impl) ───────────────────────────────────────

async def _collect_rows(adapter, snapshot_id):
    rows = []
    async for row in adapter._stream_rows_impl(snapshot_id):
        rows.append(row)
    return rows


def test_stream_rows_yields_correct_count():
    xlsx = _make_xlsx([("A", 10, "100"), ("B", 20, "200"), ("C", 30, "300")])
    adapter = _adapter()
    adapter._xlsx_bytes = xlsx
    adapter._meta = {}
    rows = asyncio.run(_collect_rows(adapter, "snap-001"))
    assert len(rows) == 3


def test_stream_rows_stable_row_ref():
    xlsx = _make_xlsx([("A", 42, "100")])
    adapter = _adapter()
    adapter._xlsx_bytes = xlsx
    adapter._meta = {}
    rows = asyncio.run(_collect_rows(adapter, "snap-001"))
    assert rows[0].row_ref == "42"


def test_stream_rows_provenance_attached():
    xlsx = _make_xlsx([("A", 42, "100")])
    adapter = _adapter()
    adapter._xlsx_bytes = xlsx
    adapter._meta = {}
    rows = asyncio.run(_collect_rows(adapter, "snap-XYZ"))
    row = rows[0]
    assert row.provenance.source_id == "test-src"
    assert row.provenance.source_row_ref == "42"
    assert row.provenance.source_snapshot_id == "snap-XYZ"
    assert len(row.provenance.source_row_hash) == 64


def test_stream_rows_hash_stable():
    xlsx = _make_xlsx([("A", 42, "100")])
    adapter = _adapter()
    adapter._xlsx_bytes = xlsx
    adapter._meta = {}
    r1 = asyncio.run(_collect_rows(adapter, "snap-001"))
    r2 = asyncio.run(_collect_rows(adapter, "snap-001"))
    assert r1[0].row_hash == r2[0].row_hash


def test_stream_rows_raises_before_connect():
    adapter = _adapter()

    async def _try():
        rows = []
        async for row in adapter._stream_rows_impl("snap-001"):
            rows.append(row)
        return rows

    with pytest.raises(RuntimeError, match="connect()"):
        asyncio.run(_try())


def test_stream_rows_raises_on_duplicate_ids():
    xlsx = _make_xlsx([("A", 7, "100"), ("B", 7, "200")])
    adapter = _adapter()
    adapter._xlsx_bytes = xlsx
    adapter._meta = {}

    async def _try():
        rows = []
        async for row in adapter._stream_rows_impl("snap-001"):
            rows.append(row)
        return rows

    with pytest.raises(ValueError, match="invalid source"):
        asyncio.run(_try())


# ── get_capabilities() ────────────────────────────────────────────────────────

def test_capabilities():
    adapter = _adapter()
    caps = adapter.get_capabilities()
    assert caps.supports_streaming is True
    assert caps.supports_snapshots is True
    assert caps.supports_checkpointing is True
    assert caps.supports_incremental_sync is False
    assert caps.supports_deletions is False


# ── get_checkpoint() ──────────────────────────────────────────────────────────

def test_get_checkpoint_returns_etag():
    adapter = _adapter()
    adapter._xlsx_bytes = b"x"
    adapter._meta = {"etag": '"my-etag"', "last_modified": ""}
    cp = _run(adapter.get_checkpoint())
    assert cp is not None
    assert cp.checkpoint_value == '"my-etag"'
    assert cp.checkpoint_type == "etag"
    assert cp.source_id == "test-src"


def test_get_checkpoint_returns_none_when_no_etag():
    adapter = _adapter()
    adapter._xlsx_bytes = b"x"
    adapter._meta = {"etag": "", "last_modified": ""}
    with patch.object(adapter, "_fetch_meta_only", new=AsyncMock(return_value={"etag": "", "last_modified": ""})):
        cp = _run(adapter.get_checkpoint())
    assert cp is None


# ── advance_checkpoint() ──────────────────────────────────────────────────────

def test_advance_checkpoint_accepted():
    from datetime import datetime, timezone
    from app.a2.sources.checkpoint import SourceCheckpoint
    adapter = _adapter()
    cp = SourceCheckpoint(
        source_id="test-src",
        checkpoint_value='"new-etag"',
        checkpointed_at=datetime.now(tz=timezone.utc),
        checkpoint_type="etag",
    )
    _run(adapter.advance_checkpoint(cp))


# ── SOURCE_TYPE constant ──────────────────────────────────────────────────────

def test_source_type_constant():
    assert NextcloudSourceAdapter.SOURCE_TYPE == "nextcloud_xlsx"
