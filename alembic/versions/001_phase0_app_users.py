"""Phase 0: Create app_users table for DB-backed access control.

Revision ID: 001
Revises:
Create Date: 2026-06-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "app_users" not in inspector.get_table_names():
        op.create_table(
            "app_users",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("username", sa.String, nullable=False, unique=True, index=True),
            sa.Column("display_name", sa.String, nullable=True),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
            sa.Column("is_admin", sa.Boolean, nullable=False, server_default="0"),
            sa.Column("permission_version", sa.Integer, nullable=False, server_default="1"),
            sa.Column("notes", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime, nullable=True),
        )


def downgrade() -> None:
    op.drop_table("app_users")
