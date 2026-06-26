"""WooPrice Beta — wooprice scheduler command group. Stub — B11."""

import typer

app = typer.Typer(help="Scheduler management.")

_NOT_IMPLEMENTED = "Not implemented in this phase. Scheduler management begins in B11 (Scheduler Viewer)."


@app.command("list")
def scheduler_list() -> None:
    """List schedules. [NOT IMPLEMENTED — B11]"""
    typer.echo(_NOT_IMPLEMENTED)


@app.command("pause")
def scheduler_pause() -> None:
    """Pause a schedule. [NOT IMPLEMENTED — B11]"""
    typer.echo(_NOT_IMPLEMENTED)


@app.command("resume")
def scheduler_resume() -> None:
    """Resume a paused schedule. [NOT IMPLEMENTED — B11]"""
    typer.echo(_NOT_IMPLEMENTED)


@app.command("cancel")
def scheduler_cancel() -> None:
    """Cancel a schedule. [NOT IMPLEMENTED — B11]"""
    typer.echo(_NOT_IMPLEMENTED)
