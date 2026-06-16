"""Analytics: indexes for fast dashboard queries + future-analytics fields on change_history.

Revision ID: 005
Revises: 004
Create Date: 2026-06-17

Adds four indexes to eliminate full-table scans on analytics endpoints:
  - products_cache(stock_status)     → "out of stock" card
  - products_cache(last_synced_at)   → staleness report
  - change_history(source, changed_at) composite → "today's applies", top movements
  - sync_jobs(status, created_at) composite       → apply count today

Also adds two future-analytics columns to change_history so velocity metrics
can be built later without a second migration:
  - brand_id       INTEGER  — brand active at the time of the change
  - price_delta_pct REAL   — pre-computed (new-old)/old*100, NULL when prices non-numeric
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEXES = [
    ("ix_products_cache_stock_status",        "products_cache",  ["stock_status"]),
    ("ix_products_cache_last_synced_at",       "products_cache",  ["last_synced_at"]),
    ("ix_change_history_source_changed_at",    "change_history",  ["source", "changed_at"]),
    ("ix_sync_jobs_status_created_at",         "sync_jobs",       ["status", "created_at"]),
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # ── Indexes ───────────────────────────────────────────────────────────────
    for idx_name, table, cols in _INDEXES:
        if table not in existing_tables:
            continue
        existing = {ix["name"] for ix in inspector.get_indexes(table)}
        if idx_name not in existing:
            op.create_index(idx_name, table, cols)

    # ── Future-analytics fields on change_history ─────────────────────────────
    if "change_history" not in existing_tables:
        return  # fresh install — Base.metadata.create_all() creates with these columns

    existing_cols = {c["name"] for c in inspector.get_columns("change_history")}
    to_add = []
    if "brand_id" not in existing_cols:
        to_add.append(sa.Column("brand_id", sa.Integer(), nullable=True))
    if "price_delta_pct" not in existing_cols:
        to_add.append(sa.Column("price_delta_pct", sa.Float(), nullable=True))

    if to_add:
        with op.batch_alter_table("change_history") as batch_op:
            for col in to_add:
                batch_op.add_column(col)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    for idx_name, table, _cols in _INDEXES:
        if table not in existing_tables:
            continue
        existing = {ix["name"] for ix in inspector.get_indexes(table)}
        if idx_name in existing:
            op.drop_index(idx_name, table_name=table)

    # SQLite batch_alter_table supports drop_column in recent Alembic versions
    if "change_history" in existing_tables:
        existing_cols = {c["name"] for c in inspector.get_columns("change_history")}
        to_drop = [c for c in ("brand_id", "price_delta_pct") if c in existing_cols]
        if to_drop:
            with op.batch_alter_table("change_history") as batch_op:
                for col in to_drop:
                    batch_op.drop_column(col)
