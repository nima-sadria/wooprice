"""Initial A2 foundation: canonical_products, channel_listings, channel_credentials

Revision ID: 0001
Revises:
Create Date: 2026-06-24 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "canonical_products",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("sku", sa.String(255), nullable=False),
        sa.Column("name", sa.String(1000), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint("sku", name="canonical_products_sku_key"),
        sa.CheckConstraint(
            "status IN ('active', 'inactive', 'draft')",
            name="canonical_products_status_check",
        ),
    )

    op.create_table(
        "channel_listings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel_type", sa.String(100), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["canonical_products.id"],
            name="channel_listings_product_id_fkey",
            ondelete="RESTRICT",
        ),
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
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("channel_type", sa.String(100), nullable=False),
        sa.Column("credential_type", sa.String(100), nullable=False),
        sa.Column("encrypted_payload", sa.LargeBinary, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("channel_credentials")
    op.drop_table("channel_listings")
    op.drop_table("canonical_products")
