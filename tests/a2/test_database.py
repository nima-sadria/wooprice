"""Tests for app/a2/database.py.

PostgreSQL-requiring tests are skipped when PG is not available.
The POSTGRES_URL error test runs without PG.
"""
import os

import pytest
from sqlalchemy import text

from app.a2.database import A2Base, create_a2_engine, get_postgres_url
from tests.a2.conftest import POSTGRES_TEST_URL, requires_postgres


def test_get_postgres_url_raises_when_env_not_set(monkeypatch):
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    with pytest.raises(RuntimeError, match="POSTGRES_URL"):
        get_postgres_url()


@requires_postgres
def test_create_a2_engine_connects():
    engine = create_a2_engine(POSTGRES_TEST_URL)
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        assert result.scalar() == 1
    engine.dispose()


@requires_postgres
def test_a2_base_metadata_has_expected_tables():
    table_names = set(A2Base.metadata.tables.keys())
    assert "canonical_products" in table_names
    assert "channel_listings" in table_names
    assert "channel_credentials" in table_names


@requires_postgres
def test_tables_exist_after_create_all(pg_engine):
    from sqlalchemy import inspect
    inspector = inspect(pg_engine)
    existing = set(inspector.get_table_names())
    assert "canonical_products" in existing
    assert "channel_listings" in existing
    assert "channel_credentials" in existing


@requires_postgres
def test_tables_gone_after_drop_all():
    """Verify create_all / drop_all round-trip works (uses a separate engine to avoid
    interfering with the session-scoped pg_engine fixture)."""
    engine = create_a2_engine(POSTGRES_TEST_URL)
    A2Base.metadata.create_all(engine)

    from sqlalchemy import inspect
    assert "canonical_products" in set(inspect(engine).get_table_names())

    A2Base.metadata.drop_all(engine)
    assert "canonical_products" not in set(inspect(engine).get_table_names())

    # Restore for other tests in this session
    A2Base.metadata.create_all(engine)
    engine.dispose()
