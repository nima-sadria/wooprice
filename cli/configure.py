"""WooPrice Beta — wooprice configure command group.

Configuration management: show, verify.
Uses B3 ConfigurationManager and ConfigValidator.
No file writes in B5. Secrets always redacted in output.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(help="Configuration management.")


@app.command("show")
def configure_show(
    env_file: Annotated[
        Path | None,
        typer.Option("--env-file", help="Path to .env file"),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
) -> None:
    """Display current configuration. Secrets are always redacted."""
    from cli.shared.output import console, print_banner, print_section, print_error
    from cli.shared.config_reader import load_config, redact_env_dict
    from app.beta.config import ConfigurationError

    manager, profile = load_config(env_file)

    if profile is None:
        print_banner(None)
        print_error(
            "Configuration could not be loaded.",
            suggestion="Pass --env-file <path> or create a .env file in the current directory.",
        )
        raise typer.Exit(code=1)

    _env_path = env_file or Path(".env")
    env_dict: dict[str, str] = {}
    if _env_path.exists():
        for line in _env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            if k:
                env_dict[k] = v.strip()

    redacted = redact_env_dict(env_dict)

    if json_output:
        typer.echo(json.dumps(redacted, indent=2))
        return

    print_banner(profile)
    print_section("Configuration (secrets redacted)")

    ordered_keys = [
        "BETA_ENV", "BETA_DOMAIN", "BETA_PORT", "BETA_SSL_MODE",
        "BETA_TIMEZONE", "BETA_CURRENCY", "BETA_ADMIN_EMAIL",
        "BETA_POSTGRES_DB", "BETA_POSTGRES_USER",
        "BETA_DATABASE_URL",
        "BETA_NEXTCLOUD_URL", "BETA_NEXTCLOUD_FILE_PATH", "BETA_NEXTCLOUD_USERNAME",
        "BETA_WOOCOMMERCE_URL",
        "BETA_STORAGE_PATH", "BETA_BACKUP_PATH",
        "BETA_LOG_LEVEL",
        # Secrets shown as redacted
        "BETA_JWT_SECRET", "BETA_REST_API_SECRET",
        "BETA_POSTGRES_PASSWORD", "BETA_NEXTCLOUD_PASSWORD",
        "BETA_WOOCOMMERCE_KEY", "BETA_WOOCOMMERCE_SECRET",
    ]

    for key in ordered_keys:
        if key in redacted:
            value = redacted[key]
            style = "[dim]" if value == "[REDACTED]" else ""
            end_style = "[/dim]" if value == "[REDACTED]" else ""
            console.print(f"  {key:<36} {style}{value}{end_style}")

    # Any remaining keys not in the ordered list
    for key, value in sorted(redacted.items()):
        if key not in ordered_keys:
            console.print(f"  {key:<36} {value}")

    console.print()


@app.command("verify")
def configure_verify(
    env_file: Annotated[
        Path | None,
        typer.Option("--env-file", help="Path to .env file"),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
) -> None:
    """Verify configuration using B3 ConfigValidator. Never modifies any file."""
    from cli.shared.output import console, print_banner, print_section, print_success, print_error
    from cli.shared.config_reader import load_config, validate_env_file
    from app.beta.config import SECRET_FIELDS

    manager, profile = load_config(env_file)
    if not json_output:
        print_banner(profile)

    result = validate_env_file(env_file)

    if json_output:
        errors = [{"field": e.field, "message": e.message} for e in result.errors]
        typer.echo(json.dumps({
            "valid": result.is_valid,
            "error_count": len(result.errors),
            "errors": errors,
        }, indent=2))
        if not result.is_valid:
            raise typer.Exit(code=1)
        return

    print_section("Configuration Verification")

    if result.is_valid:
        print_success("Configuration is valid — all 22 required fields pass validation.")
    else:
        console.print(f"  [bold red]✗ {len(result.errors)} validation error(s):[/bold red]")
        for err in result.errors:
            field = err.field
            msg = err.message
            # Never print raw secret values
            display = "[REDACTED]" if field in SECRET_FIELDS else repr(err.value)
            console.print(f"    [red]✗[/red] {field}={display}: {msg}")

    if result.warnings:
        for w in result.warnings:
            console.print(f"  [yellow]⚠[/yellow]  {w}")

    console.print()
    if not result.is_valid:
        raise typer.Exit(code=1)


@app.command("get")
def configure_get(
    field: Annotated[str, typer.Argument(help="Config field name (e.g., BETA_LOG_LEVEL)")],
    env_file: Annotated[
        Path | None,
        typer.Option("--env-file", help="Path to .env file"),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
) -> None:
    """Show the current value of a single configuration field (secrets redacted)."""
    from cli.shared.output import console, print_banner, print_section
    from cli.shared.config_reader import load_config
    from app.beta.runtime_config import RuntimeConfigService

    _, profile = load_config(env_file)
    env_path = env_file or Path(".env")
    svc = RuntimeConfigService(env_file=env_path)
    record = svc.get(field)

    if json_output:
        typer.echo(json.dumps(record.to_dict(), indent=2))
        return

    print_banner(profile)
    print_section(f"Configuration: {record.field_name}")
    value_display = "[REDACTED]" if record.is_secret else (record.current_value or "[not set]")
    console.print(f"  {record.field_name:<36} {value_display}")
    if record.is_secret:
        console.print("  [dim]This field is a secret and cannot be displayed.[/dim]")
    elif record.is_installer_only:
        console.print("  [dim]This field is installer-only and cannot be changed at runtime.[/dim]")
    elif not record.is_editable:
        console.print("  [dim]This field is not editable via runtime configuration.[/dim]")
    console.print()


@app.command("set")
def configure_set(
    field: Annotated[str, typer.Argument(help="Config field name (e.g., BETA_LOG_LEVEL)")],
    value: Annotated[str, typer.Argument(help="New value to set")],
    env_file: Annotated[
        Path | None,
        typer.Option("--env-file", help="Path to .env file"),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
) -> None:
    """Set a runtime configuration field. Only editable fields are accepted.

    Secrets and installer-only fields are always rejected.
    The value is validated before any write occurs.
    """
    from cli.shared.output import console, print_banner, print_section, print_error
    from cli.shared.config_reader import load_config
    from app.beta.runtime_config import RuntimeConfigService

    _, profile = load_config(env_file)
    env_path = env_file or Path(".env")
    svc = RuntimeConfigService(env_file=env_path)
    result = svc.set(field, value, changed_by="cli")

    if json_output:
        out = {
            "success": result.success,
            "field_name": result.field_name,
            "new_value": result.new_value,
            "error": result.error,
        }
        typer.echo(json.dumps(out, indent=2))
        if not result.success:
            raise typer.Exit(code=1)
        return

    print_banner(profile)

    if not result.success:
        print_error(
            f"Cannot set {result.field_name}",
            suggestion=result.error or "Unknown error.",
        )
        raise typer.Exit(code=1)

    print_section("Configuration Updated")
    console.print(f"  [green]✓[/green]  {result.field_name} = {result.new_value}")
    if result.old_value is not None and result.old_value != result.new_value:
        console.print(f"      [dim](was: {result.old_value})[/dim]")
    console.print()
