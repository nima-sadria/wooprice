"""WooPrice Beta — wooprice integrations command group (CP1.3).

list    — show all registered integration services
test    — run a live check chain for a specific service
status  — run checks for all services and show a summary

Uses CP1.2 HealthEngine through DiagnosticRunner.
Secrets are never printed. Network adapter is injected so tests can pass
a FakeNetworkAdapter without real network calls.
"""

from __future__ import annotations

import json as _json
from pathlib import Path
from typing import Annotated, Optional

import typer

from app.beta.diagnostics.runner import DiagnosticRunner, KNOWN_SERVICES

app = typer.Typer(help="Integration service management.")


def _load_config(env_file: Optional[Path]) -> dict[str, str]:
    path = env_file or (Path(".env") if Path(".env").exists() else None)
    config: dict[str, str] = {}
    if path and path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            k, _, v = stripped.partition("=")
            k = k.strip()
            if k:
                config[k] = v.strip()
    return config


def _make_adapter():
    from app.beta.connections.adapters import RealNetworkAdapter
    return RealNetworkAdapter()


@app.command("list")
def integrations_list() -> None:
    """List all registered integration services."""
    from cli.shared.output import console, print_banner, print_section
    from cli.shared.config_reader import load_config

    _, profile = load_config(None)
    print_banner(profile)
    print_section("Integration Services")

    for name in KNOWN_SERVICES:
        console.print(f"  [cyan]•[/cyan]  {name}")

    console.print()
    console.print(
        "  Run [bold]wooprice integrations test <service>[/bold] to run a live check."
    )
    console.print()


@app.command("test")
def integrations_test(
    service: Annotated[
        str,
        typer.Argument(help=f"Service to test: {' | '.join(KNOWN_SERVICES)}"),
    ],
    env_file: Annotated[
        Optional[Path],
        typer.Option("--env-file", help="Path to .env file"),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
) -> None:
    """Run a live integration health check for a specific service."""
    from cli.shared.output import console, print_banner, print_section
    from cli.shared.config_reader import load_config

    if service not in KNOWN_SERVICES:
        typer.echo(
            f"Unknown service '{service}'. Known services: {', '.join(KNOWN_SERVICES)}",
            err=True,
        )
        raise typer.Exit(code=1)

    _, profile = load_config(env_file)
    config_dict = _load_config(env_file)

    if not json_output:
        print_banner(profile)

    runner = DiagnosticRunner(adapter=_make_adapter(), config=config_dict)
    report = runner.run_integration(service)

    if json_output:
        typer.echo(_json.dumps(report.to_dict(), indent=2))
        if report.overall_status.value == "fail":
            raise typer.Exit(code=1)
        return

    print_section(f"Integration Test — {service}")

    _STATUS_ICON = {
        "pass": "[green]PASS[/green]",
        "warn": "[yellow]WARN[/yellow]",
        "fail": "[red]FAIL[/red]",
        "skip": "[dim]SKIP[/dim]",
        "unknown": "[dim]UNKN[/dim]",
    }

    for check in report.checks:
        icon = _STATUS_ICON.get(check.status.value, check.status.value.upper())
        fc_note = (
            f" · {check.failure_class.value}"
            if check.failure_class.value != "none"
            else ""
        )
        skip_note = (
            f"  ({check.skipped_because} failed)"
            if check.skipped_because
            else ""
        )
        ms_note = (
            f"  ({check.duration_ms:.0f}ms)"
            if check.duration_ms > 0
            else ""
        )
        console.print(
            f"  {check.check_name:<8} {icon}{fc_note}  {check.message}{ms_note}{skip_note}"
        )

    console.print()
    _OVERALL_STYLE = {"pass": "[bold green]", "warn": "[bold yellow]", "fail": "[bold red]"}
    style = _OVERALL_STYLE.get(report.overall_status.value, "[bold]")
    console.print(
        f"  Result: {style}{report.overall_status.value.upper()}[/]"
        f"  ·  {report.overall_failure_class.value}"
    )

    if report.repair_steps:
        console.print()
        console.print("  Suggested repair steps:")
        for step in report.repair_steps:
            console.print(f"    {step.step_number}. {step.description}")
            if step.command:
                console.print(f"       [dim]$ {step.command}[/dim]")
            if step.detail:
                console.print(f"       [dim]{step.detail}[/dim]")

    console.print()
    if report.overall_status.value == "fail":
        raise typer.Exit(code=1)


@app.command("status")
def integrations_status(
    env_file: Annotated[
        Optional[Path],
        typer.Option("--env-file", help="Path to .env file"),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
) -> None:
    """Run on-demand checks for all integration services and show summary."""
    from cli.shared.output import console, print_banner, print_section
    from cli.shared.config_reader import load_config

    _, profile = load_config(env_file)
    config_dict = _load_config(env_file)

    if not json_output:
        print_banner(profile)

    runner = DiagnosticRunner(adapter=_make_adapter(), config=config_dict)
    report = runner.run_all(config=config_dict)

    if json_output:
        typer.echo(_json.dumps(report.to_dict(), indent=2))
        return

    print_section("Integration Status")

    _STATUS_ICON = {
        "pass": "[green]✓[/green]",
        "warn": "[yellow]⚠[/yellow]",
        "fail": "[red]✗[/red]",
        "skip": "[dim]-[/dim]",
        "unknown": "[dim]?[/dim]",
    }

    for check in report.checks:
        icon = _STATUS_ICON.get(check.status.value, "?")
        ms_note = f"  ({check.duration_ms:.0f}ms)" if check.duration_ms > 0 else ""
        fc_note = (
            f"  [{check.failure_class.value}]"
            if check.failure_class.value != "none"
            else ""
        )
        console.print(f"  {icon}  {check.check_name:<32} {check.message}{fc_note}{ms_note}")

    console.print()
    _OVERALL_STYLE = {"pass": "[bold green]", "warn": "[bold yellow]", "fail": "[bold red]"}
    style = _OVERALL_STYLE.get(report.overall_status.value, "[bold]")
    console.print(f"  Overall: {style}{report.overall_status.value.upper()}[/]")
    console.print(f"  {report.summary}")
    console.print()
