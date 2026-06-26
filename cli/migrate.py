"""WooPrice Beta — wooprice migrate command group. Stub — B6."""

import typer

app = typer.Typer(help="Database migration management.")

_NOT_IMPLEMENTED = "Not implemented in this phase. Database migrations begin in B6 (Docker Runtime Foundation)."


@app.command("status")
def migrate_status() -> None:
    """Show current and pending migrations. [NOT IMPLEMENTED — B6]"""
    typer.echo(_NOT_IMPLEMENTED)


@app.command("up")
def migrate_up() -> None:
    """Run pending migrations. [NOT IMPLEMENTED — B6]"""
    typer.echo(_NOT_IMPLEMENTED)


@app.command("history")
def migrate_history() -> None:
    """Show migration history. [NOT IMPLEMENTED — B6]"""
    typer.echo(_NOT_IMPLEMENTED)
