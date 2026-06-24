"""CanonicalProductRepository — A2.1 foundation, preserved in A2.2."""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from ..models.canonical_product import CanonicalProduct


class CanonicalProductRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get(self, product_id: str) -> Optional[CanonicalProduct]:
        return self._db.get(CanonicalProduct, product_id)

    def get_by_sku(self, sku: str) -> Optional[CanonicalProduct]:
        return (
            self._db.query(CanonicalProduct)
            .filter(CanonicalProduct.sku == sku)
            .first()
        )

    def create(self, *, sku: str, name: str, status: str = "active") -> CanonicalProduct:
        now = datetime.now(tz=timezone.utc)
        record = CanonicalProduct(sku=sku, name=name, status=status, created_at=now, updated_at=now)
        self._db.add(record)
        self._db.flush()
        return record

    def list_active(self) -> list[CanonicalProduct]:
        return (
            self._db.query(CanonicalProduct)
            .filter(CanonicalProduct.status == "active")
            .all()
        )
