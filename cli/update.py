"""WooPrice Beta — wooprice update command group. Stub — B15."""

import typer

app = typer.Typer(help="Version management.")

_NOT_IMPLEMENTED = "Not implemented in this phase. Update system begins in B15 (Backup + Update System)."


@app.command("check")
def update_check() -> None:
    """Check for available updates. [NOT IMPLEMENTED — B15]"""
    typer.echo(_NOT_IMPLEMENTED)


@app.command("apply")
def update_apply() -> None:
    """Apply an update. [NOT IMPLEMENTED — B15]"""
    typer.echo(_NOT_IMPLEMENTED)
