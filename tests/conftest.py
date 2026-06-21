"""Shared pytest configuration.

Sets environment variables before any test module is imported so that
get_settings() (which is @lru_cache'd) sees the correct values on its first call.
All individual test files also set these via os.environ.setdefault() as a fallback
for when they are run in isolation (e.g. python tests/test_phase7b.py).
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("NEXTCLOUD_URL", "http://example.invalid")
os.environ.setdefault("NEXTCLOUD_USER", "x")
os.environ.setdefault("NEXTCLOUD_PASSWORD", "x")
os.environ.setdefault("NEXTCLOUD_FILE_PATH", "/x.xlsx")
os.environ.setdefault("WC_URL", "http://example.invalid")
os.environ.setdefault("WC_KEY", "x")
os.environ.setdefault("WC_SECRET", "x")
# 'testadmin' is used by test_phase7b.py as a super admin (bypasses DB checks).
os.environ.setdefault("SUPER_ADMIN_USERS", "testadmin")
