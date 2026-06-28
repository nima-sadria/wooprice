"""beta_003 — create beta_login_audit table

Revision ID: beta_003
Revises: beta_002
Create Date: 2026-06-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "beta_003"
down_revision = "beta_002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "beta_login_audit",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=150), nullable=False),
        sa.Column("event", sa.String(length=50), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_beta_login_audit_id"), "beta_login_audit", ["id"], unique=False)
    op.create_index(
        op.f("ix_beta_login_audit_username"), "beta_login_audit", ["username"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_beta_login_audit_username"), table_name="beta_login_audit")
    op.drop_index(op.f("ix_beta_login_audit_id"), table_name="beta_login_audit")
    op.drop_table("beta_login_audit")
