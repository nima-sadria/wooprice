"""CP1.3 — Diagnostic Runner.

Orchestrates integration health checks through CP1.2 safe abstractions.
Never blocks the Control Plane — all exceptions are caught and converted
to structured UNKNOWN_ERROR results.  Secrets are never stored in reports.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.beta.connections.adapters import NetworkAdapter
from app.beta.control_plane.failure import FailureClass, Severity
from app.beta.health.engine import HealthEngine
from app.beta.health.models import CheckCategory, HealthCheckResult, HealthStatus

from .repair import ProbableCauseInferrer, RepairPlaybook
from .report import DiagnosticCategory, DiagnosticCheckResult, DiagnosticReport

# Maps service name → env var keys for URL / credentials.
# Credentials are resolved at call time from config dict, never stored.
_SERVICE_CONFIG: dict[str, dict[str, str]] = {
    "nextcloud": {
        "url_key": "BETA_NEXTCLOUD_URL",
        "username_key": "BETA_NEXTCLOUD_USERNAME",
        "password_key": "BETA_NEXTCLOUD_PASSWORD",
    },
    "woocommerce": {
        "url_key": "BETA_WOOCOMMERCE_URL",
        "username_key": "BETA_WOOCOMMERCE_KEY",
        "password_key": "BETA_WOOCOMMERCE_SECRET",
    },
    "currency_api": {
        "url": "https://alanchand.com/api/",
        "url_key": "",
        "username_key": "",
        "password_key": "",
    },
}

KNOWN_SERVICES: list[str] = list(_SERVICE_CONFIG.keys())


class DiagnosticRunner:
    """Runs structured health checks through CP1.2 NetworkAdapter abstractions.

    Accepts an injected NetworkAdapter so tests can use FakeNetworkAdapter
    without real network calls.  Config is a flat env-var dict (BETA_* keys).
    """

    def __init__(
        self,
        adapter: NetworkAdapter,
        config: Optional[dict[str, str]] = None,
    ) -> None:
        self._adapter = adapter
        self._config = config or {}
        self._engine = HealthEngine(adapter=adapter)
        self._inferrer = ProbableCauseInferrer()
        self._playbook = RepairPlaybook()

    def run_integration(
        self,
        service_name: str,
        url: Optional[str] = None,
        auth_username: Optional[str] = None,
        auth_password: Optional[str] = None,
    ) -> DiagnosticReport:
        """Run the full check chain for one integration service.

        Credentials are used only for the auth check and never stored in the
        returned DiagnosticReport.  Pass auth_username/auth_password explicitly,
        or leave None to skip the auth check.
        """
        started_at = datetime.now(tz=timezone.utc)
        svc_cfg = _SERVICE_CONFIG.get(service_name, {})

        effective_url = (
            url
            or self._config.get(svc_cfg.get("url_key", ""), "")
            or svc_cfg.get("url", "")
            or f"https://{service_name}.example.com"
        )

        # Credentials: use explicit args first, then config (never stored)
        eff_username = auth_username or self._config.get(svc_cfg.get("username_key", ""))
        eff_password = auth_password or self._config.get(svc_cfg.get("password_key", ""))

        checks: list[DiagnosticCheckResult] = []
        try:
            health_results = self._engine.run_integration_chain(
                service_name=service_name,
                url=effective_url,
                timeout=10.0,
                expected_http_status=200,
                auth_url=None,
                auth_username=eff_username,
                auth_password=eff_password,
            )
            for hr in health_results:
                checks.append(
                    DiagnosticCheckResult.from_health_result(hr, DiagnosticCategory.INTEGRATION)
                )
        except Exception as exc:
            checks.append(
                DiagnosticCheckResult.from_health_result(
                    _make_unknown_error(
                        f"integration:{service_name}",
                        effective_url,
                        f"Diagnostic runner caught unexpected error: {type(exc).__name__}",
                    ),
                    DiagnosticCategory.INTEGRATION,
                )
            )

        return self._build_report(service_name, started_at, checks)

    def run_all(
        self,
        config: Optional[dict[str, str]] = None,
    ) -> DiagnosticReport:
        """Run diagnostics for all known integration services."""
        started_at = datetime.now(tz=timezone.utc)
        cfg = config or self._config
        all_checks: list[DiagnosticCheckResult] = []

        for service_name, svc_cfg in _SERVICE_CONFIG.items():
            effective_url = (
                cfg.get(svc_cfg.get("url_key", ""), "")
                or svc_cfg.get("url", "")
                or f"https://{service_name}.example.com"
            )
            try:
                health_results = self._engine.run_integration_chain(
                    service_name=service_name,
                    url=effective_url,
                    timeout=10.0,
                    expected_http_status=200,
                )
                for hr in health_results:
                    all_checks.append(
                        DiagnosticCheckResult.from_health_result(hr, DiagnosticCategory.INTEGRATION)
                    )
            except Exception as exc:
                all_checks.append(
                    DiagnosticCheckResult.from_health_result(
                        _make_unknown_error(
                            f"integration:{service_name}",
                            effective_url,
                            f"Unexpected error checking {service_name}: {type(exc).__name__}",
                        ),
                        DiagnosticCategory.INTEGRATION,
                    )
                )

        return self._build_report("all", started_at, all_checks)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_report(
        self,
        target: str,
        started_at: datetime,
        checks: list[DiagnosticCheckResult],
    ) -> DiagnosticReport:
        completed_at = datetime.now(tz=timezone.utc)

        failed = [c for c in checks if c.status == HealthStatus.FAIL]
        warned = [c for c in checks if c.status == HealthStatus.WARN]

        if failed:
            overall_status = HealthStatus.FAIL
            # Pick the worst failure class by severity
            worst = max(failed, key=lambda c: c.severity)
            overall_fc = worst.failure_class
            overall_severity = worst.severity
        elif warned:
            overall_status = HealthStatus.WARN
            worst_warn = max(warned, key=lambda c: c.severity)
            overall_fc = worst_warn.failure_class
            overall_severity = Severity.WARNING
        elif checks:
            overall_status = HealthStatus.PASS
            overall_fc = FailureClass.NONE
            overall_severity = Severity.INFO
        else:
            overall_status = HealthStatus.UNKNOWN
            overall_fc = FailureClass.NONE
            overall_severity = Severity.INFO

        repair_steps = self._playbook.steps_for(overall_fc) if failed else []

        total = len(checks)
        fail_count = len(failed)
        warn_count = len(warned)
        if total == 0:
            summary = "No checks were run."
        elif fail_count:
            summary = (
                f"{fail_count} of {total} check(s) failed. "
                f"Probable cause: {self._inferrer.infer(overall_fc)}"
            )
        elif warn_count:
            summary = f"{warn_count} of {total} check(s) have warnings."
        else:
            summary = f"All {total} check(s) passed."

        return DiagnosticReport(
            target=target,
            started_at=started_at,
            completed_at=completed_at,
            overall_status=overall_status,
            overall_failure_class=overall_fc,
            overall_severity=overall_severity,
            checks=checks,
            repair_steps=repair_steps,
            summary=summary,
        )


def _make_unknown_error(
    check_name: str,
    target: str,
    message: str,
) -> HealthCheckResult:
    return HealthCheckResult.fail(
        check_name=check_name,
        category=CheckCategory.INTEGRATION,
        target=target,
        failure_class=FailureClass.UNKNOWN_ERROR,
        message=message,
    )
