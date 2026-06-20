import sys
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from .config import get_settings

# The exact URL produced by _default_database_url() on Windows.
_WIN_LOCAL_URL = "sqlite:///./data/wooprice-local.db"


def _ensure_local_db_dir(db_url: str) -> None:
    """Create data/ only for the Windows local-dev fallback URL.

    All other URLs — Docker absolute paths, Linux defaults, :memory: — must
    not trigger automatic directory creation; those environments either manage
    their own directories or should fail fast if misconfigured.
    """
    if sys.platform == "win32" and db_url == _WIN_LOCAL_URL:
        Path("./data").mkdir(parents=True, exist_ok=True)


_db_url = get_settings().database_url
_ensure_local_db_dir(_db_url)

engine = create_engine(
    _db_url,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
