"""A2.5 change set engine — change sets, revisions, and items

Revision ID: a2_004
Revises: a2_003
Create Date: 2026-06-26

Additive migration: creates 3 new tables.
No existing A2 tables or SQLite tables are modified.
Default production stack is unaffected.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a2_004"
down_revision: Union[str, None] = "a2_003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "a2_change_sets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("state", sa.String(20), nullable=False, server_default="DRAFT"),
        sa.Column("destination_channel", sa.String(256), nullable=False),
        sa.Column("scope", sa.String(512), nullable=False),
        sa.Column("source_snapshot_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('DRAFT','READY','SUPERSEDED','ARCHIVED')",
            name="a2_change_sets_state_check",
        ),
    )
    op.create_index("ix_a2_change_sets_state", "a2_change_sets", ["state"])
    op.create_index(
        "ix_a2_change_sets_destination_channel",
        "a2_change_sets",
        ["destination_channel"],
    )
    op.create_index(
        "ix_a2_change_sets_source_snapshot_id",
        "a2_change_sets",
        ["source_snapshot_id"],
    )

    op.create_table(
        "a2_change_set_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "change_set_id",
            sa.String(36),
            sa.ForeignKey("a2_change_sets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("revision_number", sa.Integer, nullable=False),
        sa.Column("parent_revision_id", sa.String(36), nullable=True),
        sa.Column("digest", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "change_set_id",
            "revision_number",
            name="uq_a2_change_set_revisions_cs_revnum",
        ),
        sa.ForeignKeyConstraint(
            ["parent_revision_id"],
            ["a2_change_set_revisions.id"],
            ondelete="RESTRICT",
            name="fk_a2_change_set_revisions_parent",
        ),
    )
    op.create_index(
        "ix_a2_change_set_revisions_change_set_id",
        "a2_change_set_revisions",
        ["change_set_id"],
    )
    op.create_index(
        "ix_a2_change_set_revisions_digest",
        "a2_change_set_revisions",
        ["digest"],
    )

    op.create_table(
        "a2_change_set_items",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "revision_id",
            sa.String(36),
            sa.ForeignKey("a2_change_set_revisions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("product_id", sa.String(256), nullable=False),
        sa.Column("proposal_id", sa.String(36), nullable=False),
        sa.Column("proposal_hash", sa.String(64), nullable=False),
        sa.Column("safety_result_id", sa.String(36), nullable=False),
        sa.Column("rule_version_id", sa.String(36), nullable=False),
        sa.Column("proposed_price", sa.Numeric(14, 4), nullable=False),
        sa.Column("current_price", sa.Numeric(14, 4), nullable=True),
        sa.Column("delta", sa.Numeric(14, 4), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_a2_change_set_items_revision_id",
        "a2_change_set_items",
        ["revision_id"],
    )
    op.create_index(
        "ix_a2_change_set_items_product_id",
        "a2_change_set_items",
        ["product_id"],
    )
    op.create_index(
        "ix_a2_change_set_items_proposal_id",
        "a2_change_set_items",
        ["proposal_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_a2_change_set_items_proposal_id", table_name="a2_change_set_items")
    op.drop_index("ix_a2_change_set_items_product_id", table_name="a2_change_set_items")
    op.drop_index("ix_a2_change_set_items_revision_id", table_name="a2_change_set_items")
    op.drop_table("a2_change_set_items")

    op.drop_index("ix_a2_change_set_revisions_digest", table_name="a2_change_set_revisions")
    op.drop_index(
        "ix_a2_change_set_revisions_change_set_id",
        table_name="a2_change_set_revisions",
    )
    op.drop_table("a2_change_set_revisions")

    op.drop_index("ix_a2_change_sets_source_snapshot_id", table_name="a2_change_sets")
    op.drop_index("ix_a2_change_sets_destination_channel", table_name="a2_change_sets")
    op.drop_index("ix_a2_change_sets_state", table_name="a2_change_sets")
    op.drop_table("a2_change_sets")
