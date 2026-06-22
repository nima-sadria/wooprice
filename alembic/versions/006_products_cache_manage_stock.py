"""Add manage_stock column to products_cache.

Revision ID: 006
Revises: 005
Create Date: 2026-06-22

WooCommerce `manage_stock` distinguishes parent-managed stock from
variation-managed stock:
  parent:    "true" | "false"
  variation: "true" | "false" | "parent"  ("parent" = inherit from parent)

Stored as a nullable String so all three enum values fit without coercion.
NULL means the field was not returned by WC (pre-refresh cache rows).

This column is required by propagate_parent_metadata_to_children to know
whether to propagate stock_status/stock_quantity from the parent row down
to cached variation rows.

If products_cache does not exist (fresh install), Base.metadata.create_all()
creates it with manage_stock already present via the model — this migration
is a no-op in that case.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "products_cache" not in inspector.get_table_names():
        return  # fresh DB — create_all() handles it

    existing_cols = {c["name"] for c in inspector.get_columns("products_cache")}
    if "manage_stock" not in existing_cols:
        with op.batch_alter_table("products_cache") as batch_op:
            batch_op.add_column(sa.Column("manage_stock", sa.String(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "products_cache" not in inspector.get_table_names():
        return
    existing_cols = {c["name"] for c in inspector.get_columns("products_cache")}
    if "manage_stock" in existing_cols:
        with op.batch_alter_table("products_cache") as batch_op:
            batch_op.drop_column("manage_stock")
