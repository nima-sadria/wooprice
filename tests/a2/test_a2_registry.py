"""Unit tests — SourceRegistry."""
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

from collections.abc import AsyncIterator
from typing import Optional

import pytest

from app.a2.sources.base import SourceAdapter, SourceRow, SourceValidationResult
from app.a2.sources.capabilities import SourceCapabilities
from app.a2.sources.checkpoint import SourceCheckpoint
from app.a2.sources.registry import (
    DuplicateSourceTypeError,
    SourceRegistry,
    UnknownSourceTypeError,
)
from app.a2.sources.snapshot import SourceSnapshot


class _DummyAdapter(SourceAdapter):
    async def connect(self) -> None:
        pass

    async def validate_source(self) -> SourceValidationResult:
        return SourceValidationResult(is_valid=True)

    async def fetch_snapshot(self) -> SourceSnapshot:
        raise NotImplementedError

    def stream_rows(self) -> AsyncIterator[SourceRow]:
        raise NotImplementedError

    def get_capabilities(self) -> SourceCapabilities:
        return SourceCapabilities()

    async def get_checkpoint(self) -> Optional[SourceCheckpoint]:
        return None

    async def advance_checkpoint(self, checkpoint: SourceCheckpoint) -> None:
        pass


class _OtherAdapter(_DummyAdapter):
    pass


def test_register_and_resolve():
    registry = SourceRegistry()
    registry.register("dummy", _DummyAdapter)
    resolved = registry.resolve("dummy")
    assert resolved is _DummyAdapter


def test_duplicate_registration_raises():
    registry = SourceRegistry()
    registry.register("dummy", _DummyAdapter)
    with pytest.raises(DuplicateSourceTypeError):
        registry.register("dummy", _DummyAdapter)


def test_unknown_type_raises():
    registry = SourceRegistry()
    with pytest.raises(UnknownSourceTypeError):
        registry.resolve("nonexistent")


def test_multiple_types():
    registry = SourceRegistry()
    registry.register("type_a", _DummyAdapter)
    registry.register("type_b", _OtherAdapter)
    assert registry.resolve("type_a") is _DummyAdapter
    assert registry.resolve("type_b") is _OtherAdapter


def test_registered_types_sorted():
    registry = SourceRegistry()
    registry.register("z_type", _DummyAdapter)
    registry.register("a_type", _OtherAdapter)
    assert registry.registered_types() == ["a_type", "z_type"]


def test_register_does_not_affect_other_instances():
    r1 = SourceRegistry()
    r2 = SourceRegistry()
    r1.register("dummy", _DummyAdapter)
    with pytest.raises(UnknownSourceTypeError):
        r2.resolve("dummy")
