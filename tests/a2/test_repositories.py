"""Tests for A2 repository layer. All tests require PostgreSQL."""
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.a2.repositories.canonical_product import CanonicalProductRepository
from app.a2.repositories.channel_listing import ChannelListingRepository
from tests.a2.conftest import requires_postgres

products_repo = CanonicalProductRepository()
listings_repo = ChannelListingRepository()


@requires_postgres
class TestCanonicalProductRepository:
    def test_create_returns_product_with_generated_id(self, pg_session):
        p = products_repo.create(pg_session, sku="SKU-001", name="Widget A")
        assert p.id is not None
        assert p.sku == "SKU-001"
        assert p.name == "Widget A"
        assert p.status == "active"

    def test_get_by_id_returns_product(self, pg_session):
        p = products_repo.create(pg_session, sku="SKU-002", name="Widget B")
        fetched = products_repo.get_by_id(pg_session, p.id)
        assert fetched is not None
        assert fetched.sku == "SKU-002"

    def test_get_by_id_returns_none_for_unknown_id(self, pg_session):
        result = products_repo.get_by_id(pg_session, uuid.uuid4())
        assert result is None

    def test_get_by_sku_returns_product(self, pg_session):
        products_repo.create(pg_session, sku="SKU-003", name="Widget C")
        fetched = products_repo.get_by_sku(pg_session, "SKU-003")
        assert fetched is not None
        assert fetched.name == "Widget C"

    def test_get_by_sku_returns_none_for_unknown_sku(self, pg_session):
        result = products_repo.get_by_sku(pg_session, "DOES-NOT-EXIST")
        assert result is None

    def test_create_with_explicit_status(self, pg_session):
        p = products_repo.create(pg_session, sku="SKU-004", name="Draft Widget", status="draft")
        assert p.status == "draft"

    def test_list_all_returns_created_products(self, pg_session):
        products_repo.create(pg_session, sku="SKU-LIST-1", name="List Widget 1")
        products_repo.create(pg_session, sku="SKU-LIST-2", name="List Widget 2")
        all_products = products_repo.list_all(pg_session)
        skus = {p.sku for p in all_products}
        assert "SKU-LIST-1" in skus
        assert "SKU-LIST-2" in skus


@requires_postgres
class TestChannelListingRepository:
    def _make_product(self, session, suffix: str):
        return products_repo.create(session, sku=f"CL-PROD-{suffix}", name=f"Product {suffix}")

    def test_create_returns_listing_with_generated_id(self, pg_session):
        p = self._make_product(pg_session, "A")
        listing = listings_repo.create(
            pg_session, product_id=p.id, channel_type="woocommerce", external_id="WC-100"
        )
        assert listing.id is not None
        assert listing.product_id == p.id
        assert listing.channel_type == "woocommerce"
        assert listing.external_id == "WC-100"
        assert listing.status == "pending"

    def test_get_by_id_returns_listing(self, pg_session):
        p = self._make_product(pg_session, "B")
        listing = listings_repo.create(
            pg_session, product_id=p.id, channel_type="woocommerce", external_id="WC-101"
        )
        fetched = listings_repo.get_by_id(pg_session, listing.id)
        assert fetched is not None
        assert fetched.external_id == "WC-101"

    def test_get_by_id_returns_none_for_unknown_id(self, pg_session):
        result = listings_repo.get_by_id(pg_session, uuid.uuid4())
        assert result is None

    def test_get_by_product_returns_all_listings(self, pg_session):
        p = self._make_product(pg_session, "C")
        listings_repo.create(
            pg_session, product_id=p.id, channel_type="woocommerce", external_id="WC-200"
        )
        listings_repo.create(
            pg_session, product_id=p.id, channel_type="digikala", external_id="DK-200"
        )
        results = listings_repo.get_by_product(pg_session, p.id)
        channels = {r.channel_type for r in results}
        assert channels == {"woocommerce", "digikala"}

    def test_get_by_channel_and_external_id(self, pg_session):
        p = self._make_product(pg_session, "D")
        listings_repo.create(
            pg_session, product_id=p.id, channel_type="woocommerce", external_id="WC-300"
        )
        fetched = listings_repo.get_by_channel_and_external_id(
            pg_session, "woocommerce", "WC-300"
        )
        assert fetched is not None
        assert fetched.product_id == p.id

    def test_get_by_channel_and_external_id_returns_none_when_missing(self, pg_session):
        result = listings_repo.get_by_channel_and_external_id(
            pg_session, "woocommerce", "NO-SUCH-ID"
        )
        assert result is None

    def test_unique_constraint_raises_on_duplicate(self, pg_session):
        p = self._make_product(pg_session, "E")
        listings_repo.create(
            pg_session, product_id=p.id, channel_type="woocommerce", external_id="WC-DUP"
        )
        pg_session.flush()
        with pytest.raises(IntegrityError):
            listings_repo.create(
                pg_session, product_id=p.id, channel_type="woocommerce", external_id="WC-DUP"
            )
            pg_session.flush()
