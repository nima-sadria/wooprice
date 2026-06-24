"""
Database tests — A2.2 migration and repository persistence.

All tests use an in-memory SQLite database; no PostgreSQL required.
Real Alembic upgrade/downgrade tests use a file-based SQLite (tmp_path fixture).
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

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.a2.database import A2Base
import app.a2.models.canonical_product  # noqa: F401 — registers with A2Base
from app.a2.models.checkpoint import SourceCheckpointRecord  # noqa: F401
from app.a2.models.provenance import SourceRowProvenanceRecord  # noqa: F401
from app.a2.models.snapshot import SourceSnapshotRecord  # noqa: F401
from app.a2.models.source import SourceDefinition  # noqa: F401
from app.a2.repositories.checkpoint_repository import CheckpointRepository
from app.a2.repositories.snapshot_repository import SnapshotRepository
from app.a2.repositories.source_repository import SourceRepository
from app.a2.sources.checkpoint import SourceCheckpoint
from app.a2.sources.provenance import SourceRowProvenance
from app.a2.sources.snapshot import SourceSnapshot


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def engine():
    """Fresh in-memory SQLite engine with A2 schema applied via SQLAlchemy metadata."""
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    A2Base.metadata.create_all(eng)
    yield eng
    A2Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture()
def db(engine):
    """Session bound to the fixture engine."""
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def source_repo(db):
    return SourceRepository(db)


@pytest.fixture()
def snapshot_repo(db):
    return SnapshotRepository(db)


@pytest.fixture()
def checkpoint_repo(db):
    return CheckpointRepository(db)


@pytest.fixture()
def seeded_source(source_repo, db):
    """Create and commit a SourceDefinition for use in dependent tests."""
    record = source_repo.create(
        source_id="src-test",
        source_type="nextcloud_xlsx",
        display_name="Test Source",
    )
    db.commit()
    return record


# ── Alembic real migration tests (HIGH 2) ─────────────────────────────────────

def test_alembic_upgrade_creates_all_expected_tables(tmp_path):
    """
    Real Alembic `upgrade head` must create all tables from both a2_000 and a2_001.
    This tests the actual migration path, not just SQLAlchemy metadata.
    """
    db_url = "sqlite:///" + str(tmp_path / "a2_upgrade_test.db").replace("\\", "/")
    with patch.dict(os.environ, {"A2_DATABASE_URL": db_url}):
        cfg = Config("alembic_a2.ini")
        cfg.set_main_option("sqlalchemy.url", db_url)
        command.upgrade(cfg, "head")

    eng = create_engine(db_url)
    tables = set(inspect(eng).get_table_names())
    eng.dispose()

    # a2_000: canonical product foundation
    assert "canonical_products" in tables
    assert "channel_listings" in tables
    assert "channel_credentials" in tables
    # a2_001: source adapter framework
    assert "source_definitions" in tables
    assert "source_snapshots" in tables
    assert "source_row_provenance" in tables
    assert "source_checkpoints" in tables


def test_alembic_downgrade_removes_all_tables(tmp_path):
    """
    Real Alembic `downgrade base` must remove all A2 tables after `upgrade head`.
    """
    db_url = "sqlite:///" + str(tmp_path / "a2_downgrade_test.db").replace("\\", "/")
    with patch.dict(os.environ, {"A2_DATABASE_URL": db_url}):
        cfg = Config("alembic_a2.ini")
        cfg.set_main_option("sqlalchemy.url", db_url)
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")

    eng = create_engine(db_url)
    tables = set(inspect(eng).get_table_names())
    eng.dispose()

    assert "canonical_products" not in tables
    assert "source_definitions" not in tables
    assert "source_snapshots" not in tables
    assert "source_row_provenance" not in tables
    assert "source_checkpoints" not in tables


def test_alembic_migration_lineage_is_chained(tmp_path):
    """
    a2_001 must depend on a2_000 (not be a root revision).
    Upgrading to a2_000 only must not create source_definitions.
    """
    db_url = "sqlite:///" + str(tmp_path / "a2_lineage_test.db").replace("\\", "/")
    with patch.dict(os.environ, {"A2_DATABASE_URL": db_url}):
        cfg = Config("alembic_a2.ini")
        cfg.set_main_option("sqlalchemy.url", db_url)
        command.upgrade(cfg, "a2_000")

    eng = create_engine(db_url)
    tables = set(inspect(eng).get_table_names())
    eng.dispose()

    assert "canonical_products" in tables
    assert "source_definitions" not in tables  # belongs to a2_001, not yet applied


# ── SQLAlchemy metadata smoke tests ──────────────────────────────────────────

def test_metadata_create_all_creates_tables():
    """A2Base.metadata.create_all must create all registered tables."""
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    A2Base.metadata.create_all(eng)
    inspector = inspect(eng)
    tables = set(inspector.get_table_names())
    assert "source_definitions" in tables
    assert "source_snapshots" in tables
    assert "source_row_provenance" in tables
    assert "source_checkpoints" in tables
    assert "canonical_products" in tables
    eng.dispose()


def test_metadata_drop_all_removes_tables():
    """drop_all must remove all A2 tables."""
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    A2Base.metadata.create_all(eng)
    A2Base.metadata.drop_all(eng)
    inspector = inspect(eng)
    tables = inspector.get_table_names()
    assert "source_definitions" not in tables
    assert "source_snapshots" not in tables
    assert "source_row_provenance" not in tables
    assert "source_checkpoints" not in tables
    eng.dispose()


def test_source_definitions_has_expected_columns():
    """source_definitions table must use non_secret_config_json (not config_json)."""
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    A2Base.metadata.create_all(eng)
    inspector = inspect(eng)
    cols = {c["name"] for c in inspector.get_columns("source_definitions")}
    assert {"source_id", "source_type", "display_name", "non_secret_config_json",
            "is_active", "created_at", "updated_at"} <= cols
    assert "config_json" not in cols  # old name must not exist
    eng.dispose()


# ── SourceRepository persistence tests ────────────────────────────────────────

def test_source_create_and_get(source_repo, db):
    record = source_repo.create(
        source_id="src-001",
        source_type="nextcloud_xlsx",
        display_name="My Source",
        non_secret_config_json='{"url": "http://nc.example"}',
    )
    db.commit()
    fetched = source_repo.get("src-001")
    assert fetched is not None
    assert fetched.source_type == "nextcloud_xlsx"
    assert fetched.display_name == "My Source"
    assert fetched.is_active is True


def test_source_get_missing_returns_none(source_repo):
    assert source_repo.get("nonexistent") is None


def test_source_list_active(source_repo, db):
    source_repo.create(source_id="s1", source_type="nextcloud_xlsx", display_name="S1")
    source_repo.create(source_id="s2", source_type="nextcloud_xlsx", display_name="S2")
    db.commit()
    source_repo.deactivate("s2")
    db.commit()
    active = source_repo.list_active()
    ids = [r.source_id for r in active]
    assert "s1" in ids
    assert "s2" not in ids


def test_source_deactivate(source_repo, db):
    source_repo.create(source_id="src-x", source_type="nextcloud_xlsx", display_name="X")
    db.commit()
    result = source_repo.deactivate("src-x")
    db.commit()
    assert result is True
    record = source_repo.get("src-x")
    assert record.is_active is False


def test_source_deactivate_missing_returns_false(source_repo):
    assert source_repo.deactivate("does-not-exist") is False


# ── SnapshotRepository persistence tests ──────────────────────────────────────

def test_snapshot_save_and_get(snapshot_repo, seeded_source, db):
    snap = SourceSnapshot(
        snapshot_id="snap-001",
        source_id="src-test",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        schema_hash="abc123",
        row_count=5,
        source_fingerprint="fp-xyz",
    )
    snapshot_repo.save_snapshot(snap)
    db.commit()
    fetched = snapshot_repo.get_snapshot("snap-001")
    assert fetched is not None
    assert fetched.snapshot_id == "snap-001"
    assert fetched.row_count == 5
    assert fetched.schema_hash == "abc123"


def test_snapshot_get_missing_returns_none(snapshot_repo):
    assert snapshot_repo.get_snapshot("nonexistent") is None


def test_snapshot_list_by_source(snapshot_repo, seeded_source, db):
    for i in range(3):
        snap = SourceSnapshot(
            snapshot_id=f"snap-{i:03d}",
            source_id="src-test",
            created_at=datetime(2026, 1, i + 1, tzinfo=timezone.utc),
            schema_hash="h",
            row_count=i,
            source_fingerprint="fp",
        )
        snapshot_repo.save_snapshot(snap)
    db.commit()
    snaps = snapshot_repo.list_snapshots("src-test")
    assert len(snaps) == 3


def test_provenance_save_and_list(snapshot_repo, seeded_source, db):
    snap = SourceSnapshot(
        snapshot_id="snap-prov",
        source_id="src-test",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        schema_hash="h",
        row_count=1,
        source_fingerprint="fp",
    )
    snapshot_repo.save_snapshot(snap)
    db.commit()

    prov = SourceRowProvenance(
        source_id="src-test",
        source_row_ref="42",
        source_snapshot_id="snap-prov",
        source_row_hash="deadbeef" * 8,
    )
    snapshot_repo.save_provenance(prov)
    db.commit()

    records = snapshot_repo.list_provenance("snap-prov")
    assert len(records) == 1
    assert records[0].source_row_ref == "42"


def test_provenance_list_empty_for_unknown_snapshot(snapshot_repo):
    assert snapshot_repo.list_provenance("nonexistent") == []


# ── CheckpointRepository persistence tests ────────────────────────────────────

def test_checkpoint_save_and_get(checkpoint_repo, seeded_source, db):
    cp = SourceCheckpoint(
        source_id="src-test",
        checkpoint_value='"etag-abc"',
        checkpointed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        checkpoint_type="etag",
    )
    checkpoint_repo.save(cp)
    db.commit()

    fetched = checkpoint_repo.get("src-test")
    assert fetched is not None
    assert fetched.checkpoint_value == '"etag-abc"'
    assert fetched.checkpoint_type == "etag"
    assert fetched.source_id == "src-test"


def test_checkpoint_get_missing_returns_none(checkpoint_repo):
    assert checkpoint_repo.get("nonexistent") is None


def test_checkpoint_upsert(checkpoint_repo, seeded_source, db):
    """Saving a second checkpoint for the same source_id updates, not inserts."""
    cp1 = SourceCheckpoint(
        source_id="src-test",
        checkpoint_value='"etag-v1"',
        checkpointed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        checkpoint_type="etag",
    )
    checkpoint_repo.save(cp1)
    db.commit()

    cp2 = SourceCheckpoint(
        source_id="src-test",
        checkpoint_value='"etag-v2"',
        checkpointed_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        checkpoint_type="etag",
    )
    checkpoint_repo.save(cp2)
    db.commit()

    fetched = checkpoint_repo.get("src-test")
    assert fetched.checkpoint_value == '"etag-v2"'


def test_checkpoint_delete(checkpoint_repo, seeded_source, db):
    cp = SourceCheckpoint(
        source_id="src-test",
        checkpoint_value='"etag-del"',
        checkpointed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        checkpoint_type="etag",
    )
    checkpoint_repo.save(cp)
    db.commit()

    result = checkpoint_repo.delete("src-test")
    db.commit()
    assert result is True
    assert checkpoint_repo.get("src-test") is None


def test_checkpoint_delete_missing_returns_false(checkpoint_repo):
    assert checkpoint_repo.delete("nonexistent") is False
