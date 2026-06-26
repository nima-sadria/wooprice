"""WooPrice Beta — wooprice install command.

Wraps B4 Installer Foundation. In B5: dry-run mode only.
No Docker execution. No network calls. No production deployment.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(help="Installation management.")

_DEFAULT_INSTALL_DIR = Path("/opt/wooprice-beta")


def _env_file_to_installer_config(env_file: Path | None):  # type: ignore[return]
    """Load an InstallerConfig from a .env file, auto-generating missing secrets."""
    from installer.installer_core import InstallerConfig, generate_secrets, apply_secrets

    config = InstallerConfig()

    if env_file is not None and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip()
            # Map BETA_* env vars to InstallerConfig fields
            _MAP = {
                "BETA_DOMAIN": "domain",
                "BETA_ADMIN_EMAIL": "admin_email",
                "BETA_NEXTCLOUD_URL": "nextcloud_url",
                "BETA_NEXTCLOUD_FILE_PATH": "nextcloud_file_path",
                "BETA_NEXTCLOUD_USERNAME": "nextcloud_username",
                "BETA_NEXTCLOUD_PASSWORD": "nextcloud_password",
                "BETA_WOOCOMMERCE_URL": "woocommerce_url",
                "BETA_WOOCOMMERCE_KEY": "woocommerce_key",
                "BETA_WOOCOMMERCE_SECRET": "woocommerce_secret",
                "BETA_ENV": "env",
                "BETA_PORT": "port",
                "BETA_SSL_MODE": "ssl_mode",
                "BETA_POSTGRES_DB": "postgres_db",
                "BETA_POSTGRES_USER": "postgres_user",
                "BETA_POSTGRES_PASSWORD": "postgres_password",
                "BETA_JWT_SECRET": "jwt_secret",
                "BETA_REST_API_SECRET": "rest_api_secret",
                "BETA_TIMEZONE": "timezone",
                "BETA_CURRENCY": "currency",
                "BETA_STORAGE_PATH": "storage_path",
                "BETA_BACKUP_PATH": "backup_path",
                "BETA_LOG_LEVEL": "log_level",
            }
            field = _MAP.get(k)
            if field is not None:
                if field == "port":
                    try:
                        object.__setattr__(config, field, int(v))
                    except ValueError:
                        pass
                else:
                    object.__setattr__(config, field, v)

    # Auto-generate any missing secrets
    if config.needs_secret_generation():
        sec = generate_secrets()
        config = apply_secrets(config, sec)

    return config


@app.command("dry-run")
def install_dry_run(
    env_file: Annotated[
        Path | None,
        typer.Option("--env-file", help="Path to .env file to seed installer values"),
    ] = None,
    install_dir: Annotated[
        Path,
        typer.Option("--install-dir", help="Target installation directory"),
    ] = _DEFAULT_INSTALL_DIR,
) -> None:
    """Simulate a full installation without writing any files.

    Loads values from --env-file if provided; auto-generates secrets.
    Prints: planned files, planned directories, masked secrets summary,
    validation result. Writes nothing to disk.
    """
    from cli.shared.output import console, print_banner, print_section, print_success, print_error
    from cli.shared.config_reader import load_config
    from cli.shared.env_guard import require_beta_env, ProductionResourceError
    from installer.installer_core import dry_run_install

    manager, profile = load_config(env_file)
    print_banner(profile)

    # Block production profile
    if profile is not None:
        try:
            require_beta_env(profile)
        except ProductionResourceError as e:
            from cli.shared.output import print_production_warning
            print_production_warning()
            print_error(str(e))
            raise typer.Exit(code=1)

    config = _env_file_to_installer_config(env_file)
    result = dry_run_install(config, install_dir)

    print_section("Prerequisite Checks")
    for pre in result.prerequisites:
        icon = "[green]✓[/green]" if pre.passed else "[red]✗[/red]"
        console.print(f"  {icon}  {pre.name}: {pre.message}")
        if not pre.passed and pre.fix:
            console.print(f"     [dim]Fix: {pre.fix}[/dim]")

    print_section("Files That Would Be Written")
    for f in result.files_would_be_written:
        console.print(f"  [dim]{f}[/dim]")

    print_section("Directories That Would Be Created")
    for d in result.storage_dirs:
        console.print(f"  [dim]{d}[/dim]")

    print_section("Secrets")
    if result.secrets_would_be_generated:
        console.print("  [dim]Secrets would be auto-generated (masked below):[/dim]")
    # Show masked summary — never plain text
    from installer.installer_core import InstallerSecrets
    masked = InstallerSecrets(
        jwt_secret=config.jwt_secret,
        rest_api_secret=config.rest_api_secret,
        postgres_password=config.postgres_password,
    ).masked_summary()
    for k, v in masked.items():
        console.print(f"  {k:<24} {v}")

    print_section("Validation Result")
    from installer.installer_core import validate_generated_config
    validation = validate_generated_config(env_content=result.env_content)
    if validation.is_valid:
        print_success("Generated configuration is valid.")
    else:
        console.print(f"  [bold red]✗ {len(validation.errors)} validation error(s):[/bold red]")
        from app.beta.config import SECRET_FIELDS
        for err in validation.errors:
            display = "[REDACTED]" if err.field in SECRET_FIELDS else repr(err.value)
            console.print(f"    [red]✗[/red] {err.field}={display}: {err.message}")

    console.print()
    console.print("[bold cyan]  Dry-run complete. Nothing was written to disk.[/bold cyan]\n")
