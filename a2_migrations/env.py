"""Alembic environment for A2 PostgreSQL migrations.

Separate from alembic/ (SQLite). Run with:
  alembic -c alembic_a2.ini upgrade head
"""
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Import models so A2Base.metadata is populated before Alembic inspects it
import app.a2.models  # noqa: F401
from app.a2.database import A2Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = A2Base.metadata


def _get_url() -> str:
    url = os.environ.get("POSTGRES_URL")
    if not url:
        raise RuntimeError(
            "POSTGRES_URL environment variable is required for A2 migrations. "
            "Example: postgresql://wooprice:password@localhost:5432/wooprice_a2"
        )
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    cfg = config.get_section(config.config_ini_section, {})
    cfg["sqlalchemy.url"] = _get_url()
    connectable = engine_from_config(cfg, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
