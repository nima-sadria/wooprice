"""WooPrice Beta — wooprice status command.

Local-only status: environment profile, config loaded/valid, storage paths.
No external network calls. No production service connections.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from app.beta.config import ConfigurationError, ConfigProfile, SECRET_FIELDS

app = typer.Typer(help="Show local environment and configuration status.")


@app.callback(invoke_without_command=True)
def status(
    env_file: Annotated[
        Path | None,
        typer.Option("--env-file", help="Path to .env file (auto-detected if omitted)"),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
) -> None:
    """Show environment profile, config loaded/valid, and storage paths."""
    from cli.shared.output import (
        console,
        print_banner,
        print_section,
        make_table,
    )
    from cli.shared.config_reader import load_config

    manager, profile = load_config(env_file)

    config_loaded = profile is not None
    config_valid = False
    config_errors: list[str] = []
    storage_path: str = "—"
    backup_path: str = "—"
    domain: str = "—"
    port: str = "—"
    env_label: str = "—"

    if config_loaded:
        from app.beta.config import ConfigValidator
        # Read env dict for validation (we already loaded it)
        env_dict: dict[str, str] = {}
        _ef = env_file or Path(".env")
        if _ef.exists():
            for line in _ef.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                if k:
                    env_dict[k] = v.strip()
        validator = ConfigValidator(check_paths=False)
        result = validator.validate(env_dict)
        config_valid = result.is_valid
        config_errors = [str(e) for e in result.errors]
        storage_path = env_dict.get("BETA_STORAGE_PATH", "—")
        backup_path = env_dict.get("BETA_BACKUP_PATH", "—")
        domain = env_dict.get("BETA_DOMAIN", "—")
        port = env_dict.get("BETA_PORT", "—")
        env_label = env_dict.get("BETA_ENV", "—")

    data = {
        "profile": profile.value if profile else "unknown",
        "config_loaded": config_loaded,
        "config_valid": config_valid,
        "config_errors": config_errors,
        "domain": domain,
        "port": port,
        "env": env_label,
        "storage_path": storage_path,
        "backup_path": backup_path,
    }

    if json_output:
        typer.echo(json.dumps(data, indent=2))
        return

    print_banner(profile)  # banner only in non-JSON mode

    print_section("Configuration")
    loaded_str = "[green]LOADED[/green]" if config_loaded else "[red]NOT LOADED[/red]"
    valid_str = "[green]VALID[/green]" if config_valid else ("[red]INVALID[/red]" if config_loaded else "[dim]—[/dim]")
    console.print(f"  Config:          {loaded_str}")
    console.print(f"  Validation:      {valid_str}")
    if config_errors:
        for err in config_errors[:5]:
            console.print(f"  [red]  ✗ {err}[/red]")
        if len(config_errors) > 5:
            console.print(f"  [dim]  ... and {len(config_errors) - 5} more[/dim]")

    print_section("Environment")
    console.print(f"  Profile:         {profile.value if profile else 'unknown'}")
    console.print(f"  BETA_ENV:        {env_label}")
    console.print(f"  Domain:          {domain}:{port}" if domain != "—" else "  Domain:          —")

    print_section("Paths")
    storage_exists = Path(storage_path).exists() if storage_path != "—" else False
    backup_exists = Path(backup_path).exists() if backup_path != "—" else False
    console.print(f"  Storage path:    {storage_path}  {'[green][exists][/green]' if storage_exists else '[dim][not created][/dim]'}")
    console.print(f"  Backup path:     {backup_path}  {'[green][exists][/green]' if backup_exists else '[dim][not created][/dim]'}")
    console.print()
