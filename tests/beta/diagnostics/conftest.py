"""Shared fixtures for diagnostic runner tests."""

from __future__ import annotations

import pytest

from tests.beta.connections.conftest import FakeNetworkAdapter
from app.beta.connections.adapters import (
    DNSResolutionError,
    TCPConnectionError,
    TLSHandshakeError,
    ConnectionTimeoutError,
    AuthenticationError,
    AccessForbiddenError,
)
from app.beta.diagnostics.runner import DiagnosticRunner


@pytest.fixture
def fake_adapter() -> FakeNetworkAdapter:
    return FakeNetworkAdapter()


@pytest.fixture
def runner(fake_adapter: FakeNetworkAdapter) -> DiagnosticRunner:
    return DiagnosticRunner(adapter=fake_adapter, config={})


@pytest.fixture
def runner_with_config(fake_adapter: FakeNetworkAdapter) -> DiagnosticRunner:
    config = {
        "BETA_NEXTCLOUD_URL": "https://nextcloud.example.com",
        "BETA_NEXTCLOUD_USERNAME": "admin",
        "BETA_NEXTCLOUD_PASSWORD": "secret123",
        "BETA_WOOCOMMERCE_URL": "https://shop.example.com",
        "BETA_WOOCOMMERCE_KEY": "ck_abc",
        "BETA_WOOCOMMERCE_SECRET": "cs_xyz",
    }
    return DiagnosticRunner(adapter=fake_adapter, config=config)
