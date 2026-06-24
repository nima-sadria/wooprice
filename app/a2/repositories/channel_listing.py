"""ChannelListingRepository — A2.1 foundation, preserved in A2.2."""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from ..models.canonical_product import ChannelListing


class ChannelListingRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get(self, listing_id: str) -> Optional[ChannelListing]:
        return self._db.get(ChannelListing, listing_id)

    def get_by_channel(self, channel_type: str, external_id: str) -> Optional[ChannelListing]:
        return (
            self._db.query(ChannelListing)
            .filter(
                ChannelListing.channel_type == channel_type,
                ChannelListing.external_id == external_id,
            )
            .first()
        )

    def list_for_product(self, product_id: str) -> list[ChannelListing]:
        return (
            self._db.query(ChannelListing)
            .filter(ChannelListing.product_id == product_id)
            .all()
        )

    def create(
        self,
        *,
        product_id: str,
        channel_type: str,
        external_id: str,
        status: str = "pending",
    ) -> ChannelListing:
        now = datetime.now(tz=timezone.utc)
        record = ChannelListing(
            product_id=product_id,
            channel_type=channel_type,
            external_id=external_id,
            status=status,
            created_at=now,
            updated_at=now,
        )
        self._db.add(record)
        self._db.flush()
        return record
