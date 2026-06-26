"""WooPrice Beta — wooprice CLI entry point.

Registers all command groups and enforces the [BETA ENVIRONMENT] banner
on every invocation. Banner cannot be suppressed.

Usage: wooprice [--env <path>] [--json] [--no-color] <group> [subcommand]

Implementation of individual commands begins in B3–B14.
"""

import typer

app = typer.Typer(
    name="wooprice",
    help="WooPrice Beta management CLI. [BETA ENVIRONMENT]",
    no_args_is_help=False,
)

# Command groups registered in B5:
# app.add_typer(install_app, name="install")
# app.add_typer(configure_app, name="configure")
# app.add_typer(status_app, name="status")
# app.add_typer(health_app, name="health")
# app.add_typer(migrate_app, name="migrate")
# app.add_typer(backup_app, name="backup")
# app.add_typer(logs_app, name="logs")
# app.add_typer(update_app, name="update")
# app.add_typer(adapters_app, name="adapters")
# app.add_typer(channels_app, name="channels")
# app.add_typer(sources_app, name="sources")
# app.add_typer(users_app, name="users")
# app.add_typer(scheduler_app, name="scheduler")
# app.add_typer(ai_app, name="ai")
# app.add_typer(diagnostics_app, name="diagnostics")


if __name__ == "__main__":
    app()
