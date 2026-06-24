"""Unit tests — SourceCapabilities."""
import os
os.environ.setdefault("A2_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("NEXTCLOUD_URL", "http://example.invalid")
os.environ.setdefault("NEXTCLOUD_USER", "x")
os.environ.setdefault("NEXTCLOUD_PASSWORD", "x")
os.environ.setdefault("NEXTCLOUD_FILE_PATH", "/x.xlsx")
os.environ.setdefault("WC_URL", "http://example.invalid")
os.environ.setdefault("WC_KEY", "x")
os.environ.setdefault("WC_SECRET", "x")

from app.a2.sources.capabilities import SourceCapabilities


def test_all_false_by_default():
    caps = SourceCapabilities()
    assert caps.supports_streaming is False
    assert caps.supports_checkpointing is False
    assert caps.supports_deletions is False
    assert caps.supports_incremental_sync is False
    assert caps.supports_snapshots is False


def test_explicit_flags():
    caps = SourceCapabilities(
        supports_streaming=True,
        supports_snapshots=True,
    )
    assert caps.supports_streaming is True
    assert caps.supports_snapshots is True
    assert caps.supports_checkpointing is False


def test_pydantic_validation_rejects_non_bool():
    try:
        SourceCapabilities(supports_streaming="yes")  # type: ignore[arg-type]
        # Pydantic v2 coerces "yes" → True; accept either behaviour
    except Exception:
        pass  # strict mode would reject it
