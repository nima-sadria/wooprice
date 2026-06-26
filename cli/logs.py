"""WooPrice Beta — wooprice logs command group. Stub — B6."""

import typer

app = typer.Typer(help="Log streaming and export.")

_NOT_IMPLEMENTED = "Not implemented in this phase. Log streaming begins in B6 (Docker Runtime Foundation)."


@app.command("tail")
def logs_tail() -> None:
    """Stream logs live. [NOT IMPLEMENTED — B6]"""
    typer.echo(_NOT_IMPLEMENTED)


@app.command("show")
def logs_show() -> None:
    """Show recent log lines. [NOT IMPLEMENTED — B6]"""
    typer.echo(_NOT_IMPLEMENTED)


@app.command("export")
def logs_export() -> None:
    """Export logs to a file. [NOT IMPLEMENTED — B6]"""
    typer.echo(_NOT_IMPLEMENTED)
