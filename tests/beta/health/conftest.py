"""Shared fixtures for health engine tests.

Imports FakeNetworkAdapter from the connection tests conftest so there is one
canonical fake — no duplication.
"""

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
from app.beta.health.engine import HealthEngine


@pytest.fixture
def fake_adapter() -> FakeNetworkAdapter:
    return FakeNetworkAdapter()


@pytest.fixture
def engine(fake_adapter) -> HealthEngine:
    return HealthEngine(adapter=fake_adapter)
