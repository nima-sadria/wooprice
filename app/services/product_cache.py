"""
Persistent product cache service.

Stores WooCommerce product data in the local database so the preview
flow can return results instantly without hitting WooCommerce every time.
"""
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..models import ChangeTracking, ProductCache

logger = logging.getLogger(__name__)


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
        "brand_id": p.brand_id,
        "brand_name": p.brand_name,
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


def upsert_products(
    db: Session,
    products: list[dict],
    image_sync_authoritative: bool = False,
) -> tuple[int, int, set[int]]:
    """Insert or update products in the cache. Returns (inserted, updated, image_changed_ids).

    image_changed_ids: wc_ids of existing rows whose image_url changed.
    image_sync_authoritative: when True, allow clearing an existing image_url to NULL
    if the incoming dict has image_url=None.  When False (default), a None incoming
    image never overwrites a non-NULL stored value — protects against accidental erasure
    by callers that don't carry image data (e.g. preview cache rows).
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
            _prev_seen = row.last_seen_at
            # Phase C — capture prior values for change_tracking before overwrite
            _old_price = row.final_price or row.regular_price
            _old_stock_status = row.stock_status
            _old_stock_qty = row.stock_quantity
            row.parent_id = p.get("parent_id", 0) or 0
            row.product_type = p.get("product_type", "simple") or "simple"
            row.sku = p.get("sku") or row.sku
            row.name = p.get("name") or row.name
            row.status = p.get("status") or row.status
            row.stock_status = p.get("stock_status") or row.stock_status
            row.stock_quantity = p.get("stock_quantity") if p.get("stock_quantity") is not None else row.stock_quantity
            if "manage_stock" in p:
                row.manage_stock = p["manage_stock"]
            row.regular_price = p.get("regular_price", "") or row.regular_price
            row.sale_price = p.get("sale_price", "") or ""
            row.final_price = p.get("final_price", "") or row.final_price
            # Phase C — emit field-level change_tracking rows for any WC-side drift
            try:
                _new_price = row.final_price or row.regular_price
                if (_old_price or "") != (_new_price or ""):
                    db.add(ChangeTracking(
                        product_id=wc_id, detected_at=now, field_name="price",
                        old_value=str(_old_price) if _old_price is not None else None,
                        new_value=str(_new_price) if _new_price is not None else None,
                        source="wc_fetch",
                    ))
                if (_old_stock_status or "") != (row.stock_status or ""):
                    db.add(ChangeTracking(
                        product_id=wc_id, detected_at=now, field_name="stock_status",
                        old_value=_old_stock_status, new_value=row.stock_status,
                        source="wc_fetch",
                    ))
                if _old_stock_qty != row.stock_quantity:
                    db.add(ChangeTracking(
                        product_id=wc_id, detected_at=now, field_name="stock_quantity",
                        old_value=str(_old_stock_qty) if _old_stock_qty is not None else None,
                        new_value=str(row.stock_quantity) if row.stock_quantity is not None else None,
                        source="wc_fetch",
                    ))
            except Exception:
                pass
            row.categories = cats or row.categories
            # Brand: key presence is the signal — not value truthiness.
            # key absent  → non-authoritative caller; preserve existing cache value.
            # key present (even None) → authoritative caller; use exactly what WC returned.
            if "brand_id" in p:
                row.brand_id = p["brand_id"]
                row.brand_name = p.get("brand_name")
            row.date_modified_gmt = p.get("date_modified_gmt") or row.date_modified_gmt
            new_img = p.get("image_url")
            if "image_url" in p:
                if new_img:
                    if new_img != row.image_url:
                        image_changed_ids.add(wc_id)
                    row.image_url = new_img
                    row.image_source = p.get("image_source") or "simple"
                    row.image_last_synced_at = now
                elif image_sync_authoritative:
                    if row.image_url:
                        image_changed_ids.add(wc_id)
                    row.image_url = None
                    row.image_source = "none"
                    row.image_last_synced_at = now
                # else: new_img is None and not authoritative — preserve existing image_url
            logger.debug(
                "product_image: wc_id=%s parent_id=%s product_type=%s image_source=%s image_url=%s last_seen_at=%s",
                wc_id, p.get("parent_id", 0), p.get("product_type", "?"),
                p.get("image_source", "—"), new_img or "NULL",
                _prev_seen.isoformat() if _prev_seen else "NULL",
            )
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
                manage_stock=p.get("manage_stock"),
                regular_price=p.get("regular_price", ""),
                sale_price=p.get("sale_price", ""),
                final_price=p.get("final_price", ""),
                categories=cats,
                brand_id=p.get("brand_id"),
                brand_name=p.get("brand_name"),
                date_modified_gmt=p.get("date_modified_gmt"),
                image_url=p.get("image_url"),
                image_source=p.get("image_source", "none"),
                image_last_synced_at=now if p.get("image_url") is not None else None,
                last_synced_at=now,
                last_seen_at=now,
                cache_version=1,
            )
            db.add(row)
            logger.debug(
                "product_image: wc_id=%s parent_id=%s product_type=%s image_source=%s image_url=%s last_seen_at=NULL",
                wc_id, p.get("parent_id", 0), p.get("product_type", "?"),
                p.get("image_source", "—"), p.get("image_url") or "NULL",
            )
            inserted += 1
    return inserted, updated, image_changed_ids


def get_all(db: Session) -> list[dict]:
    rows = db.query(ProductCache).order_by(ProductCache.wc_id).all()
    return [{"wc_id": r.wc_id, **_to_dict(r)} for r in rows]


def filter_by_exact_category(query, category_id: int):
    """Filter ProductCache rows by exact category ID membership.

    Product categories are stored as a JSON array. SQLite JSON1 expands each
    category object and compares its `id` value numerically, avoiding substring
    matches such as category 4 incorrectly matching category 44.
    """
    clause = text("""
        EXISTS (
            SELECT 1
            FROM json_each(
                CASE
                    WHEN json_valid(products_cache.categories)
                    THEN products_cache.categories
                    ELSE '[]'
                END
            ) AS category
            WHERE CAST(json_extract(category.value, '$.id') AS INTEGER) = :exact_category_id
        )
    """).bindparams(exact_category_id=int(category_id))
    return query.filter(clause)


def get_page(
    db: Session,
    page: int = 1,
    limit: int = 50,
    search: str | None = None,
    product_type: str | None = None,
    brand_name: str | None = None,
    category_id: int | None = None,
    category_ids: list[int] | None = None,
    wc_id_exact: int | None = None,
    sku: str | None = None,
    name: str | None = None,
    stock_status: str | None = None,
    price_status: str | None = None,
    sort: str = "newest",
    quality_filter: str | None = None,
) -> tuple[list[dict], int]:
    """Return (items, total) for the requested page with optional combined filters.

    Filters are AND-combined. category_id/category_ids require exact membership in the
    cached JSON category array. category_ids applies OR logic across multiple IDs."""
    q = db.query(ProductCache)
    if search:
        like = f"%{search}%"
        q = q.filter(
            ProductCache.name.ilike(like) | ProductCache.sku.ilike(like)
        )
    if product_type:
        q = q.filter(ProductCache.product_type == product_type)
    if brand_name:
        q = q.filter(ProductCache.brand_name.ilike(f"%{brand_name}%"))
    if category_id is not None:
        q = filter_by_exact_category(q, category_id)
    elif category_ids:
        # Multi-category OR filter: match any of the given category IDs.
        # IDs are validated as integers by FastAPI so safe to inline.
        ids_literal = ", ".join(str(int(cid)) for cid in category_ids)
        clause = text(f"""
            EXISTS (
                SELECT 1
                FROM json_each(
                    CASE WHEN json_valid(products_cache.categories)
                         THEN products_cache.categories
                         ELSE '[]' END
                ) AS cat
                WHERE CAST(json_extract(cat.value, '$.id') AS INTEGER) IN ({ids_literal})
            )
        """)
        q = q.filter(clause)
    if wc_id_exact is not None:
        q = q.filter(ProductCache.wc_id == wc_id_exact)
    if sku:
        q = q.filter(ProductCache.sku.ilike(f"%{sku}%"))
    if name:
        q = q.filter(ProductCache.name.ilike(f"%{name}%"))
    if stock_status and stock_status != "all":
        q = q.filter(ProductCache.stock_status == stock_status)
    if price_status not in (None, "", "all"):
        if price_status == "has_price":
            # Matches display logic: final_price || regular_price
            q = q.filter(
                (ProductCache.final_price.isnot(None) & (ProductCache.final_price != ""))
                | (ProductCache.regular_price.isnot(None) & (ProductCache.regular_price != ""))
            )
        elif price_status == "no_price":
            q = q.filter(
                (ProductCache.final_price.is_(None) | (ProductCache.final_price == ""))
                & (ProductCache.regular_price.is_(None) | (ProductCache.regular_price == ""))
            )
    if quality_filter == "missing_sku":
        q = q.filter(
            (ProductCache.sku.is_(None)) | (ProductCache.sku == "")
        )
    elif quality_filter == "missing_image":
        q = q.filter(
            (ProductCache.image_url.is_(None)) | (ProductCache.image_url == "")
        )
    total = q.count()
    offset = (page - 1) * limit
    if sort == "name_asc":
        q = q.order_by(ProductCache.name.asc(), ProductCache.wc_id.asc())
    elif sort == "name_desc":
        q = q.order_by(ProductCache.name.desc(), ProductCache.wc_id.desc())
    elif sort == "oldest":
        q = q.order_by(ProductCache.last_synced_at.asc(), ProductCache.wc_id.asc())
    else:
        q = q.order_by(ProductCache.last_synced_at.desc(), ProductCache.wc_id.desc())
    rows = q.offset(offset).limit(limit).all()
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


def get_last_wc_modified_time(db: Session) -> datetime | None:
    """Return the latest date_modified_gmt across all top-level cached products.

    Use this as the light-refresh watermark — it reflects WC's own modification
    time, not the local cache upsert time, so we never advance past what WC
    actually told us."""
    from sqlalchemy import func
    raw = (
        db.query(func.max(ProductCache.date_modified_gmt))
        .filter(ProductCache.parent_id == 0, ProductCache.date_modified_gmt.isnot(None))
        .scalar()
    )
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    try:
        return datetime.fromisoformat(str(raw))
    except (ValueError, TypeError):
        return None


def propagate_parent_metadata_to_children(
    db: Session,
    parent_wc_ids: list[int],
) -> int:
    """Update inherited metadata on cached variation rows from their parent row.

    Propagates: name, categories, brand, image (including removal), and stock
    when the parent manages stock.  No WooCommerce API call is made.
    Returns the count of child rows that were actually modified.
    """
    if not parent_wc_ids:
        return 0
    parents = {
        r.wc_id: r
        for r in db.query(ProductCache).filter(ProductCache.wc_id.in_(parent_wc_ids)).all()
    }
    if not parents:
        return 0
    children = (
        db.query(ProductCache)
        .filter(ProductCache.parent_id.in_(parent_wc_ids))
        .all()
    )
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    count = 0
    for child in children:
        parent = parents.get(child.parent_id)
        if parent is None:
            continue
        changed = False
        image_changed = False

        # Name
        if child.name != parent.name:
            child.name = parent.name
            changed = True

        # Categories
        if child.categories != parent.categories:
            child.categories = parent.categories
            changed = True

        # Brand
        if child.brand_id != parent.brand_id or child.brand_name != parent.brand_name:
            child.brand_id = parent.brand_id
            child.brand_name = parent.brand_name
            changed = True

        # Image — only when child has no own variation-level image
        if child.image_source not in ("variation",):
            if parent.image_url:
                # Parent has image — propagate it
                if child.image_url != parent.image_url:
                    child.image_url = parent.image_url
                    child.image_source = "parent"
                    changed = True
                    image_changed = True
            else:
                # Parent image removed — clear stale inherited image
                if child.image_url is not None or child.image_source not in ("none", None):
                    child.image_url = None
                    child.image_source = "none"
                    child.image_last_synced_at = now
                    changed = True
                    image_changed = True

        # Stock — propagate only when parent manages stock AND child explicitly inherits.
        # manage_stock=NULL means the field was not fetched yet (pre-migration legacy row);
        # do NOT overwrite its stock value until we have confirmed inheritance status.
        parent_manages_stock = (parent.manage_stock == "true")
        child_inherits_stock = (child.manage_stock in ("false", "parent"))
        if parent_manages_stock and child_inherits_stock:
            if child.stock_status != parent.stock_status:
                child.stock_status = parent.stock_status
                changed = True
            if child.stock_quantity != parent.stock_quantity:
                child.stock_quantity = parent.stock_quantity
                changed = True

        if changed:
            child.cache_version = (child.cache_version or 0) + 1
            child.last_synced_at = now
            if image_changed:
                child.image_last_synced_at = now
            count += 1
    return count


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
        "brand_id": data.get("brand_id"),
        "brand_name": data.get("brand_name"),
        "date_modified_gmt": data.get("wc_date_modified") or "",
        # image_url intentionally absent — do not overwrite existing thumbnail cache
    }
