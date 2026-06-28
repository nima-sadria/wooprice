"""WooPrice Beta — Alembic migration environment (BU2).

Reads BETA_DATABASE_URL from the environment (set in .env.beta).
target_metadata is wired to BetaBase so that `alembic --autogenerate`
detects model changes from beta_001 onward.

Usage:
  alembic -c alembic_beta.ini upgrade head
  alembic -c alembic_beta.ini current
  alembic -c alembic_beta.ini history
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

database_url = os.environ.get("BETA_DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

# Import models so their tables are registered on BetaBase.metadata before
# Alembic inspects it.  The import chain is: models → database (BetaBase).
# The database module is safe to import without a live connection.
from app.beta.database import BetaBase  # noqa: E402
from app.beta.auth import models as _auth_models  # noqa: E402, F401

target_metadata = BetaBase.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
