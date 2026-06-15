"""Add email column to app_users for email-based login resolution.

Revision ID: 002
Revises: 001
Create Date: 2026-06-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_cols = {c["name"] for c in inspector.get_columns("app_users")}
    if "email" not in existing_cols:
        with op.batch_alter_table("app_users") as batch_op:
            batch_op.add_column(sa.Column("email", sa.String(), nullable=True))
            batch_op.create_index("ix_app_users_email", ["email"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("app_users") as batch_op:
        batch_op.drop_index("ix_app_users_email")
        batch_op.drop_column("email")
