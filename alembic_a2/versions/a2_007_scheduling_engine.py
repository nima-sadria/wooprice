"""A2.8 Scheduling Engine — schedules, runs, leases

Revision ID: a2_007
Revises: a2_006
Create Date: 2026-06-26

Additive migration: creates 3 new tables (a2_schedules, a2_schedule_runs,
a2_schedule_leases).
No existing A2 tables or SQLite tables are modified.
Default production stack is unaffected.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a2_007"
down_revision: Union[str, None] = "a2_006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "a2_schedules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("change_set_id", sa.String(36), nullable=False),
        sa.Column("change_set_revision_id", sa.String(36), nullable=False),
        sa.Column("change_set_digest", sa.String(64), nullable=False),
        sa.Column("confirmation_id", sa.String(36), nullable=False),
        sa.Column("confirmation_digest", sa.String(64), nullable=False),
        sa.Column("dry_run_id", sa.String(36), nullable=False),
        sa.Column("dry_run_result", sa.String(20), nullable=False),
        sa.Column(
            "dry_run_digest_verified",
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("destination_channel", sa.String(256), nullable=False),
        sa.Column("scope", sa.String(512), nullable=False),
        sa.Column("source_snapshot_id", sa.String(36), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="SCHEDULED"),
        sa.Column("max_attempts", sa.Integer, nullable=False, server_default="3"),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("backoff_seconds", sa.Integer, nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('SCHEDULED','PAUSED','CANCELLED','COMPLETED','FAILED')",
            name="a2_schedules_status_check",
        ),
    )
    op.create_index("ix_a2_schedules_status", "a2_schedules", ["status"])
    op.create_index("ix_a2_schedules_scheduled_at", "a2_schedules", ["scheduled_at"])
    op.create_index("ix_a2_schedules_change_set_id", "a2_schedules", ["change_set_id"])

    op.create_table(
        "a2_schedule_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "schedule_id",
            sa.String(36),
            sa.ForeignKey("a2_schedules.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("execution_id", sa.String(36), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('PENDING','CLAIMED','DISPATCHED','SUCCEEDED','FAILED','CANCELLED','EXPIRED')",
            name="a2_schedule_runs_status_check",
        ),
    )
    op.create_index("ix_a2_schedule_runs_schedule_id", "a2_schedule_runs", ["schedule_id"])
    op.create_index("ix_a2_schedule_runs_status", "a2_schedule_runs", ["status"])

    op.create_table(
        "a2_schedule_leases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("a2_schedule_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("lease_owner", sa.String(256), nullable=False),
        sa.Column("lease_token", sa.String(36), nullable=False),
        sa.Column("lease_acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", name="uq_a2_schedule_leases_run_id"),
    )
    op.create_index(
        "ix_a2_schedule_leases_run_id", "a2_schedule_leases", ["run_id"], unique=True
    )
    op.create_index(
        "ix_a2_schedule_leases_expires_at", "a2_schedule_leases", ["lease_expires_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_a2_schedule_leases_expires_at", table_name="a2_schedule_leases")
    op.drop_index("ix_a2_schedule_leases_run_id", table_name="a2_schedule_leases")
    op.drop_table("a2_schedule_leases")

    op.drop_index("ix_a2_schedule_runs_status", table_name="a2_schedule_runs")
    op.drop_index("ix_a2_schedule_runs_schedule_id", table_name="a2_schedule_runs")
    op.drop_table("a2_schedule_runs")

    op.drop_index("ix_a2_schedules_change_set_id", table_name="a2_schedules")
    op.drop_index("ix_a2_schedules_scheduled_at", table_name="a2_schedules")
    op.drop_index("ix_a2_schedules_status", table_name="a2_schedules")
    op.drop_table("a2_schedules")
