"""Add per-user permission columns to app_users.

Revision ID: 003
Revises: 002
Create Date: 2026-06-15

Default values for NEW rows (server_default):
    can_access_site=1, can_fetch=1, can_apply=1, can_edit_price=1, can_edit_stock=1
    can_view_logs=0, can_view_settings=0

Defaults for EXISTING operator rows (backfilled at migration time via server_default):
    Broad-access defaults are intentional for the current deployment.
    All existing users in app_users are trusted price operators who need full
    fetch/apply/edit access. can_view_logs and can_view_settings default to 0
    (non-admins do not see these sections unless explicitly granted).

    Existing admin rows (is_admin=1) receive all permissions=1 via the UPDATE
    statement below, matching their pre-migration unrestricted access.

    To restrict an existing operator after deploy, run:
        UPDATE app_users SET can_apply=0 WHERE username='...';
        -- and bump permission_version to invalidate live tokens.

Public-by-design route: /api/products/{wc_id}/thumb
    This route has no authentication. It exposes only JPEG thumbnails — no
    price, stock, or catalogue data. Marked public so the browser workspace
    table can load images without token forwarding. Rate limiting may be
    added in a future deployment if abuse is detected.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Columns to add: (name, type, server_default)
_PERM_COLS = [
    ("can_access_site",   "BOOLEAN", "1"),
    ("can_fetch",         "BOOLEAN", "1"),
    ("can_apply",         "BOOLEAN", "1"),
    ("can_edit_price",    "BOOLEAN", "1"),
    ("can_edit_stock",    "BOOLEAN", "1"),
    ("can_view_logs",     "BOOLEAN", "0"),
    ("can_view_settings", "BOOLEAN", "0"),
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_cols = {c["name"] for c in inspector.get_columns("app_users")}

    missing = [c for c in _PERM_COLS if c[0] not in existing_cols]
    if missing:
        with op.batch_alter_table("app_users") as batch_op:
            for col_name, col_type, default in missing:
                batch_op.add_column(
                    sa.Column(col_name, sa.Boolean(), nullable=False, server_default=default)
                )

    # Grant all permissions to existing admin users
    bind.execute(text(
        "UPDATE app_users SET "
        "can_access_site=1, can_fetch=1, can_apply=1, can_edit_price=1, "
        "can_edit_stock=1, can_view_logs=1, can_view_settings=1 "
        "WHERE is_admin=1"
    ))


def downgrade() -> None:
    with op.batch_alter_table("app_users") as batch_op:
        for col_name, _, _ in reversed(_PERM_COLS):
            batch_op.drop_column(col_name)
