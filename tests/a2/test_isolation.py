"""Isolation tests — verify A2 does not touch any existing system.

These tests do NOT require PostgreSQL. They import both the existing app modules
and the A2 modules to confirm complete separation at the metadata and object level.
The existing tests/conftest.py sets DATABASE_URL=sqlite:///:memory: so importing
app.database works cleanly without a real SQLite file.

The subprocess test (test_app_main_does_not_import_a2_subprocess) runs a fresh Python
interpreter to rule out sys.modules cache pollution from the test process itself.
"""
import json
import os
import subprocess
import sys
from pathlib import Path


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


def test_app_main_does_not_import_a2_subprocess():
    """Verify via a fresh Python process that importing app.main does not pull in app.a2.

    Uses subprocess so the check is immune to sys.modules pollution from the test runner
    itself (which may have already imported app.a2 modules during test collection).
    """
    project_root = str(Path(__file__).parent.parent.parent)

    # Minimal env required for app.main to import without errors
    env = os.environ.copy()
    env["PYTHONPATH"] = project_root
    env["DATABASE_URL"] = "sqlite:///:memory:"
    env["NEXTCLOUD_URL"] = "http://example.invalid"
    env["NEXTCLOUD_USER"] = "x"
    env["NEXTCLOUD_PASSWORD"] = "x"
    env["NEXTCLOUD_FILE_PATH"] = "/x.xlsx"
    env["WC_URL"] = "http://example.invalid"
    env["WC_KEY"] = "x"
    env["WC_SECRET"] = "x"
    env["SUPER_ADMIN_USERS"] = "testadmin"

    script = (
        "import sys, json\n"
        "import app.main\n"
        "print(json.dumps([k for k in sys.modules if k.startswith('app.a2')]))\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"subprocess failed (exit {result.returncode}):\n{result.stderr}"
    )
    a2_modules = json.loads(result.stdout.strip())
    assert a2_modules == [], (
        f"app.main transitively imported A2 modules in a fresh process: {a2_modules}. "
        "A2 must be a standalone additive package — app.main must not depend on app.a2."
    )
