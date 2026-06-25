"""A2.4 safety policy engine — policies, versions, safety results, override logs

Revision ID: a2_003
Revises: a2_002
Create Date: 2026-06-25

Additive migration: creates 4 new tables.
No existing A2 tables or SQLite tables are modified.
Default production stack is unaffected.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a2_003"
down_revision: Union[str, None] = "a2_002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "a2_safety_policies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("policy_type", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(256), nullable=False),
        sa.Column("scope_type", sa.String(64), nullable=False, server_default="global"),
        sa.Column("scope_value", sa.String(256), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "policy_type IN ('percentage_change','missing_zero','extra_zero','historical_anomaly')",
            name="a2_safety_policies_policy_type_check",
        ),
        sa.CheckConstraint(
            "scope_type IN ('global','category','brand','user','channel')",
            name="a2_safety_policies_scope_type_check",
        ),
    )
    op.create_index("ix_a2_safety_policies_policy_type", "a2_safety_policies", ["policy_type"])
    op.create_index("ix_a2_safety_policies_scope_type", "a2_safety_policies", ["scope_type"])
    op.create_index("ix_a2_safety_policies_is_active", "a2_safety_policies", ["is_active"])

    op.create_table(
        "a2_policy_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "policy_id",
            sa.String(36),
            sa.ForeignKey("a2_safety_policies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer, nullable=False),
        sa.Column("mode", sa.String(20), nullable=False, server_default="WARN"),
        sa.Column("parameters_json", sa.Text, nullable=False),
        sa.Column("is_published", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "mode IN ('WARN','BLOCK','REQUIRE_OVERRIDE')",
            name="a2_policy_versions_mode_check",
        ),
        sa.UniqueConstraint("policy_id", "version_number", name="uq_a2_policy_versions_policy_version"),
    )
    op.create_index("ix_a2_policy_versions_policy_id", "a2_policy_versions", ["policy_id"])
    op.create_index("ix_a2_policy_versions_is_published", "a2_policy_versions", ["is_published"])
    op.create_index("ix_a2_policy_versions_mode", "a2_policy_versions", ["mode"])

    op.create_table(
        "a2_safety_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("proposal_id", sa.String(36), nullable=False),
        sa.Column(
            "policy_version_id",
            sa.String(36),
            sa.ForeignKey("a2_policy_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("policy_name", sa.String(256), nullable=False),
        sa.Column("policy_mode", sa.String(20), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("triggered_threshold", sa.String(256), nullable=True),
        sa.Column("evaluated_value", sa.String(256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('PASS','WARN','BLOCK','REQUIRE_OVERRIDE')",
            name="a2_safety_results_outcome_check",
        ),
    )
    op.create_index("ix_a2_safety_results_proposal_id", "a2_safety_results", ["proposal_id"])
    op.create_index("ix_a2_safety_results_outcome", "a2_safety_results", ["outcome"])
    op.create_index("ix_a2_safety_results_policy_version", "a2_safety_results", ["policy_version_id"])

    op.create_table(
        "a2_override_logs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "safety_result_id",
            sa.String(36),
            sa.ForeignKey("a2_safety_results.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("authorizing_user", sa.String(256), nullable=False),
        sa.Column("justification", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_a2_override_logs_safety_result", "a2_override_logs", ["safety_result_id"])


def downgrade() -> None:
    op.drop_index("ix_a2_override_logs_safety_result", table_name="a2_override_logs")
    op.drop_table("a2_override_logs")
    op.drop_index("ix_a2_safety_results_policy_version", table_name="a2_safety_results")
    op.drop_index("ix_a2_safety_results_outcome", table_name="a2_safety_results")
    op.drop_index("ix_a2_safety_results_proposal_id", table_name="a2_safety_results")
    op.drop_table("a2_safety_results")
    op.drop_index("ix_a2_policy_versions_mode", table_name="a2_policy_versions")
    op.drop_index("ix_a2_policy_versions_is_published", table_name="a2_policy_versions")
    op.drop_index("ix_a2_policy_versions_policy_id", table_name="a2_policy_versions")
    op.drop_table("a2_policy_versions")
    op.drop_index("ix_a2_safety_policies_is_active", table_name="a2_safety_policies")
    op.drop_index("ix_a2_safety_policies_scope_type", table_name="a2_safety_policies")
    op.drop_index("ix_a2_safety_policies_policy_type", table_name="a2_safety_policies")
    op.drop_table("a2_safety_policies")
