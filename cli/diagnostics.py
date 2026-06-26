"""WooPrice Beta — wooprice diagnostics command.

Shows environment info, config validation summary, missing required variables,
redacted secret status, and installer prerequisite summary.
No secrets in output. No external network calls.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(help="Environment diagnostics (read-only, no network calls).")


@app.callback(invoke_without_command=True)
def diagnostics(
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
