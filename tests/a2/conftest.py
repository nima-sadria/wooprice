"""A2 test fixtures. PostgreSQL-requiring tests are skipped when PG is not available."""
import os

import pytest
import sqlalchemy
from sqlalchemy import text

from app.a2.database import A2Base, create_a2_engine, create_a2_session_factory

POSTGRES_TEST_URL = os.environ.get(
    "POSTGRES_TEST_URL",
    "postgresql://wooprice:wooprice@localhost:5432/wooprice_a2_test",
)


def _postgres_available() -> bool:
    try:
        engine = sqlalchemy.create_engine(
            POSTGRES_TEST_URL,
            connect_args={"connect_timeout": 3},
        )
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


requires_postgres = pytest.mark.skipif(
    not _postgres_available(),
    reason="PostgreSQL not available (set POSTGRES_TEST_URL to enable)",
)


@pytest.fixture(scope="session")
def pg_engine():
    """Session-scoped engine that creates all A2 tables and drops them on teardown."""
    engine = create_a2_engine(POSTGRES_TEST_URL)
    A2Base.metadata.create_all(engine)
    yield engine
    A2Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def pg_session(pg_engine):
    """Function-scoped session that rolls back after each test."""
    SessionLocal = create_a2_session_factory(pg_engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
