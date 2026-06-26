"""WooPrice Beta — wooprice health command group.

Local-only health checks. No external network calls.
Docker runtime health checks (db, sources, channels) require B6.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(help="Local health checks (no network calls).")

_REQUIRED_MODULES = [
    ("typer", "Typer (CLI framework)"),
    ("rich", "Rich (terminal output)"),
    ("pydantic", "Pydantic v2 (config schema)"),
    ("dotenv", "python-dotenv (env file loading)"),
    ("app.beta.config", "B3 Configuration Foundation"),
    ("installer.installer_core", "B4 Installer Core"),
]


@app.callback(invoke_without_command=True)
def health(
    env_file: Annotated[
        Path | None,
        typer.Option("--env-file", help="Path to .env file"),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
) -> None:
    """Run local health checks and report pass/fail for each."""
    from cli.shared.output import console, print_banner, print_section
    from cli.shared.config_reader import load_config

    checks: list[dict[str, object]] = []

    # 1. Python version
    ok = sys.version_info >= (3, 12)
    checks.append({
        "name": "Python >= 3.12",
        "passed": ok,
        "detail": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    })

    # 2. Required modules importable
    for mod, label in _REQUIRED_MODULES:
        try:
            importlib.import_module(mod)
            checks.append({"name": f"Import: {label}", "passed": True, "detail": "ok"})
        except ImportError as e:
            checks.append({"name": f"Import: {label}", "passed": False, "detail": str(e)})

    # 3. Config loads (if env file provided or .env exists in cwd)
    _env_path = env_file or (Path(".env") if Path(".env").exists() else None)
    config_load_attempted = _env_path is not None
    if config_load_attempted:
        manager, profile = load_config(_env_path)
        config_loaded = profile is not None
        checks.append({
            "name": "Config: loads from .env",
            "passed": config_loaded,
            "detail": f"profile={profile.value}" if profile else "failed to load",
        })

        # 4. Config validates
        if config_loaded:
            from cli.shared.config_reader import validate_env_file
            result = validate_env_file(_env_path)
            checks.append({
                "name": "Config: validates",
                "passed": result.is_valid,
                "detail": "valid" if result.is_valid else f"{len(result.errors)} error(s)",
            })
    else:
        checks.append({
            "name": "Config: .env file",
            "passed": False,
            "detail": "no .env file found (pass --env-file to check)",
        })

    # 5. Storage path readable (if config loaded)
    storage_path_str = ""
    if config_load_attempted and config_loaded:
        _ef = _env_path
        if _ef and _ef.exists():
            for line in _ef.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("BETA_STORAGE_PATH="):
                    storage_path_str = line.split("=", 1)[1].strip()
                    break
    if storage_path_str:
        sp = Path(storage_path_str)
        # Not existing is expected pre-install; report as info, not failure
        checks.append({
            "name": "Storage path",
            "passed": True,
            "detail": str(sp) + (" [exists]" if sp.exists() else " [not created — run install first]"),
        })

    all_passed = all(c["passed"] for c in checks)  # type: ignore[arg-type]

    if json_output:
        typer.echo(json.dumps({"all_passed": all_passed, "checks": checks}, indent=2))
        if not all_passed:
            raise typer.Exit(code=1)
        return

    manager_for_profile, profile_for_banner = load_config(env_file) if env_file else (None, None)
    print_banner(profile_for_banner)
    print_section("Health Checks")

    for c in checks:
        passed = c["passed"]
        icon = "[green]✓[/green]" if passed else "[red]✗[/red]"
        name = c["name"]
        detail = c["detail"]
        console.print(f"  {icon}  {name}  [dim]{detail}[/dim]")

    console.print()
    if all_passed:
        console.print("  [bold green]All checks passed.[/bold green]\n")
    else:
        failed = sum(1 for c in checks if not c["passed"])
        console.print(f"  [bold red]{failed} check(s) failed.[/bold red]\n")
        raise typer.Exit(code=1)
