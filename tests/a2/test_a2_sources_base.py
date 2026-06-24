"""Unit tests — SourceAdapter ABC and hash_row utility."""
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

import pytest

from app.a2.sources.base import SourceAdapter, hash_row


def test_source_adapter_is_abstract():
    with pytest.raises(TypeError):
        SourceAdapter()  # type: ignore[abstract]


def test_hash_row_deterministic():
    data = {"product_id": 123, "price_raw": "99.00", "label": "Widget"}
    h1 = hash_row(data)
    h2 = hash_row(data)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex


def test_hash_row_sensitive_to_values():
    d1 = {"product_id": 1, "price_raw": "10.00"}
    d2 = {"product_id": 1, "price_raw": "20.00"}
    assert hash_row(d1) != hash_row(d2)


def test_hash_row_key_order_independent():
    d1 = {"a": 1, "b": 2}
    d2 = {"b": 2, "a": 1}
    assert hash_row(d1) == hash_row(d2)


def test_hash_row_handles_non_string_values():
    data = {"product_id": 42, "flag": True, "count": None}
    h = hash_row(data)
    assert isinstance(h, str) and len(h) == 64
