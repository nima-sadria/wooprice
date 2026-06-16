"""Add brand_id / brand_name columns to products_cache.

Revision ID: 004
Revises: 003
Create Date: 2026-06-16

Brand source confirmed via live WooCommerce audit (softpple.com):
WooCommerce's native "Brands" feature (taxonomy `product_brand`), exposed on
every product payload as a top-level `brands: [{id, name, slug}]` array —
structured exactly like `categories`. Variations never carry their own
`brands` key; they always inherit the parent's brand (see woocommerce.py).

NULL means "no brand assigned in WooCommerce" — never guessed from the
product name or any other field.

products_cache is NOT an Alembic-managed table elsewhere (it's created by
SQLAlchemy's create_all() and historically patched via the raw-SQL
`_run_column_migrations()` in main.py). This migration only adds the two
brand columns; if the table doesn't exist yet (fresh install), create_all()
will create it with these columns already present via the model, so this
migration is a no-op in that case.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEX_NAME = "ix_products_cache_brand_id"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "products_cache" not in inspector.get_table_names():
        return  # fresh DB — create_all() creates the table with these columns

    existing_cols = {c["name"] for c in inspector.get_columns("products_cache")}
    existing_indexes = {ix["name"] for ix in inspector.get_indexes("products_cache")}

    to_add = []
    if "brand_id" not in existing_cols:
        to_add.append(sa.Column("brand_id", sa.Integer(), nullable=True))
    if "brand_name" not in existing_cols:
        to_add.append(sa.Column("brand_name", sa.String(), nullable=True))

    if to_add:
        with op.batch_alter_table("products_cache") as batch_op:
            for col in to_add:
                batch_op.add_column(col)

    if _INDEX_NAME not in existing_indexes:
        op.create_index(_INDEX_NAME, "products_cache", ["brand_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "products_cache" not in inspector.get_table_names():
        return
    existing_indexes = {ix["name"] for ix in inspector.get_indexes("products_cache")}
    if _INDEX_NAME in existing_indexes:
        op.drop_index(_INDEX_NAME, table_name="products_cache")
    with op.batch_alter_table("products_cache") as batch_op:
        batch_op.drop_column("brand_name")
        batch_op.drop_column("brand_id")
