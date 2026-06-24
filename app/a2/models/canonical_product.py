"""A2.1 canonical product models — preserved from approved A2.1 baseline."""
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import A2Base


class CanonicalProduct(A2Base):
    """Platform-level product identity. SKU is the stable cross-channel key."""

    __tablename__ = "canonical_products"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'inactive', 'draft')",
            name="canonical_products_status_check",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    sku: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    listings: Mapped[list["ChannelListing"]] = relationship(
        "ChannelListing", back_populates="product"
    )


class ChannelListing(A2Base):
    """Per-channel representation of a canonical product."""

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

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    product_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("canonical_products.id", ondelete="RESTRICT"),
        nullable=False,
    )
    channel_type: Mapped[str] = mapped_column(String(100), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    product: Mapped[CanonicalProduct] = relationship(
        "CanonicalProduct", back_populates="listings"
    )


class ChannelCredential(A2Base):
    """Encrypted channel credentials.

    encrypted_payload stores ciphertext. Encryption implementation deferred to a future phase;
    field is architecture-ready. Do not store plaintext secrets.
    """

    __tablename__ = "channel_credentials"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    channel_type: Mapped[str] = mapped_column(String(100), nullable=False)
    credential_type: Mapped[str] = mapped_column(String(100), nullable=False)
    encrypted_payload: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
