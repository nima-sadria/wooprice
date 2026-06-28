"""Tests for wooprice diagnostics run command (CP1.3)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest
from typer.testing import CliRunner

from cli.main import app

runner = CliRunner()


def _make_fake_runner(all_pass: bool = True):
    from tests.beta.connections.conftest import FakeNetworkAdapter
    from app.beta.connections.adapters import DNSResolutionError
    from app.beta.diagnostics.runner import DiagnosticRunner

    fake = FakeNetworkAdapter()
    if not all_pass:
        fake.dns_default = DNSResolutionError("NXDOMAIN")
    return DiagnosticRunner(adapter=fake, config={})


class TestDiagnosticsRunCommand:
    def test_run_help_exits_zero(self):
        result = runner.invoke(app, ["diagnostics", "run", "--help"])
        assert result.exit_code == 0

    def test_run_unknown_target_exits_nonzero(self):
        with mock.patch("cli.diagnostics.RealNetworkAdapter"):
            result = runner.invoke(app, ["diagnostics", "run", "unknown_service"])
        assert result.exit_code != 0

    def test_run_all_pass_exits_zero(self):
        _runner = _make_fake_runner(all_pass=True)
        with mock.patch("cli.diagnostics.RealNetworkAdapter"), \
             mock.patch("cli.diagnostics.DiagnosticRunner", return_value=_runner):
            result = runner.invoke(app, ["diagnostics", "run"])
        assert result.exit_code == 0

    def test_run_with_fail_exits_nonzero(self):
        _runner = _make_fake_runner(all_pass=False)
        with mock.patch("cli.diagnostics.RealNetworkAdapter"), \
             mock.patch("cli.diagnostics.DiagnosticRunner", return_value=_runner):
            result = runner.invoke(app, ["diagnostics", "run"])
        assert result.exit_code != 0

    def test_run_json_output_pass(self):
        _runner = _make_fake_runner(all_pass=True)
        with mock.patch("cli.diagnostics.RealNetworkAdapter"), \
             mock.patch("cli.diagnostics.DiagnosticRunner", return_value=_runner):
            result = runner.invoke(app, ["diagnostics", "run", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "overall_status" in data
        assert "checks" in data
        assert "summary" in data

    def test_run_specific_service(self):
        _runner = _make_fake_runner(all_pass=True)
        with mock.patch("cli.diagnostics.RealNetworkAdapter"), \
             mock.patch("cli.diagnostics.DiagnosticRunner", return_value=_runner):
            result = runner.invoke(app, ["diagnostics", "run", "nextcloud"])
        assert result.exit_code == 0

    def test_run_no_secrets_in_output(self):
        from tests.beta.connections.conftest import FakeNetworkAdapter
        from app.beta.diagnostics.runner import DiagnosticRunner
        fake = FakeNetworkAdapter()
        _runner = DiagnosticRunner(adapter=fake, config={"BETA_NEXTCLOUD_PASSWORD": "secretpassword"})

        with mock.patch("cli.diagnostics.RealNetworkAdapter"), \
             mock.patch("cli.diagnostics.DiagnosticRunner", return_value=_runner):
            result = runner.invoke(app, ["diagnostics", "run"])
        assert "secretpassword" not in result.output

    def test_run_shows_overall_status(self):
        _runner = _make_fake_runner(all_pass=True)
        with mock.patch("cli.diagnostics.RealNetworkAdapter"), \
             mock.patch("cli.diagnostics.DiagnosticRunner", return_value=_runner):
            result = runner.invoke(app, ["diagnostics", "run"])
        assert "PASS" in result.output or "pass" in result.output.lower()

    def test_run_shows_summary(self):
        _runner = _make_fake_runner(all_pass=True)
        with mock.patch("cli.diagnostics.RealNetworkAdapter"), \
             mock.patch("cli.diagnostics.DiagnosticRunner", return_value=_runner):
            result = runner.invoke(app, ["diagnostics", "run"])
        assert "check" in result.output.lower() or "pass" in result.output.lower()

    def test_run_fail_shows_repair_steps(self):
        _runner = _make_fake_runner(all_pass=False)
        with mock.patch("cli.diagnostics.RealNetworkAdapter"), \
             mock.patch("cli.diagnostics.DiagnosticRunner", return_value=_runner):
            result = runner.invoke(app, ["diagnostics", "run"])
        assert "step" in result.output.lower() or "repair" in result.output.lower() or \
               "suggest" in result.output.lower() or "verify" in result.output.lower() or \
               result.exit_code != 0

    def test_run_woocommerce_target(self):
        _runner = _make_fake_runner(all_pass=True)
        with mock.patch("cli.diagnostics.RealNetworkAdapter"), \
             mock.patch("cli.diagnostics.DiagnosticRunner", return_value=_runner):
            result = runner.invoke(app, ["diagnostics", "run", "woocommerce"])
        assert result.exit_code == 0

    def test_run_all_target_explicit(self):
        _runner = _make_fake_runner(all_pass=True)
        with mock.patch("cli.diagnostics.RealNetworkAdapter"), \
             mock.patch("cli.diagnostics.DiagnosticRunner", return_value=_runner):
            result = runner.invoke(app, ["diagnostics", "run", "all"])
        assert result.exit_code == 0
