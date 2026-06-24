"""A2 platform database setup — PostgreSQL only, completely separate from app/database.py."""
import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class A2Base(DeclarativeBase):
    pass


def get_postgres_url() -> str:
    """Read POSTGRES_URL from environment. Raises RuntimeError if not set."""
    url = os.environ.get("POSTGRES_URL")
    if not url:
        raise RuntimeError(
            "POSTGRES_URL is required for A2 platform features. "
            "Example: postgresql://wooprice:password@localhost:5432/wooprice_a2"
        )
    return url


def create_a2_engine(url: str | None = None):
    """Create a PostgreSQL engine. Uses POSTGRES_URL env var if url is not provided."""
    return create_engine(url or get_postgres_url(), pool_pre_ping=True)


def create_a2_session_factory(engine):
    """Return a session factory bound to the given engine."""
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_a2_db(engine):
    """FastAPI dependency that yields an A2 database session."""
    SessionLocal = create_a2_session_factory(engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
