"""Regression tests for the DX improvement: platform-aware DATABASE_URL default
and scoped directory auto-creation.

Coverage:
  1. _default_database_url() returns local path on Windows.
  2. _default_database_url() raises RuntimeError on non-Windows (fail-fast).
  3. DATABASE_URL env var overrides the default (pydantic-settings framework
     behaviour — verified by confirming the factory is NOT called when the env
     var is present).
  4. _ensure_local_db_dir() creates data/ on Windows with the local fallback URL.
  5. _ensure_local_db_dir() is a no-op on non-Windows regardless of URL.
  6. _ensure_local_db_dir() is a no-op on Windows for any URL that is not the
     exact Windows local fallback (e.g. :memory:, Docker absolute paths).

Note on import-time side effects: app.database calls get_settings() at module
level, which requires DATABASE_URL to be set (or triggers _default_database_url).
We set DATABASE_URL=sqlite:///:memory: via os.environ.setdefault() BEFORE any app
import, following the same pattern as all other test files in this suite.  The
_default_database_url and _ensure_local_db_dir functions are then imported for
direct unit testing with sys.platform patched as needed.
"""
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

os.environ.setdefault("NEXTCLOUD_URL", "http://example.invalid")
os.environ.setdefault("NEXTCLOUD_USER", "x")
os.environ.setdefault("NEXTCLOUD_PASSWORD", "x")
os.environ.setdefault("NEXTCLOUD_FILE_PATH", "/x.xlsx")
os.environ.setdefault("WC_URL", "http://example.invalid")
os.environ.setdefault("WC_KEY", "x")
os.environ.setdefault("WC_SECRET", "x")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import _default_database_url, Settings  # noqa: E402
from app.database import _ensure_local_db_dir, _WIN_LOCAL_URL  # noqa: E402


# ── _default_database_url ─────────────────────────────────────────────────────

def test_windows_returns_local_db_path():
    with mock.patch.object(sys, "platform", "win32"):
        assert _default_database_url() == "sqlite:///./data/wooprice-local.db"


def test_linux_raises_without_database_url():
    with mock.patch.object(sys, "platform", "linux"):
        try:
            _default_database_url()
            assert False, "Expected RuntimeError was not raised"
        except RuntimeError as exc:
            assert "DATABASE_URL is required" in str(exc)
            assert "non-Windows" in str(exc)


def test_macos_raises_without_database_url():
    with mock.patch.object(sys, "platform", "darwin"):
        try:
            _default_database_url()
            assert False, "Expected RuntimeError was not raised"
        except RuntimeError as exc:
            assert "DATABASE_URL is required" in str(exc)


def test_database_url_env_overrides_default_factory(monkeypatch):
    explicit_url = "sqlite:////tmp/explicit-test.db"
    monkeypatch.setenv("DATABASE_URL", explicit_url)
    # Linux + no factory fallback: if pydantic-settings called the factory
    # instead of reading the env var, Settings() would raise RuntimeError.
    monkeypatch.setattr(sys, "platform", "linux")

    settings = Settings()

    assert settings.database_url == explicit_url


# ── _ensure_local_db_dir ──────────────────────────────────────────────────────

def test_windows_local_url_creates_data_dir():
    with tempfile.TemporaryDirectory() as tmp:
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp)
            with mock.patch.object(sys, "platform", "win32"):
                _ensure_local_db_dir(_WIN_LOCAL_URL)
            assert Path(tmp, "data").exists()
        finally:
            os.chdir(original_cwd)


def test_linux_local_url_does_not_create_dir():
    with tempfile.TemporaryDirectory() as tmp:
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp)
            with mock.patch.object(sys, "platform", "linux"):
                _ensure_local_db_dir(_WIN_LOCAL_URL)
            assert not Path(tmp, "data").exists()
        finally:
            os.chdir(original_cwd)


def test_windows_memory_url_does_not_create_dir():
    with tempfile.TemporaryDirectory() as tmp:
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp)
            with mock.patch.object(sys, "platform", "win32"):
                _ensure_local_db_dir("sqlite:///:memory:")
            assert not Path(tmp, "data").exists()
        finally:
            os.chdir(original_cwd)


def test_windows_docker_absolute_url_does_not_create_dir():
    with tempfile.TemporaryDirectory() as tmp:
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp)
            with mock.patch.object(sys, "platform", "win32"):
                _ensure_local_db_dir("sqlite:////app/data/wooprice.db")
            assert not Path(tmp, "data").exists()
        finally:
            os.chdir(original_cwd)
