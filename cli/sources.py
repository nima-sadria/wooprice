"""WooPrice Beta — wooprice sources command group. Stub — B8."""

import typer

app = typer.Typer(help="Source configuration.")

_NOT_IMPLEMENTED = "Not implemented in this phase. Source configuration begins in B8 (Read-only A2 Inspector UI)."


@app.command("list")
def sources_list() -> None:
    """List configured sources. [NOT IMPLEMENTED — B8]"""
    typer.echo(_NOT_IMPLEMENTED)


@app.command("add")
def sources_add() -> None:
    """Add a source. [NOT IMPLEMENTED — B8]"""
    typer.echo(_NOT_IMPLEMENTED)


@app.command("test")
def sources_test() -> None:
    """Test source connectivity. [NOT IMPLEMENTED — B8]"""
    typer.echo(_NOT_IMPLEMENTED)


@app.command("remove")
def sources_remove() -> None:
    """Remove a source. [NOT IMPLEMENTED — B8]"""
    typer.echo(_NOT_IMPLEMENTED)
