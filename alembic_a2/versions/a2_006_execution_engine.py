"""A2.7 Execution Engine — executions, batches, items, and attempts

Revision ID: a2_006
Revises: a2_005
Create Date: 2026-06-26

Additive migration: creates 4 new tables (a2_executions, a2_execution_batches,
a2_execution_items, a2_execution_attempts).
No existing A2 tables or SQLite tables are modified.
Default production stack is unaffected.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a2_006"
down_revision: Union[str, None] = "a2_005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "a2_executions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("change_set_id", sa.String(36), nullable=False),
        sa.Column("change_set_revision_id", sa.String(36), nullable=False),
        sa.Column("change_set_digest", sa.String(64), nullable=False),
        sa.Column("confirmation_id", sa.String(36), nullable=False),
        sa.Column("confirmation_digest", sa.String(64), nullable=False),
        sa.Column("destination_channel", sa.String(256), nullable=False),
        sa.Column("scope", sa.String(512), nullable=False),
        sa.Column("source_snapshot_id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(256), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_a2_executions_idempotency_key"),
        sa.CheckConstraint(
            "status IN ('PENDING','RUNNING','SUCCEEDED','FAILED','BLOCKED','CANCELLED')",
            name="a2_executions_status_check",
        ),
    )
    op.create_index("ix_a2_executions_idempotency_key", "a2_executions", ["idempotency_key"], unique=True)
    op.create_index("ix_a2_executions_status", "a2_executions", ["status"])
    op.create_index("ix_a2_executions_change_set_id", "a2_executions", ["change_set_id"])

    op.create_table(
        "a2_execution_batches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "execution_id",
            sa.String(36),
            sa.ForeignKey("a2_executions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("batch_number", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("execution_id", "batch_number", name="uq_a2_execution_batches_exec_num"),
        sa.CheckConstraint(
            "status IN ('PENDING','RUNNING','SUCCEEDED','FAILED','BLOCKED','CANCELLED')",
            name="a2_execution_batches_status_check",
        ),
    )
    op.create_index("ix_a2_execution_batches_execution_id", "a2_execution_batches", ["execution_id"])

    op.create_table(
        "a2_execution_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "execution_id",
            sa.String(36),
            sa.ForeignKey("a2_executions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "batch_id",
            sa.String(36),
            sa.ForeignKey("a2_execution_batches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(256), nullable=False),
        sa.Column("product_id", sa.String(256), nullable=False),
        sa.Column("proposal_id", sa.String(36), nullable=False),
        sa.Column("proposal_hash", sa.String(64), nullable=False),
        sa.Column("safety_result_id", sa.String(36), nullable=False),
        sa.Column("rule_version_id", sa.String(36), nullable=False),
        sa.Column("proposed_price", sa.Numeric(14, 4), nullable=False),
        sa.Column("current_price", sa.Numeric(14, 4), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("freshness_verified", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_a2_execution_items_idempotency_key"),
        sa.CheckConstraint(
            "status IN ('PENDING','RUNNING','SUCCEEDED','FAILED','BLOCKED','SKIPPED')",
            name="a2_execution_items_status_check",
        ),
    )
    op.create_index("ix_a2_execution_items_execution_id", "a2_execution_items", ["execution_id"])
    op.create_index("ix_a2_execution_items_idempotency_key", "a2_execution_items", ["idempotency_key"], unique=True)
    op.create_index("ix_a2_execution_items_status", "a2_execution_items", ["status"])

    op.create_table(
        "a2_execution_attempts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "execution_item_id",
            sa.String(36),
            sa.ForeignKey("a2_execution_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attempt_number", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("adapter_name", sa.String(256), nullable=False),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("execution_item_id", "attempt_number", name="uq_a2_execution_attempts_item_num"),
        sa.CheckConstraint(
            "status IN ('SUCCEEDED','FAILED','BLOCKED')",
            name="a2_execution_attempts_status_check",
        ),
    )
    op.create_index("ix_a2_execution_attempts_item_id", "a2_execution_attempts", ["execution_item_id"])


def downgrade() -> None:
    op.drop_index("ix_a2_execution_attempts_item_id", table_name="a2_execution_attempts")
    op.drop_table("a2_execution_attempts")

    op.drop_index("ix_a2_execution_items_status", table_name="a2_execution_items")
    op.drop_index("ix_a2_execution_items_idempotency_key", table_name="a2_execution_items")
    op.drop_index("ix_a2_execution_items_execution_id", table_name="a2_execution_items")
    op.drop_table("a2_execution_items")

    op.drop_index("ix_a2_execution_batches_execution_id", table_name="a2_execution_batches")
    op.drop_table("a2_execution_batches")

    op.drop_index("ix_a2_executions_change_set_id", table_name="a2_executions")
    op.drop_index("ix_a2_executions_status", table_name="a2_executions")
    op.drop_index("ix_a2_executions_idempotency_key", table_name="a2_executions")
    op.drop_table("a2_executions")
