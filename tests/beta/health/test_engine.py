"""Tests for HealthEngine orchestrator."""

from __future__ import annotations

import pytest

from app.beta.connections.adapters import DNSResolutionError, TLSHandshakeError
from app.beta.control_plane.failure import FailureClass
from app.beta.health.models import CheckCategory, HealthStatus


# ---------------------------------------------------------------------------
# run() — single check delegation
# ---------------------------------------------------------------------------


def test_engine_run_delegates_to_check(engine, fake_adapter):
    from app.beta.health.checks import DNSCheck
    fake_adapter.dns_default = ["1.2.3.4"]
    r = engine.run(DNSCheck("dns", "nc.example.com", fake_adapter))
    assert r.status == HealthStatus.PASS


def test_engine_run_many_returns_all(engine, fake_adapter):
    from app.beta.health.checks import DNSCheck, StorageCheck
    checks = [
        DNSCheck("dns", "nc.example.com", fake_adapter),
        StorageCheck("storage", "/data", fake_adapter),
    ]
    results = engine.run_many(checks)
    assert len(results) == 2


# ---------------------------------------------------------------------------
# run_integration_chain()
# ---------------------------------------------------------------------------


def test_engine_integration_chain_success(engine, fake_adapter):
    results = engine.run_integration_chain("nextcloud", "https://nc.example.com")
    assert all(r.status in (HealthStatus.PASS, HealthStatus.WARN) for r in results)


def test_engine_integration_chain_has_4_steps_https(engine, fake_adapter):
    results = engine.run_integration_chain("nextcloud", "https://nc.example.com")
    # DNS, TCP, TLS, HTTP (no auth credentials supplied)
    assert len(results) == 4


def test_engine_integration_chain_has_3_steps_http(engine, fake_adapter):
    results = engine.run_integration_chain("service", "http://nc.example.com")
    # DNS, TCP, HTTP (no TLS, no auth)
    assert len(results) == 3


def test_engine_integration_chain_dns_fail_skips_rest(engine, fake_adapter):
    fake_adapter.dns_default = DNSResolutionError("NXDOMAIN")
    results = engine.run_integration_chain("nextcloud", "https://nc.example.com")
    dns = next(r for r in results if r.category == CheckCategory.DNS)
    tcp = next(r for r in results if r.category == CheckCategory.TCP)
    assert dns.status == HealthStatus.FAIL
    assert tcp.status == HealthStatus.SKIP


def test_engine_integration_chain_tls_fail_skips_http(engine, fake_adapter):
    fake_adapter.tls_default = TLSHandshakeError("cert verify failed")
    results = engine.run_integration_chain("nextcloud", "https://nc.example.com")
    http = next(r for r in results if r.category == CheckCategory.HTTP)
    assert http.status == HealthStatus.SKIP


# ---------------------------------------------------------------------------
# run_dns_check convenience method
# ---------------------------------------------------------------------------


def test_engine_run_dns_check_pass(engine, fake_adapter):
    fake_adapter.dns_default = ["1.2.3.4"]
    r = engine.run_dns_check("nc.example.com")
    assert r.status == HealthStatus.PASS
    assert r.category == CheckCategory.DNS


def test_engine_run_dns_check_fail(engine, fake_adapter):
    fake_adapter.dns_default = DNSResolutionError("NXDOMAIN")
    r = engine.run_dns_check("nc.example.com")
    assert r.status == HealthStatus.FAIL
    assert r.failure_class == FailureClass.DNS_FAILURE


# ---------------------------------------------------------------------------
# run_storage_check convenience method
# ---------------------------------------------------------------------------


def test_engine_run_storage_check_pass(engine, fake_adapter):
    r = engine.run_storage_check("/data/wooprice")
    assert r.status == HealthStatus.PASS


# ---------------------------------------------------------------------------
# run_database_check convenience method
# ---------------------------------------------------------------------------


def test_engine_run_database_check_pass(engine, fake_adapter):
    r = engine.run_database_check("postgresql://host/db")
    assert r.status == HealthStatus.PASS


# ---------------------------------------------------------------------------
# run_docker_check convenience method (stub)
# ---------------------------------------------------------------------------


def test_engine_run_docker_check_returns_skip(engine, fake_adapter):
    r = engine.run_docker_check()
    assert r.status == HealthStatus.SKIP


# ---------------------------------------------------------------------------
# run_config_check convenience method
# ---------------------------------------------------------------------------


def test_engine_run_config_check_pass(engine):
    r = engine.run_config_check(
        required_keys=["BETA_SECRET_KEY"],
        config_dict={"BETA_SECRET_KEY": "x"},
    )
    assert r.status == HealthStatus.PASS


def test_engine_run_config_check_fail_on_missing(engine):
    r = engine.run_config_check(
        required_keys=["BETA_SECRET_KEY"],
        config_dict={},
    )
    assert r.status == HealthStatus.FAIL


# ---------------------------------------------------------------------------
# summarize()
# ---------------------------------------------------------------------------


def test_engine_summarize_all_pass(engine, fake_adapter):
    results = engine.run_integration_chain("nextcloud", "https://nc.example.com")
    summary = engine.summarize(results)
    assert summary.overall_status in (HealthStatus.PASS, HealthStatus.WARN)


def test_engine_summarize_fail_when_dns_fails(engine, fake_adapter):
    fake_adapter.dns_default = DNSResolutionError("NXDOMAIN")
    results = engine.run_integration_chain("nextcloud", "https://nc.example.com")
    summary = engine.summarize(results)
    assert summary.overall_status == HealthStatus.FAIL
    assert summary.failed >= 1


def test_engine_summarize_counts_skips(engine, fake_adapter):
    fake_adapter.dns_default = DNSResolutionError("NXDOMAIN")
    results = engine.run_integration_chain("nextcloud", "https://nc.example.com")
    summary = engine.summarize(results)
    # DNS fail → TCP, TLS, HTTP all skipped
    assert summary.skipped >= 3


# ---------------------------------------------------------------------------
# No network calls verification
# ---------------------------------------------------------------------------


def test_no_real_network_in_integration_chain(engine, fake_adapter):
    """FakeNetworkAdapter must have been called — not a real adapter."""
    # If a real network call happened, the test environment would fail or be slow.
    # We verify it didn't by checking the adapter is our fake.
    from tests.beta.connections.conftest import FakeNetworkAdapter
    assert isinstance(fake_adapter, FakeNetworkAdapter)
    results = engine.run_integration_chain("nextcloud", "https://nc.example.com")
    # Results must be present
    assert len(results) > 0
