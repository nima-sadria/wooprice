"""A2.2 source adapter framework — initial schema

Revision ID: a2_001
Revises:
Create Date: 2026-06-24

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a2_001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "source_definitions",
        sa.Column("source_id", sa.String(128), primary_key=True),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(256), nullable=False),
        sa.Column("config_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "source_snapshots",
        sa.Column("snapshot_id", sa.String(36), primary_key=True),
        sa.Column(
            "source_id",
            sa.String(128),
            sa.ForeignKey("source_definitions.source_id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("schema_hash", sa.String(64), nullable=False),
        sa.Column("row_count", sa.Integer, nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
    )
    op.create_index(
        "ix_source_snapshots_source_id",
        "source_snapshots",
        ["source_id"],
    )

    op.create_table(
        "source_row_provenance",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "source_id",
            sa.String(128),
            sa.ForeignKey("source_definitions.source_id"),
            nullable=False,
        ),
        sa.Column("source_row_ref", sa.String(256), nullable=False),
        sa.Column(
            "source_snapshot_id",
            sa.String(36),
            sa.ForeignKey("source_snapshots.snapshot_id"),
            nullable=False,
        ),
        sa.Column("source_row_hash", sa.String(64), nullable=False),
    )
    op.create_index(
        "ix_source_row_provenance_snapshot",
        "source_row_provenance",
        ["source_snapshot_id"],
    )
    op.create_index(
        "ix_source_row_provenance_source_ref",
        "source_row_provenance",
        ["source_id", "source_row_ref"],
    )

    op.create_table(
        "source_checkpoints",
        sa.Column(
            "source_id",
            sa.String(128),
            sa.ForeignKey("source_definitions.source_id"),
            primary_key=True,
        ),
        sa.Column("checkpoint_value", sa.String(512), nullable=False),
        sa.Column("checkpointed_at", sa.DateTime, nullable=False),
        sa.Column("checkpoint_type", sa.String(32), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("source_checkpoints")
    op.drop_index("ix_source_row_provenance_source_ref", "source_row_provenance")
    op.drop_index("ix_source_row_provenance_snapshot", "source_row_provenance")
    op.drop_table("source_row_provenance")
    op.drop_index("ix_source_snapshots_source_id", "source_snapshots")
    op.drop_table("source_snapshots")
    op.drop_table("source_definitions")
