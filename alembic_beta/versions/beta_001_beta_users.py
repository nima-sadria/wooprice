"""beta_001 — create beta_users table

Revision ID: beta_001
Revises:
Create Date: 2026-06-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "beta_001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "beta_users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=150), nullable=False),
        sa.Column("hashed_password", sa.String(length=512), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False, server_default="viewer"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )
    op.create_index(op.f("ix_beta_users_id"), "beta_users", ["id"], unique=False)
    op.create_index(op.f("ix_beta_users_username"), "beta_users", ["username"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_beta_users_username"), table_name="beta_users")
    op.drop_index(op.f("ix_beta_users_id"), table_name="beta_users")
    op.drop_table("beta_users")
