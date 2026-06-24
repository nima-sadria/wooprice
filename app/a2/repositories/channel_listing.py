"""Repository for ChannelListing. Pure data access — no business logic."""
import uuid

from sqlalchemy.orm import Session

from app.a2.models import ChannelListing


class ChannelListingRepository:
    def create(
        self,
        session: Session,
        *,
        product_id: uuid.UUID,
        channel_type: str,
        external_id: str,
        status: str = "pending",
    ) -> ChannelListing:
        listing = ChannelListing(
            product_id=product_id,
            channel_type=channel_type,
            external_id=external_id,
            status=status,
        )
        session.add(listing)
        session.flush()
        return listing

    def get_by_id(self, session: Session, listing_id: uuid.UUID) -> ChannelListing | None:
        return session.get(ChannelListing, listing_id)

    def get_by_product(self, session: Session, product_id: uuid.UUID) -> list[ChannelListing]:
        return (
            session.query(ChannelListing)
            .filter_by(product_id=product_id)
            .order_by(ChannelListing.created_at)
            .all()
        )

    def get_by_channel_and_external_id(
        self, session: Session, channel_type: str, external_id: str
    ) -> ChannelListing | None:
        return (
            session.query(ChannelListing)
            .filter_by(channel_type=channel_type, external_id=external_id)
            .one_or_none()
        )
