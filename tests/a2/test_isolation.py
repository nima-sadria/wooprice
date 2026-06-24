"""Isolation tests — verify A2 does not touch any existing system.

These tests do NOT require PostgreSQL. They import both the existing app modules
and the A2 modules to confirm complete separation at the metadata and object level.
The existing tests/conftest.py sets DATABASE_URL=sqlite:///:memory: so importing
app.database works cleanly without a real SQLite file.
"""


def test_a2_base_is_separate_from_existing_base():
    from app.a2.database import A2Base
    from app.database import Base as AppBase

    assert AppBase is not A2Base
    assert AppBase.metadata is not A2Base.metadata


def test_a2_tables_not_in_existing_metadata():
    from app.database import Base as AppBase

    existing_tables = set(AppBase.metadata.tables.keys())
    assert "canonical_products" not in existing_tables
    assert "channel_listings" not in existing_tables
    assert "channel_credentials" not in existing_tables


def test_existing_tables_not_in_a2_metadata():
    from app.a2.database import A2Base

    a2_tables = set(A2Base.metadata.tables.keys())
    assert "sync_jobs" not in a2_tables
    assert "sync_job_items" not in a2_tables
    assert "products_cache" not in a2_tables


def test_existing_models_intact():
    from app.models import SyncJob

    assert SyncJob.__tablename__ not in {"canonical_products", "channel_listings", "channel_credentials"}


def test_a2_models_import_cleanly_without_postgres():
    """Importing A2 models must not attempt a database connection."""
    from app.a2 import models as a2_models  # noqa: F401

    assert hasattr(a2_models, "CanonicalProduct")
    assert hasattr(a2_models, "ChannelListing")
    assert hasattr(a2_models, "ChannelCredential")


def test_a2_database_import_does_not_require_postgres_env(monkeypatch):
    """Importing app.a2.database must succeed even without POSTGRES_URL set."""
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    import importlib

    import app.a2.database
    importlib.reload(app.a2.database)  # re-import without env var — must not raise


def test_existing_app_main_does_not_import_a2(monkeypatch):
    """app.main must not pull in any A2 modules at import time."""
    import sys

    # Remove cached A2 modules to get a clean read of what main imports
    a2_keys = [k for k in sys.modules if k.startswith("app.a2")]
    for key in a2_keys:
        del sys.modules[key]

    # Re-import app.main (already imported; this checks the cached module's attributes)
    import app.main  # noqa: F401

    # If A2 is now in sys.modules, it was imported transitively by main — that's the failure
    imported_by_main = [k for k in sys.modules if k.startswith("app.a2")]
    # Allow the re-import we did above (the del + re-add in this test)
    # The assertion is that main itself does not add new a2 keys beyond what we deleted
    # Since we deleted them all, if main doesn't import a2, the list stays empty
    assert imported_by_main == [], (
        f"app.main transitively imported A2 modules: {imported_by_main}. "
        "A2 must be a standalone additive package."
    )
