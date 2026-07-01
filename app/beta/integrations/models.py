"""Integration Platform ORM models."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.beta.database import BetaBase
from app.beta.integrations.contracts import ConnectorHealthStatus

_UTC = timezone.utc


def _utcnow() -> datetime:
    return datetime.now(_UTC).replace(tzinfo=None)


class ConnectorInstance(BetaBase):
    __tablename__ = "beta_connector_instances"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    connector_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    read_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default=ConnectorHealthStatus.DISABLED.value,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    settings: Mapped[list[ConnectorSetting]] = relationship(
        "ConnectorSetting",
        back_populates="connector",
        cascade="all, delete-orphan",
    )


class ConnectorSetting(BetaBase):
    __tablename__ = "beta_connector_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    connector_id: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("beta_connector_instances.id"),
        nullable=False,
        index=True,
    )
    key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    value_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    secret: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    configured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    connector: Mapped[ConnectorInstance] = relationship("ConnectorInstance", back_populates="settings")


class ConnectorHealthSnapshot(BetaBase):
    __tablename__ = "beta_connector_health_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    connector_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    message: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    checked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)


class ConnectorSourceRecord(BetaBase):
    __tablename__ = "beta_connector_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    connector_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    source_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default=ConnectorHealthStatus.DISABLED.value)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    product_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)


class ConnectorProductRecord(BetaBase):
    __tablename__ = "beta_connector_products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    connector_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    sku: Mapped[str | None] = mapped_column(String(150), nullable=True, index=True)
    current_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    inventory_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    category_names: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    raw_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)


class ConnectorTelemetryEvent(BetaBase):
    __tablename__ = "beta_connector_telemetry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    connector_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    event_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(30), nullable=False, default="info")
    message: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
