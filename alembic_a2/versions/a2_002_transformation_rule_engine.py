"""A2.3 transformation rule engine — rule definitions, versions, proposals, provenance, traces

Revision ID: a2_002
Revises: a2_001
Create Date: 2026-06-25

Additive migration: creates 5 new tables.
No existing A2 tables or SQLite tables are modified.
Default production stack is unaffected.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a2_002"
down_revision: Union[str, None] = "a2_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "a2_rule_definitions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("rule_type", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(256), nullable=False),
        sa.Column("priority", sa.Integer, nullable=False, server_default="100"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "rule_type IN ('cost_plus_profit', 'competitor_reference')",
            name="a2_rule_definitions_rule_type_check",
        ),
    )
    op.create_index("ix_a2_rule_definitions_rule_type", "a2_rule_definitions", ["rule_type"])
    op.create_index("ix_a2_rule_definitions_priority", "a2_rule_definitions", ["priority"])

    op.create_table(
        "a2_rule_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "rule_id",
            sa.String(36),
            sa.ForeignKey("a2_rule_definitions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer, nullable=False),
        sa.Column("parameters_json", sa.Text, nullable=False),
        sa.Column("is_published", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("rule_id", "version_number", name="uq_a2_rule_versions_rule_version"),
    )
    op.create_index("ix_a2_rule_versions_rule_id", "a2_rule_versions", ["rule_id"])
    op.create_index("ix_a2_rule_versions_is_published", "a2_rule_versions", ["is_published"])

    op.create_table(
        "a2_price_proposals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "rule_version_id",
            sa.String(36),
            sa.ForeignKey("a2_rule_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_snapshot_id", sa.String(36), nullable=False),
        sa.Column("input_cost", sa.Float, nullable=False),
        sa.Column("proposed_price", sa.Float, nullable=False),
        sa.Column("currency", sa.String(10), nullable=False),
        sa.Column("computation_digest", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_a2_price_proposals_rule_version", "a2_price_proposals", ["rule_version_id"])
    op.create_index("ix_a2_price_proposals_snapshot", "a2_price_proposals", ["source_snapshot_id"])
    op.create_index("ix_a2_price_proposals_digest", "a2_price_proposals", ["computation_digest"])

    op.create_table(
        "a2_proposal_provenance",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "proposal_id",
            sa.String(36),
            sa.ForeignKey("a2_price_proposals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_row_ref", sa.String(256), nullable=False),
        sa.Column("input_fields_json", sa.Text, nullable=False),
    )
    op.create_index("ix_a2_proposal_provenance_proposal", "a2_proposal_provenance", ["proposal_id"])

    op.create_table(
        "a2_execution_traces",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "proposal_id",
            sa.String(36),
            sa.ForeignKey("a2_price_proposals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("step_order", sa.Integer, nullable=False),
        sa.Column("step_name", sa.String(100), nullable=False),
        sa.Column("step_input_json", sa.Text, nullable=False),
        sa.Column("step_output_json", sa.Text, nullable=False),
        sa.Column("step_formula", sa.String(500), nullable=False),
    )
    op.create_index("ix_a2_execution_traces_proposal", "a2_execution_traces", ["proposal_id"])


def downgrade() -> None:
    op.drop_index("ix_a2_execution_traces_proposal", table_name="a2_execution_traces")
    op.drop_table("a2_execution_traces")
    op.drop_index("ix_a2_proposal_provenance_proposal", table_name="a2_proposal_provenance")
    op.drop_table("a2_proposal_provenance")
    op.drop_index("ix_a2_price_proposals_digest", table_name="a2_price_proposals")
    op.drop_index("ix_a2_price_proposals_snapshot", table_name="a2_price_proposals")
    op.drop_index("ix_a2_price_proposals_rule_version", table_name="a2_price_proposals")
    op.drop_table("a2_price_proposals")
    op.drop_index("ix_a2_rule_versions_is_published", table_name="a2_rule_versions")
    op.drop_index("ix_a2_rule_versions_rule_id", table_name="a2_rule_versions")
    op.drop_table("a2_rule_versions")
    op.drop_index("ix_a2_rule_definitions_priority", table_name="a2_rule_definitions")
    op.drop_index("ix_a2_rule_definitions_rule_type", table_name="a2_rule_definitions")
    op.drop_table("a2_rule_definitions")
