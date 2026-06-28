"""WooPrice Beta — create-admin CLI subcommand (BU2).

Creates the initial admin user in the Beta database.

Usage (after install.sh):
  wooprice create-admin
  wooprice create-admin --username admin --env-file /opt/wooprice-beta/.env.beta

This is a required post-install step for BU2.  The login endpoint returns 401
until at least one admin user exists.  Run once; re-running with an existing
username will fail safely with an error message.
"""

from __future__ import annotations

from typing import Optional

import typer

app = typer.Typer(
    name="create-admin",
    help="Create the initial WooPrice Beta admin user (required post-install step).",
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def create_admin(
    username: str = typer.Option(
        "admin",
        "--username",
        "-u",
        prompt="Admin username",
        help="Username for the new admin account.",
    ),
    password: str = typer.Option(
        ...,
        "--password",
        "-p",
        prompt="Admin password",
        hide_input=True,
        confirmation_prompt=True,
        help="Password for the new admin account.",
    ),
    env_file: Optional[str] = typer.Option(
        None,
        "--env-file",
        help="Path to .env.beta (default: /opt/wooprice-beta/.env.beta).",
    ),
) -> None:
    """Create the initial WooPrice Beta admin user.

    Run once after install.sh to create the admin account used to log in.
    """
    import os
    from pathlib import Path

    # Load .env.beta so BETA_DATABASE_URL and BETA_JWT_SECRET are set
    env_path = Path(env_file or "/opt/wooprice-beta/.env.beta")
    if env_path.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(env_path)
        except ImportError:
            # Fall back to manual parsing if python-dotenv not available
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())

    db_url = os.environ.get("BETA_DATABASE_URL", "")
    if not db_url:
        typer.echo(
            "ERROR: BETA_DATABASE_URL is not set.\n"
            "  Use --env-file /path/to/.env.beta or export BETA_DATABASE_URL.",
            err=True,
        )
        raise typer.Exit(1)

    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.beta.auth.password import hash_password
        from app.beta.auth.repository import create_user, get_user_by_username

        kwargs: dict = {}
        if db_url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}

        engine = create_engine(db_url, **kwargs)
        Session = sessionmaker(bind=engine)
        db = Session()

        try:
            existing = get_user_by_username(db, username)
            if existing:
                typer.echo(
                    f"ERROR: User '{username}' already exists. "
                    "Use a different username or delete the existing account first.",
                    err=True,
                )
                raise typer.Exit(1)

            hashed = hash_password(password)
            create_user(db, username=username, hashed_password=hashed, role="admin")

            typer.echo(f"  Admin user '{username}' created successfully.")
            typer.echo("  You can now log in at /login")
        finally:
            db.close()
            engine.dispose()

    except typer.Exit:
        raise
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(1)
