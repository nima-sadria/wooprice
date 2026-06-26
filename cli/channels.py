"""WooPrice Beta — wooprice channels command group. Stub — B8."""

import typer

app = typer.Typer(help="Channel configuration.")

_NOT_IMPLEMENTED = "Not implemented in this phase. Channel configuration begins in B8 (Read-only A2 Inspector UI)."


@app.command("list")
def channels_list() -> None:
    """List configured channels. [NOT IMPLEMENTED — B8]"""
    typer.echo(_NOT_IMPLEMENTED)


@app.command("add")
def channels_add() -> None:
    """Add a channel. [NOT IMPLEMENTED — B8]"""
    typer.echo(_NOT_IMPLEMENTED)


@app.command("test")
def channels_test() -> None:
    """Test channel connectivity. [NOT IMPLEMENTED — B8]"""
    typer.echo(_NOT_IMPLEMENTED)


@app.command("remove")
def channels_remove() -> None:
    """Remove a channel. [NOT IMPLEMENTED — B8]"""
    typer.echo(_NOT_IMPLEMENTED)
