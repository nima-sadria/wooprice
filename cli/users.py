"""WooPrice Beta — wooprice users command group. Stub — B7."""

import typer

app = typer.Typer(help="User management.")

_NOT_IMPLEMENTED = "Not implemented in this phase. User management begins in B7 (Authentication Foundation)."


@app.command("list")
def users_list() -> None:
    """List all users. [NOT IMPLEMENTED — B7]"""
    typer.echo(_NOT_IMPLEMENTED)


@app.command("create")
def users_create() -> None:
    """Create a new user. [NOT IMPLEMENTED — B7]"""
    typer.echo(_NOT_IMPLEMENTED)


@app.command("set-role")
def users_set_role() -> None:
    """Set user role. [NOT IMPLEMENTED — B7]"""
    typer.echo(_NOT_IMPLEMENTED)


@app.command("deactivate")
def users_deactivate() -> None:
    """Deactivate a user. [NOT IMPLEMENTED — B7]"""
    typer.echo(_NOT_IMPLEMENTED)


@app.command("reset-pw")
def users_reset_pw() -> None:
    """Reset a user password. [NOT IMPLEMENTED — B7]"""
    typer.echo(_NOT_IMPLEMENTED)
