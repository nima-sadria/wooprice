"""WooPrice Beta — database session factory (BU2).

Reads BETA_DATABASE_URL from the environment.  Provides BetaBase (the
declarative base shared by all Beta ORM models) and a get_db() FastAPI
dependency that yields a SQLAlchemy Session.

Engine creation is cached per URL string so that the connection pool is
reused across requests.  Tests override get_db via dependency_overrides to
inject an in-memory SQLite session.
"""

from __future__ import annotations

import os
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool


class BetaBase(DeclarativeBase):
    pass


@lru_cache(maxsize=4)
def _get_engine(db_url: str):
    """Return a cached SQLAlchemy engine for the given URL."""
    kwargs: dict = {}
    if db_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs["poolclass"] = NullPool
    return create_engine(db_url, **kwargs)


def get_db():  # type: ignore[return]
    """FastAPI dependency: yield a database session, close on exit."""
    url = os.environ.get("BETA_DATABASE_URL", "")
    if not url:
        raise RuntimeError("BETA_DATABASE_URL is not configured")
    engine = _get_engine(url)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
