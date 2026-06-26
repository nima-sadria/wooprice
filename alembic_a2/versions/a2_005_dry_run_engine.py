"""A2.6 Dry Run Engine — dry runs, per-item results, and seller confirmations

Revision ID: a2_005
Revises: a2_004
Create Date: 2026-06-26

Additive migration: creates 3 new tables (a2_dry_runs, a2_dry_run_results,
a2_seller_confirmations).
No existing A2 tables or SQLite tables are modified.
Default production stack is unaffected.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a2_005"
down_revision: Union[str, None] = "a2_004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "a2_dry_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("change_set_id", sa.String(36), nullable=False),
        sa.Column("change_set_revision_id", sa.String(36), nullable=False),
        sa.Column("change_set_digest", sa.String(64), nullable=False),
        sa.Column("digest_verified", sa.Boolean, nullable=False),
        sa.Column("validation_result", sa.String(20), nullable=False),
        sa.Column("execution_eligible", sa.Boolean, nullable=False),
        sa.Column("proposal_count", sa.Integer, nullable=False),
        sa.Column("blocked_count", sa.Integer, nullable=False),
        sa.Column("warning_count", sa.Integer, nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "validation_result IN ('PASS','WARN','BLOCK')",
            name="a2_dry_runs_validation_result_check",
        ),
    )
    op.create_index("ix_a2_dry_runs_change_set_id", "a2_dry_runs", ["change_set_id"])
    op.create_index(
        "ix_a2_dry_runs_change_set_revision_id",
        "a2_dry_runs",
        ["change_set_revision_id"],
    )
    op.create_index("ix_a2_dry_runs_validation_result", "a2_dry_runs", ["validation_result"])

    op.create_table(
        "a2_dry_run_results",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "dry_run_id",
            sa.String(36),
            sa.ForeignKey("a2_dry_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("product_id", sa.String(256), nullable=False),
        sa.Column("proposal_id", sa.String(36), nullable=False),
        sa.Column("proposal_hash", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('PASS','WARN','BLOCK')",
            name="a2_dry_run_results_outcome_check",
        ),
    )
    op.create_index(
        "ix_a2_dry_run_results_dry_run_id",
        "a2_dry_run_results",
        ["dry_run_id"],
    )
    op.create_index(
        "ix_a2_dry_run_results_outcome",
        "a2_dry_run_results",
        ["outcome"],
    )

    op.create_table(
        "a2_seller_confirmations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "dry_run_id",
            sa.String(36),
            sa.ForeignKey("a2_dry_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("change_set_digest", sa.String(64), nullable=False),
        sa.Column("confirmed_by", sa.String(256), nullable=False),
        sa.Column("is_valid", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidation_reason", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_a2_seller_confirmations_dry_run_id",
        "a2_seller_confirmations",
        ["dry_run_id"],
    )
    op.create_index(
        "ix_a2_seller_confirmations_change_set_digest",
        "a2_seller_confirmations",
        ["change_set_digest"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_a2_seller_confirmations_change_set_digest",
        table_name="a2_seller_confirmations",
    )
    op.drop_index(
        "ix_a2_seller_confirmations_dry_run_id",
        table_name="a2_seller_confirmations",
    )
    op.drop_table("a2_seller_confirmations")

    op.drop_index("ix_a2_dry_run_results_outcome", table_name="a2_dry_run_results")
    op.drop_index(
        "ix_a2_dry_run_results_dry_run_id",
        table_name="a2_dry_run_results",
    )
    op.drop_table("a2_dry_run_results")

    op.drop_index("ix_a2_dry_runs_validation_result", table_name="a2_dry_runs")
    op.drop_index(
        "ix_a2_dry_runs_change_set_revision_id",
        table_name="a2_dry_runs",
    )
    op.drop_index("ix_a2_dry_runs_change_set_id", table_name="a2_dry_runs")
    op.drop_table("a2_dry_runs")
