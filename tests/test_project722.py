"""Focused Project 7.2.2 launch-hotfix regression tests."""
import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.main as main_module
from app.database import Base
from app.models import ProductCache
from app.services.product_cache import get_page


@pytest.fixture(autouse=True)
def restore_currency_cache():
    original = dict(main_module._currency_cache)
    main_module._currency_cache.clear()
    main_module._currency_cache.update(data=None, ts=0.0)
    yield
    main_module._currency_cache.clear()
    main_module._currency_cache.update(original)


def test_currency_payload_maps_all_sell_rates_and_tolerates_strings():
    data = main_module._parse_currency_payload({
        "usd": {"sell": 159500, "updated_at": "2026-06-21 16:00"},
        "eur": {"sell": "183,000"},
        "aed": {"sell": 43120.9},
        "try": {"sell": "3490"},
    })
    assert data["usd_to_irr"] == 159500
    assert data["eur_to_irr"] == 183000
    assert data["aed_to_irr"] == 43120
    assert data["try_to_irr"] == 3490
    assert data["last_updated"] == "2026-06-21 16:00"


def test_currency_payload_preserves_single_missing_rate():
    data = main_module._parse_currency_payload({"usd": {"sell": 159500}})
    assert data["usd_to_irr"] == 159500
    assert data["eur_to_irr"] is None
    assert data["aed_to_irr"] is None
    assert data["try_to_irr"] is None


def test_currency_payload_rejects_completely_unusable_response():
    with pytest.raises(ValueError):
        main_module._parse_currency_payload({"status": "ok"})


def test_currency_missing_token_returns_generic_503(monkeypatch):
    monkeypatch.setattr(main_module, "get_settings", lambda: SimpleNamespace(alanchand_api_token=""))
    with pytest.raises(HTTPException) as caught:
        asyncio.run(main_module.get_currency())
    assert caught.value.status_code == 503
    assert caught.value.detail == "Currency service unavailable"


def test_currency_missing_token_returns_stale_cache(monkeypatch):
    monkeypatch.setattr(main_module, "get_settings", lambda: SimpleNamespace(alanchand_api_token=""))
    main_module._currency_cache.update({
        "data": {"usd_to_irr": 1, "eur_to_irr": None, "aed_to_irr": None,
                 "try_to_irr": None, "last_updated": "old", "source": "test"},
        "ts": 0.0,
    })
    data = asyncio.run(main_module.get_currency())
    assert data["usd_to_irr"] == 1
    assert data["cached"] is True
    assert data["stale"] is True


def test_product_cache_filters_combine_and_return_image_fields():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        db.add_all([
            ProductCache(
                wc_id=72201, name="Persian Phone", sku="SKU-722", brand_name="Acme",
                categories=json.dumps([{"id": 44, "name": "Phones"}], separators=(",", ":")),
                image_url="https://example.invalid/phone.jpg", image_source="simple",
            ),
            ProductCache(
                wc_id=72202, name="Persian Case", sku="CASE-722", brand_name="Acme",
                categories=json.dumps([{"id": 45, "name": "Cases"}]),
            ),
            ProductCache(
                wc_id=72203, name="Exact Four", sku="FOUR-722", brand_name="Other",
                categories=json.dumps([{"id": 4, "name": "Exact Four"}]),
            ),
        ])
        db.commit()

        items, total = get_page(
            db, name="phone", sku="SKU-722", wc_id_exact=72201,
            brand_name="acm", category_id=44,
        )
        assert total == 1
        assert items[0]["wc_id"] == 72201
        assert items[0]["image_url"] == "https://example.invalid/phone.jpg"

        compact_items, compact_total = get_page(db, category_id=44)
        assert compact_total == 1
        assert compact_items[0]["wc_id"] == 72201

        spaced_items, spaced_total = get_page(db, category_id=45)
        assert spaced_total == 1
        assert spaced_items[0]["wc_id"] == 72202

        exact_items, exact_total = get_page(db, category_id=4)
        assert exact_total == 1, "category 4 must not substring-match category 44 or 45"
        assert exact_items[0]["wc_id"] == 72203
    finally:
        db.close()
        engine.dispose()


def test_prefetch_multi_category_uses_exact_or_semantics():
    categories = [{"id": 44, "name": "Phones"}]
    assert main_module._matches_any_selected_category(categories, {44, 45}) is True
    assert main_module._matches_any_selected_category(categories, {4, 45}) is False
    assert main_module._matches_any_selected_category(categories, set()) is True
