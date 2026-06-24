"""Repository for CanonicalProduct. Pure data access — no business logic."""
import uuid

from sqlalchemy.orm import Session

from app.a2.models import CanonicalProduct


class CanonicalProductRepository:
    def create(
        self,
        session: Session,
        *,
        sku: str,
        name: str,
        status: str = "active",
    ) -> CanonicalProduct:
        product = CanonicalProduct(sku=sku, name=name, status=status)
        session.add(product)
        session.flush()
        return product

    def get_by_id(self, session: Session, product_id: uuid.UUID) -> CanonicalProduct | None:
        return session.get(CanonicalProduct, product_id)

    def get_by_sku(self, session: Session, sku: str) -> CanonicalProduct | None:
        return session.query(CanonicalProduct).filter_by(sku=sku).one_or_none()

    def list_all(self, session: Session) -> list[CanonicalProduct]:
        return session.query(CanonicalProduct).order_by(CanonicalProduct.created_at).all()
