from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from .config import get_settings

_db_url = get_settings().database_url

# For relative-path SQLite URLs (3-slash form, not 4-slash absolute), ensure the
# parent directory exists before SQLAlchemy tries to open the file.  This lets a
# clean Windows clone start without DATABASE_URL or a manual `mkdir data`.
# 4-slash URLs (sqlite:////app/…) are absolute paths; Docker creates those dirs
# via `RUN mkdir -p /app/data`, so we skip them here.
if _db_url.startswith("sqlite:///") and not _db_url.startswith("sqlite:////"):
    _db_rel = _db_url.removeprefix("sqlite:///")
    if _db_rel not in (":memory:", ""):
        Path(_db_rel).parent.mkdir(parents=True, exist_ok=True)

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
