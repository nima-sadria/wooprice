"""WooPrice Beta — wooprice backup command group. Stub — B15."""

import typer

app = typer.Typer(help="Backup and restore.")

_NOT_IMPLEMENTED = "Not implemented in this phase. Backup/restore begins in B15 (Backup + Update System)."


@app.command("create")
def backup_create() -> None:
    """Create a backup. [NOT IMPLEMENTED — B15]"""
    typer.echo(_NOT_IMPLEMENTED)


@app.command("list")
def backup_list() -> None:
    """List available backups. [NOT IMPLEMENTED — B15]"""
    typer.echo(_NOT_IMPLEMENTED)


@app.command("restore")
def backup_restore() -> None:
    """Restore from a backup. [NOT IMPLEMENTED — B15]"""
    typer.echo(_NOT_IMPLEMENTED)
