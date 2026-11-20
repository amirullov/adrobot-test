"""Create campaign drafts and idempotency records.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-19
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "campaigns",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("keitaro_campaign_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("google_stream_id", sa.Integer(), nullable=True),
        sa.Column("offer_stream_id", sa.Integer(), nullable=False),
        sa.Column("server_snapshot", sa.JSON(), nullable=False),
        sa.Column("draft", sa.JSON(), nullable=True),
        sa.Column("remote_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("remote_updated_at", sa.String(length=64), nullable=True),
        sa.Column("draft_version", sa.Integer(), nullable=False),
        sa.Column("syncing", sa.Boolean(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("keitaro_campaign_id"),
    )
    op.create_index(
        op.f("ix_campaigns_keitaro_campaign_id"),
        "campaigns",
        ["keitaro_campaign_id"],
        unique=True,
    )
    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("response", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("operation", "key", name="uq_idempotency_operation_key"),
    )


def downgrade() -> None:
    op.drop_table("idempotency_records")
    op.drop_index(op.f("ix_campaigns_keitaro_campaign_id"), table_name="campaigns")
    op.drop_table("campaigns")
