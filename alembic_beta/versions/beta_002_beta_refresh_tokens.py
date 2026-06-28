"""beta_002 — create beta_refresh_tokens table

Revision ID: beta_002
Revises: beta_001
Create Date: 2026-06-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "beta_002"
down_revision = "beta_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "beta_refresh_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["beta_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(op.f("ix_beta_refresh_tokens_id"), "beta_refresh_tokens", ["id"], unique=False)
    op.create_index(
        op.f("ix_beta_refresh_tokens_token_hash"), "beta_refresh_tokens", ["token_hash"], unique=True
    )
    op.create_index(
        op.f("ix_beta_refresh_tokens_user_id"), "beta_refresh_tokens", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_beta_refresh_tokens_user_id"), table_name="beta_refresh_tokens")
    op.drop_index(op.f("ix_beta_refresh_tokens_token_hash"), table_name="beta_refresh_tokens")
    op.drop_index(op.f("ix_beta_refresh_tokens_id"), table_name="beta_refresh_tokens")
    op.drop_table("beta_refresh_tokens")
