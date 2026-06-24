"""
A2 test configuration.

Sets environment variables before any A2 module is imported so the A2 database
layer uses in-memory SQLite instead of requiring a live PostgreSQL instance.
"""
import os

os.environ.setdefault("A2_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("NEXTCLOUD_URL", "http://example.invalid")
os.environ.setdefault("NEXTCLOUD_USER", "testuser")
os.environ.setdefault("NEXTCLOUD_PASSWORD", "testpass")
os.environ.setdefault("NEXTCLOUD_FILE_PATH", "/prices.xlsx")
os.environ.setdefault("WC_URL", "http://example.invalid")
os.environ.setdefault("WC_KEY", "x")
os.environ.setdefault("WC_SECRET", "x")
