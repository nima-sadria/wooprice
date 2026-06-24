"""A2.1 initial foundation: canonical_products, channel_listings, channel_credentials

Revision ID: a2_000
Revises:
Create Date: 2026-06-24

Preserved from approved A2.1 baseline (commit 7fa78f0 lineage).
Uses String(36) for IDs to remain compatible with both SQLite (test) and PostgreSQL (production).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a2_000"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "canonical_products",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("sku", sa.String(255), nullable=False),
        sa.Column("name", sa.String(1000), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("sku", name="canonical_products_sku_key"),
        sa.CheckConstraint(
            "status IN ('active', 'inactive', 'draft')",
            name="canonical_products_status_check",
        ),
    )

    op.create_table(
        "channel_listings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "product_id",
            sa.String(36),
            sa.ForeignKey("canonical_products.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("channel_type", sa.String(100), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "channel_type",
            "external_id",
            name="channel_listings_channel_type_external_id_key",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'inactive', 'pending')",
            name="channel_listings_status_check",
        ),
    )

    op.create_table(
        "channel_credentials",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("channel_type", sa.String(100), nullable=False),
        sa.Column("credential_type", sa.String(100), nullable=False),
        sa.Column("encrypted_payload", sa.LargeBinary, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("channel_credentials")
    op.drop_table("channel_listings")
    op.drop_table("canonical_products")
