"""Service layer for canonical product operations. Minimal scaffolding for A2.1."""
import uuid

from sqlalchemy.orm import Session

from app.a2.models import CanonicalProduct
from app.a2.repositories.canonical_product import CanonicalProductRepository
from app.a2.repositories.channel_listing import ChannelListingRepository

_products = CanonicalProductRepository()
_listings = ChannelListingRepository()


class CanonicalProductService:
    def create_product(
        self,
        session: Session,
        *,
        sku: str,
        name: str,
    ) -> CanonicalProduct:
        """Create a new canonical product. SKU must be unique."""
        product = _products.create(session, sku=sku, name=name)
        session.commit()
        session.refresh(product)
        return product

    def get_product_by_id(
        self, session: Session, product_id: uuid.UUID
    ) -> CanonicalProduct | None:
        return _products.get_by_id(session, product_id)

    def get_product_by_sku(
        self, session: Session, sku: str
    ) -> CanonicalProduct | None:
        return _products.get_by_sku(session, sku)
