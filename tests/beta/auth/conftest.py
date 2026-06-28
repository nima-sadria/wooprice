"""Shared fixtures for BU2 auth tests."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Set env vars BEFORE importing any app.beta modules so the lru_cache in
# database.py picks up the test URL on first call.
os.environ.setdefault("BETA_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("BETA_JWT_SECRET", "test-bu2-jwt-secret-32-bytes-min!")

from app.beta.database import BetaBase, _get_engine  # noqa: E402
from app.beta.auth import models as _models  # noqa: E402, F401  — registers tables

_SQLITE_URL = "sqlite:///:memory:"


@pytest.fixture()
def db_engine():
    """Single shared SQLite in-memory engine for the test.

    StaticPool forces every SQLAlchemy connection to reuse the same underlying
    sqlite3 connection, so tables created in one session are visible to all
    sessions (including the TestClient's dependency-override sessions).
    """
    _get_engine.cache_clear()
    engine = create_engine(
        _SQLITE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    BetaBase.metadata.create_all(engine)
    yield engine
    BetaBase.metadata.drop_all(engine)
    engine.dispose()
    _get_engine.cache_clear()


@pytest.fixture()
def db(db_engine):
    Session = sessionmaker(bind=db_engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def client(db_engine):
    """TestClient wired to the test SQLite DB via dependency override."""
    from fastapi.testclient import TestClient

    from app.beta.app import app
    from app.beta.database import get_db

    Session = sessionmaker(bind=db_engine)

    def _override_get_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def admin_user(db):
    """Pre-created admin user in the test DB."""
    from app.beta.auth.password import hash_password
    from app.beta.auth.repository import create_user

    return create_user(
        db,
        username="testadmin",
        hashed_password=hash_password("correct-horse-battery"),
        role="admin",
    )
