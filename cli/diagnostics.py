"""WooPrice Beta — wooprice diagnostics command group (CP1.3).

diagnostics (default)  — env info, config validation, prerequisites (no network)
diagnostics run        — full integration health check via DiagnosticRunner
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer

from app.beta.connections.adapters import RealNetworkAdapter
from app.beta.diagnostics.runner import DiagnosticRunner, KNOWN_SERVICES

app = typer.Typer(help="Diagnostics: environment checks and integration health.")


@app.callback(invoke_without_command=True)
def diagnostics(
    ctx: typer.Context,
    env_file: Annotated[
        Path | None,
        typer.Option("--env-file", help="Path to .env file"),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
) -> None:
    """Show branch-safe diagnostics: config summary, secrets status, prerequisites."""
    if ctx.invoked_subcommand is not None:
        return
    from cli.shared.output import console, print_banner, print_section
    from cli.shared.config_reader import load_config, validate_env_file, secret_status
    from app.beta.config import REQUIRED_FIELDS, SECRET_FIELDS
    from installer.installer_core import check_prerequisites

    manager, profile = load_config(env_file)

    # --- Env dict (for field presence check) ---
    env_dict: dict[str, str] = {}
    _ef = env_file or (Path(".env") if Path(".env").exists() else None)
    if _ef and _ef.exists():
        for line in _ef.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            if k:
                env_dict[k] = v.strip()

    # --- Validation ---
    validation = validate_env_file(env_file)

    # --- Missing required fields ---
    missing = [f for f in REQUIRED_FIELDS if f not in env_dict]

    # --- Secret status (set / not set — never values) ---
    sec_status = secret_status(env_dict)

    # --- Prerequisites ---
    prereqs = check_prerequisites(install_dir=None)

    diag_data = {
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "profile": profile.value if profile else "unknown",
        "config_loaded": profile is not None,
        "config_valid": validation.is_valid,
        "validation_errors": len(validation.errors),
        "missing_required_fields": missing,
        "secret_status": sec_status,
        "prerequisites": [
            {"name": p.name, "passed": p.passed, "message": p.message}
            for p in prereqs
        ],
    }

    if json_output:
        typer.echo(json.dumps(diag_data, indent=2))
        return

    print_banner(profile)

    print_section("Environment")
    console.print(f"  Python:          {diag_data['python_version']}")
    console.print(f"  Profile:         {diag_data['profile']}")
    console.print(f"  Config loaded:   {'[green]YES[/green]' if diag_data['config_loaded'] else '[red]NO[/red]'}")
    console.print(f"  Config valid:    {'[green]YES[/green]' if diag_data['config_valid'] else '[red]NO[/red]'}")

    print_section("Validation Summary")
    if validation.is_valid:
        console.print("  [green]✓[/green]  All 22 required fields pass validation.")
    else:
        console.print(f"  [red]✗[/red]  {len(validation.errors)} error(s) found:")
        for err in validation.errors[:10]:
            display = "[REDACTED]" if err.field in SECRET_FIELDS else repr(err.value)
            console.print(f"      [red]•[/red] {err.field}={display}: {err.message}")
        if len(validation.errors) > 10:
            console.print(f"      [dim]... and {len(validation.errors) - 10} more[/dim]")

    if missing:
        print_section("Missing Required Variables")
        for field in missing:
            console.print(f"  [red]✗[/red]  {field}")

    print_section("Secret Status (values never shown)")
    for field, status in sec_status.items():
        icon = "[green]✓[/green]" if status == "set" else "[red]✗[/red]"
        console.print(f"  {icon}  {field:<36} {status}")

    print_section("Installer Prerequisites")
    for pre in prereqs:
        icon = "[green]✓[/green]" if pre.passed else "[red]✗[/red]"
        console.print(f"  {icon}  {pre.name}: {pre.message}")

    console.print()


@app.command("run")
def diagnostics_run(
    target: Annotated[
        Optional[str],
        typer.Argument(
            help="Service to diagnose: nextcloud | woocommerce | currency_api | all (default: all)"
        ),
    ] = None,
    env_file: Annotated[
        Optional[Path],
        typer.Option("--env-file", help="Path to .env file"),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
) -> None:
    """Run integration health checks through CP1.2 safe abstractions.

    Runs all integration services by default. Pass a service name to target one.
    Secrets are never included in output or stored in the diagnostic report.
    """
    from cli.shared.output import console, print_banner, print_section
    from cli.shared.config_reader import load_config

    service = (target or "all").lower()
    if service != "all" and service not in KNOWN_SERVICES:
        typer.echo(
            f"Unknown target '{service}'. Known services: {', '.join(KNOWN_SERVICES)} | all",
            err=True,
        )
        raise typer.Exit(code=1)

    _, profile = load_config(env_file)
    env_path = env_file or (Path(".env") if Path(".env").exists() else None)
    config_dict: dict[str, str] = {}
    if env_path and env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            k, _, v = stripped.partition("=")
            k = k.strip()
            if k:
                config_dict[k] = v.strip()

    if not json_output:
        print_banner(profile)

    runner = DiagnosticRunner(adapter=RealNetworkAdapter(), config=config_dict)

    if service == "all":
        report = runner.run_all(config=config_dict)
    else:
        report = runner.run_integration(service)

    if json_output:
        import json as _json
        typer.echo(_json.dumps(report.to_dict(), indent=2))
        if report.overall_status.value == "fail":
            raise typer.Exit(code=1)
        return

    print_section(f"Diagnostic Run — {report.target}")

    _STATUS_ICON = {
        "pass": "[green]✓[/green]",
        "warn": "[yellow]⚠[/yellow]",
        "fail": "[red]✗[/red]",
        "skip": "[dim]-[/dim]",
        "unknown": "[dim]?[/dim]",
    }

    for check in report.checks:
        icon = _STATUS_ICON.get(check.status.value, "?")
        fc_note = (
            f"  [{check.failure_class.value}]"
            if check.failure_class.value != "none"
            else ""
        )
        ms_note = f"  ({check.duration_ms:.0f}ms)" if check.duration_ms > 0 else ""
        skip_note = (
            f"  (skipped — {check.skipped_because} failed)"
            if check.skipped_because
            else ""
        )
        console.print(
            f"  {icon}  {check.check_name:<32} {check.message}{fc_note}{ms_note}{skip_note}"
        )

    console.print()
    _OVERALL_STYLE = {"pass": "[bold green]", "warn": "[bold yellow]", "fail": "[bold red]"}
    style = _OVERALL_STYLE.get(report.overall_status.value, "[bold]")
    console.print(f"  Overall: {style}{report.overall_status.value.upper()}[/]")
    console.print(f"  {report.summary}")

    if report.repair_steps:
        console.print()
        console.print("  Repair steps:")
        for step in report.repair_steps:
            console.print(f"    {step.step_number}. {step.description}")
            if step.command:
                console.print(f"       [dim]$ {step.command}[/dim]")
            if step.detail:
                console.print(f"       [dim]{step.detail}[/dim]")

    console.print()
    if report.overall_status.value == "fail":
        raise typer.Exit(code=1)
