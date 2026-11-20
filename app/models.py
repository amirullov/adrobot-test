from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    keitaro_campaign_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    country_code: Mapped[str] = mapped_column(String(2), default="ZZ")
    google_stream_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    offer_stream_id: Mapped[int] = mapped_column(Integer)
    server_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    draft: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    remote_fingerprint: Mapped[str] = mapped_column(String(64))
    remote_updated_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    draft_version: Mapped[int] = mapped_column(Integer, default=0)
    syncing: Mapped[bool] = mapped_column(Boolean, default=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("operation", "key", name="uq_idempotency_operation_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    operation: Mapped[str] = mapped_column(String(64))
    key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    response: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
