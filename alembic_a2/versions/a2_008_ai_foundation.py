"""A2.9 AI Foundation — advisory sessions and insights

Revision ID: a2_008
Revises: a2_007
Create Date: 2026-06-26

Additive migration: creates 2 new tables (a2_advisory_sessions,
a2_advisory_insights).
No existing A2 tables or SQLite tables are modified.
Default production stack is unaffected.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a2_008"
down_revision: Union[str, None] = "a2_007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_VALID_CATEGORIES = "('EXPLANATION','RISK_SUMMARY','ANOMALY','STALE_PRICE','REVIEW_PRIORITY','RULE_RECOMMENDATION')"
_VALID_SEVERITIES = "('INFO','LOW','MEDIUM','HIGH','CRITICAL')"


def upgrade() -> None:
    op.create_table(
        "a2_advisory_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("subject_type", sa.String(100), nullable=False),
        sa.Column("subject_id", sa.String(36), nullable=False),
        sa.Column("prompt_text", sa.Text, nullable=True),
        sa.Column("response_text", sa.Text, nullable=True),
        sa.Column("model_version", sa.String(100), nullable=False),
        sa.Column(
            "is_archived", sa.Boolean, nullable=False, server_default=sa.false()
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            f"category IN {_VALID_CATEGORIES}",
            name="a2_advisory_sessions_category_check",
        ),
    )
    op.create_table(
        "a2_advisory_insights",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("a2_advisory_sessions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("summary", sa.String(512), nullable=False),
        sa.Column("explanation", sa.Text, nullable=False),
        sa.Column("evidence", sa.Text, nullable=False),
        sa.Column("related_object_type", sa.String(100), nullable=True),
        sa.Column("related_object_id", sa.String(36), nullable=True),
        sa.Column("recommendation_trace", sa.Text, nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"category IN {_VALID_CATEGORIES}",
            name="a2_advisory_insights_category_check",
        ),
        sa.CheckConstraint(
            f"severity IN {_VALID_SEVERITIES}",
            name="a2_advisory_insights_severity_check",
        ),
    )


def downgrade() -> None:
    op.drop_table("a2_advisory_insights")
    op.drop_table("a2_advisory_sessions")
