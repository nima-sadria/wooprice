"""A2 canonical product models — PostgreSQL, separate metadata from existing app/models.py."""
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, LargeBinary, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from .database import A2Base


class CanonicalProduct(A2Base):
    """Platform-level product identity. SKU is the stable cross-channel key."""

    __tablename__ = "canonical_products"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'inactive', 'draft')",
            name="canonical_products_status_check",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    sku: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    listings: Mapped[list["ChannelListing"]] = relationship(
        "ChannelListing", back_populates="product"
    )


class ChannelListing(A2Base):
    """Per-channel representation of a canonical product. WC IDs live here, not in products."""

    __tablename__ = "channel_listings"
    __table_args__ = (
        UniqueConstraint(
            "channel_type",
            "external_id",
            name="channel_listings_channel_type_external_id_key",
        ),
        CheckConstraint(
            "status IN ('active', 'inactive', 'pending')",
            name="channel_listings_status_check",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("canonical_products.id", ondelete="RESTRICT"),
        nullable=False,
    )
    channel_type: Mapped[str] = mapped_column(String(100), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    product: Mapped[CanonicalProduct] = relationship(
        "CanonicalProduct", back_populates="listings"
    )


class ChannelCredential(A2Base):
    """Encrypted channel credentials. encrypted_payload stores AES-256-GCM ciphertext (nonce||ct||tag).
    Encryption implementation is deferred to Phase 2; field is architecture-ready."""

    __tablename__ = "channel_credentials"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    channel_type: Mapped[str] = mapped_column(String(100), nullable=False)
    credential_type: Mapped[str] = mapped_column(String(100), nullable=False)
    encrypted_payload: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
