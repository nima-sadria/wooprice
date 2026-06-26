"""WooPrice Beta — wooprice adapters command group. Stub — B14."""

import typer

app = typer.Typer(help="Plugin adapter management.")

_NOT_IMPLEMENTED = "Not implemented in this phase. Adapter management begins in B14 (Plugin System)."


@app.command("list")
def adapters_list() -> None:
    """List installed adapters. [NOT IMPLEMENTED — B14]"""
    typer.echo(_NOT_IMPLEMENTED)


@app.command("install")
def adapters_install() -> None:
    """Install an adapter plugin. [NOT IMPLEMENTED — B14]"""
    typer.echo(_NOT_IMPLEMENTED)


@app.command("enable")
def adapters_enable() -> None:
    """Enable an installed adapter. [NOT IMPLEMENTED — B14]"""
    typer.echo(_NOT_IMPLEMENTED)


@app.command("disable")
def adapters_disable() -> None:
    """Disable an active adapter. [NOT IMPLEMENTED — B14]"""
    typer.echo(_NOT_IMPLEMENTED)


@app.command("remove")
def adapters_remove() -> None:
    """Uninstall an adapter. [NOT IMPLEMENTED — B14]"""
    typer.echo(_NOT_IMPLEMENTED)
