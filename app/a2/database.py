"""
A2 database layer — completely isolated from the production SQLite stack.

Uses A2_DATABASE_URL environment variable.  Defaults to sqlite:///:memory:
so unit tests run without a PostgreSQL instance.
"""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool


def _a2_database_url() -> str:
    return os.environ.get("A2_DATABASE_URL", "sqlite:///:memory:")


def _make_engine(url: str):
    is_memory = ":memory:" in url
    kwargs: dict = {}
    if "sqlite" in url:
        kwargs["connect_args"] = {"check_same_thread": False}
    if is_memory:
        kwargs["poolclass"] = StaticPool
    return create_engine(url, **kwargs)


_url = _a2_database_url()
a2_engine = _make_engine(_url)
A2SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=a2_engine)


class A2Base(DeclarativeBase):
    pass


def get_a2_db():
    db = A2SessionLocal()
    try:
        yield db
    finally:
        db.close()
