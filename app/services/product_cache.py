"""
Persistent product cache service.

Stores WooCommerce product data in the local database so the preview
flow can return results instantly without hitting WooCommerce every time.
"""
import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..models import ProductCache


def _to_dict(p: ProductCache) -> dict:
    cats = []
    try:
        if p.categories:
            cats = json.loads(p.categories)
    except Exception:
        pass
    return {
        "name": p.name or "",
        "price": p.final_price or p.regular_price or "",
        "regular_price": p.regular_price or "",
        "sale_price": p.sale_price or "",
        "sku": p.sku or "",
        "stock_status": p.stock_status or "instock",
        "stock_quantity": p.stock_quantity,
        "categories": cats,
        "parent_id": p.parent_id or 0,
        "wc_date_modified": p.date_modified_gmt or None,
        "product_type": p.product_type or "simple",
        "last_synced_at": p.last_synced_at.isoformat() if p.last_synced_at else None,
        "image_url": p.image_url or None,
        "image_source": p.image_source or "none",
    }


def get_cached_by_ids(db: Session, product_ids: list[int]) -> dict[int, dict]:
    """Return {wc_id: data_dict} for the requested IDs that exist in cache."""
    if not product_ids:
        return {}
    rows = db.query(ProductCache).filter(ProductCache.wc_id.in_(product_ids)).all()
    return {r.wc_id: _to_dict(r) for r in rows}


def upsert_products(db: Session, products: list[dict]) -> tuple[int, int, set[int]]:
    """Insert or update products in the cache. Returns (inserted, updated, image_changed_ids).

    image_changed_ids: wc_ids of existing rows whose image_url changed — callers
    should invalidate disk thumbnails for these IDs (and cascade to variations that
    inherit the parent's image).
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    inserted = updated = 0
    image_changed_ids: set[int] = set()
    ids = [p["wc_id"] for p in products if "wc_id" in p]
    existing = {r.wc_id: r for r in db.query(ProductCache).filter(ProductCache.wc_id.in_(ids)).all()}

    for p in products:
        wc_id = p.get("wc_id")
        if wc_id is None:
            continue
        cats = p.get("categories")
        if isinstance(cats, list):
            cats = json.dumps(cats)

        if wc_id in existing:
            row = existing[wc_id]
            row.parent_id = p.get("parent_id", 0) or 0
            row.product_type = p.get("product_type", "simple") or "simple"
            row.sku = p.get("sku") or row.sku
            row.name = p.get("name") or row.name
            row.status = p.get("status") or row.status
            row.stock_status = p.get("stock_status") or row.stock_status
            row.stock_quantity = p.get("stock_quantity") if p.get("stock_quantity") is not None else row.stock_quantity
            row.regular_price = p.get("regular_price", "") or row.regular_price
            row.sale_price = p.get("sale_price", "") or ""
            row.final_price = p.get("final_price", "") or row.final_price
            row.categories = cats or row.categories
            row.date_modified_gmt = p.get("date_modified_gmt") or row.date_modified_gmt
            new_img = p.get("image_url")
            if new_img is not None:
                if new_img != row.image_url:
                    image_changed_ids.add(wc_id)
                row.image_url = new_img or None
                row.image_source = p.get("image_source") or "none"
                row.image_last_synced_at = now
            row.last_synced_at = now
            row.last_seen_at = now
            row.cache_version = (row.cache_version or 0) + 1
            updated += 1
        else:
            row = ProductCache(
                wc_id=wc_id,
                parent_id=p.get("parent_id", 0) or 0,
                product_type=p.get("product_type", "simple") or "simple",
                sku=p.get("sku"),
                name=p.get("name"),
                status=p.get("status"),
                stock_status=p.get("stock_status"),
                stock_quantity=p.get("stock_quantity"),
                regular_price=p.get("regular_price", ""),
                sale_price=p.get("sale_price", ""),
                final_price=p.get("final_price", ""),
                categories=cats,
                date_modified_gmt=p.get("date_modified_gmt"),
                image_url=p.get("image_url"),
                image_source=p.get("image_source", "none"),
                image_last_synced_at=now if p.get("image_url") is not None else None,
                last_synced_at=now,
                last_seen_at=now,
                cache_version=1,
            )
            db.add(row)
            inserted += 1
    return inserted, updated, image_changed_ids


def get_all(db: Session) -> list[dict]:
    rows = db.query(ProductCache).order_by(ProductCache.wc_id).all()
    return [{"wc_id": r.wc_id, **_to_dict(r)} for r in rows]


def get_page(
    db: Session,
    page: int = 1,
    limit: int = 50,
    search: str | None = None,
    product_type: str | None = None,
) -> tuple[list[dict], int]:
    """Return (items, total) for the requested page with optional filters."""
    q = db.query(ProductCache)
    if search:
        like = f"%{search}%"
        q = q.filter(
            ProductCache.name.ilike(like) | ProductCache.sku.ilike(like)
        )
    if product_type:
        q = q.filter(ProductCache.product_type == product_type)
    total = q.count()
    offset = (page - 1) * limit
    rows = q.order_by(ProductCache.wc_id).offset(offset).limit(limit).all()
    items = [{"wc_id": r.wc_id, **_to_dict(r)} for r in rows]
    return items, total


def patch_cached_product(db: Session, wc_id: int, fields: dict) -> bool:
    """Update specific fields on an existing cache row. Returns True if the row existed."""
    row = db.query(ProductCache).filter(ProductCache.wc_id == wc_id).first()
    if row is None:
        return False
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for key, value in fields.items():
        if hasattr(row, key):
            setattr(row, key, value)
    row.last_synced_at = now
    row.cache_version = (row.cache_version or 0) + 1
    return True


def get_stats(db: Session) -> dict:
    total = db.query(ProductCache).count()
    last_row = db.query(ProductCache).order_by(ProductCache.last_synced_at.desc()).first()
    last_sync = last_row.last_synced_at.isoformat() if last_row and last_row.last_synced_at else None
    return {"total": total, "last_synced_at": last_sync}


def get_last_sync_time(db: Session) -> datetime | None:
    row = db.query(ProductCache).order_by(ProductCache.last_synced_at.desc()).first()
    return row.last_synced_at if row else None


def clear_all(db: Session) -> int:
    count = db.query(ProductCache).count()
    db.query(ProductCache).delete()
    return count


def wc_response_to_cache_dict(pid: int, data: dict) -> dict:
    """Convert the dict returned by fetch_product_prices into cache format."""
    return {
        "wc_id": pid,
        "parent_id": data.get("parent_id", 0) or 0,
        "product_type": "variation" if (data.get("parent_id") or 0) > 0 else "simple",
        "sku": data.get("sku", ""),
        "name": data.get("name", ""),
        "stock_status": data.get("stock_status", "instock"),
        "stock_quantity": data.get("stock_quantity"),
        "regular_price": data.get("regular_price") or data.get("price", ""),
        "sale_price": data.get("sale_price", ""),
        "final_price": data.get("price") or data.get("regular_price", ""),
        "categories": json.dumps(data.get("categories", [])),
        "date_modified_gmt": data.get("wc_date_modified") or "",
        # image_url intentionally absent — do not overwrite existing thumbnail cache
    }
