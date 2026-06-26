"""WooPrice Beta — wooprice ai command group. Stub — B12."""

import typer

app = typer.Typer(help="AI Foundation management.")

_NOT_IMPLEMENTED = "Not implemented in this phase. AI management begins in B12 (AI Insights Viewer)."


@app.command("status")
def ai_status() -> None:
    """Show AI feature status. [NOT IMPLEMENTED — B12]"""
    typer.echo(_NOT_IMPLEMENTED)


@app.command("insights")
def ai_insights() -> None:
    """List recent advisory insights. [NOT IMPLEMENTED — B12]"""
    typer.echo(_NOT_IMPLEMENTED)


@app.command("toggle")
def ai_toggle() -> None:
    """Enable or disable AI feature flag. [NOT IMPLEMENTED — B12]"""
    typer.echo(_NOT_IMPLEMENTED)
