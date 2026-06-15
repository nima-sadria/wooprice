import asyncio
import hashlib
import io as _io
import json
import logging
import time

import httpx
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from PIL import Image as _PilImage
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

logger = logging.getLogger(__name__)

_SSE_HEADERS = {
    "X-Accel-Buffering": "no",   # tell nginx: do not buffer this stream
    "Cache-Control": "no-cache",
    "Content-Type": "text/event-stream",
}

from fastapi import Depends, FastAPI, HTTPException, Header, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func, inspect as sa_inspect, text
from sqlalchemy.orm import Session

from .config import get_settings
from .database import Base, SessionLocal, engine, get_db
from .models import AlarmThreshold, AppUser, AuditLog, ItemStatus, JobStatus, ProductCache, SyncItem, SyncJob
from .services.auth import create_token, decode_token, is_super_admin, verify_nextcloud_credentials
from .services.nextcloud import (
    download_xlsx, fetch_spreadsheet_meta, get_cached_xlsx_meta,
    parse_price_list, write_back_to_sheet, write_price_to_sheet,
)
from .services.product_cache import (
    clear_all as cache_clear_all,
    get_all as cache_get_all,
    get_cached_by_ids,
    get_last_sync_time,
    get_page as cache_get_page,
    get_stats as cache_get_stats,
    patch_cached_product,
    upsert_products,
    wc_response_to_cache_dict,
)
from .services.woocommerce import (
    batch_update_prices,
    clear_product_cache,
    fetch_all_products_fast,
    fetch_all_products_full,
    fetch_all_variations_stock,
    fetch_categories,
    fetch_product_prices,
    fetch_products_modified_after,
    fetch_variations_for_selected_parents,
    get_cache_info,
    lookup_product_info,
    resolve_variation_parent_id,
    update_parent_stock_statuses,
    update_single_product,
)

def _run_alembic_migrations() -> None:
    """Run Alembic migrations FIRST so Alembic owns every table it declares.
    create_all() runs afterwards and only creates tables not yet handled by Alembic."""
    from alembic.config import Config as AlembicConfig
    from alembic import command as alembic_command
    root = Path(__file__).parent.parent
    cfg = AlembicConfig(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    try:
        alembic_command.upgrade(cfg, "head")
        logger.info("startup: Alembic migrations applied")
    except Exception as exc:
        logger.error("startup: Alembic migration failed: %s", exc)
        raise


_run_alembic_migrations()

# create_all runs after Alembic so Alembic-owned tables (e.g. app_users) are
# already present; create_all only fills in any remaining non-Alembic tables.
Base.metadata.create_all(bind=engine)


def _run_column_migrations():
    with engine.connect() as conn:
        inspector = sa_inspect(engine)
        existing_tables = inspector.get_table_names()

        if "sync_items" in existing_tables:
            existing_cols = {c["name"] for c in inspector.get_columns("sync_items")}
            for col_name, col_type in [
                ("sku", "TEXT"),
                ("sale_price", "TEXT"),
                ("stock_status", "TEXT"),
                ("stock_quantity", "INTEGER"),
                ("categories", "TEXT"),
                ("row_color", "TEXT"),
                ("last_price_updated", "TIMESTAMP"),
                ("wc_date_modified", "TIMESTAMP"),
            ]:
                if col_name not in existing_cols:
                    conn.execute(text(f"ALTER TABLE sync_items ADD COLUMN {col_name} {col_type}"))

        if "audit_logs" in existing_tables:
            existing_cols = {c["name"] for c in inspector.get_columns("audit_logs")}
            if "detail" not in existing_cols:
                conn.execute(text("ALTER TABLE audit_logs ADD COLUMN detail TEXT"))

        if "sync_jobs" in existing_tables:
            existing_cols = {c["name"] for c in inspector.get_columns("sync_jobs")}
            if "sheet_hash" not in existing_cols:
                conn.execute(text("ALTER TABLE sync_jobs ADD COLUMN sheet_hash TEXT"))

        if "products_cache" in existing_tables:
            existing_cols = {c["name"] for c in inspector.get_columns("products_cache")}
            for col_name, col_type in [
                ("image_url", "TEXT"),
                ("image_source", "TEXT"),
                ("image_last_synced_at", "TIMESTAMP"),
            ]:
                if col_name not in existing_cols:
                    conn.execute(text(f"ALTER TABLE products_cache ADD COLUMN {col_name} {col_type}"))

        conn.commit()


_run_column_migrations()


def _check_jwt_secret() -> None:
    secret = get_settings().jwt_secret
    length = len(secret.encode())
    if length < 32:
        raise RuntimeError(
            f"JWT_SECRET is only {length} bytes — minimum is 32, recommended 64+. "
            "Set a strong value in .env and restart."
        )
    logger.info("startup: JWT_SECRET OK (%d bytes)", length)


_check_jwt_secret()

app = FastAPI(title="WooPrice Sync", docs_url="/docs")


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        raise exc
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ── Auto-fetch background task ────────────────────────────────────────────────

async def _auto_fetch_loop(interval_secs: int) -> None:
    while True:
        try:
            await asyncio.sleep(60)  # check every minute
            info = get_cache_info()
            age = info.get("age_seconds")
            if age is None or age >= interval_secs:
                xlsx = await download_xlsx(force=True)
                ids = [i["product_id"] for i in parse_price_list(xlsx)[0]]
                if ids:
                    await fetch_product_prices(ids, force=True)
        except asyncio.CancelledError:
            break
        except Exception:
            pass


async def _cleanup_stale_jobs():
    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(hours=1)
        db.query(SyncJob).filter(
            SyncJob.status == JobStatus.preview,
            SyncJob.created_at < cutoff,
        ).update({"status": JobStatus.cancelled})
        db.commit()
    finally:
        db.close()


@app.on_event("startup")
async def _start_auto_fetch():
    asyncio.create_task(_cleanup_stale_jobs())
    s = get_settings()
    if s.wc_auto_fetch_hours > 0:
        asyncio.create_task(_auto_fetch_loop(s.wc_auto_fetch_hours * 3600))

static_dir = Path(__file__).parent.parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# ── Pydantic models ───────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class AlarmThresholdItem(BaseModel):
    category_id: int | None = None
    threshold_percent: float


class PriceUpdateRequest(BaseModel):
    new_price: str
    parent_id: int = 0
    job_id: int | None = None


class StockUpdateRequest(BaseModel):
    stock_status: str
    stock_quantity: int | None = None
    parent_id: int = 0
    job_id: int | None = None


class AppUserCreate(BaseModel):
    username: str
    display_name: str | None = None
    is_admin: bool = False
    notes: str | None = None


class AppUserUpdate(BaseModel):
    display_name: str | None = None
    is_active: bool | None = None
    is_admin: bool | None = None
    notes: str | None = None


# ── Thumbnail helpers ─────────────────────────────────────────────────────────

def _get_thumb_dir() -> Path:
    db_path_str = get_settings().database_url.removeprefix("sqlite:///")
    db_path = Path(db_path_str)
    if not db_path.is_absolute():
        db_path = (Path(__file__).parent.parent / db_path_str).resolve()
    return db_path.parent / "thumbs"


# 1×1 transparent PNG used as placeholder when no image is available
_EMPTY_THUMB = bytes([
    0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,
    0x00, 0x00, 0x00, 0x0d, 0x49, 0x48, 0x44, 0x52,
    0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
    0x08, 0x06, 0x00, 0x00, 0x00, 0x1f, 0x15, 0xc4,
    0x89, 0x00, 0x00, 0x00, 0x0a, 0x49, 0x44, 0x41,
    0x54, 0x78, 0x9c, 0x62, 0x00, 0x01, 0x00, 0x00,
    0x05, 0x00, 0x01, 0x0d, 0x0a, 0x2d, 0xb4, 0x00,
    0x00, 0x00, 0x00, 0x49, 0x45, 0x4e, 0x44, 0xae,
    0x42, 0x60, 0x82,
])

# Max 4 concurrent image downloads — avoids hammering the CDN
_THUMB_SEM = asyncio.Semaphore(4)

_THUMB_SIZES = {96, 128, 256}


def _thumb_path(thumb_dir: Path, wc_id: int, size: int) -> Path:
    return thumb_dir / str(size) / f"{wc_id}.jpg"


def _delete_all_thumbs(thumb_dir: Path, wc_id: int) -> None:
    """Remove cached thumbnails for a product at all known sizes."""
    for size in _THUMB_SIZES:
        p = _thumb_path(thumb_dir, wc_id, size)
        try:
            p.unlink(missing_ok=True)
        except Exception:
            pass
    # Also remove old flat-layout file (pre-size-keyed scheme) if it exists
    old = thumb_dir / f"{wc_id}.jpg"
    try:
        old.unlink(missing_ok=True)
    except Exception:
        pass


def _invalidate_thumbs(changed_ids: set[int], db: Session) -> None:
    """Delete disk thumbnails for changed_ids plus any variations that inherit their image."""
    if not changed_ids:
        return
    thumb_dir = _get_thumb_dir()
    to_delete = set(changed_ids)
    # Cascade: find variations whose image_source == "parent" and parent_id in changed_ids
    variation_rows = (
        db.query(ProductCache.wc_id)
        .filter(
            ProductCache.image_source == "parent",
            ProductCache.parent_id.in_(changed_ids),
        )
        .all()
    )
    for (vid,) in variation_rows:
        to_delete.add(vid)
    if to_delete:
        logger.info("thumb invalidation: deleting %d thumbnails (direct=%d, cascaded=%d)",
                    len(to_delete), len(changed_ids), len(to_delete) - len(changed_ids))
    for wc_id in to_delete:
        _delete_all_thumbs(thumb_dir, wc_id)


# ── Auth helpers ──────────────────────────────────────────────────────────────

async def get_current_user(
    authorization: str | None = Header(None),
    token: str | None = Query(None),
) -> dict:
    raw = None
    if authorization and authorization.startswith("Bearer "):
        raw = authorization.removeprefix("Bearer ")
    elif token:
        raw = token
    if not raw:
        raise HTTPException(401, "Not authenticated")
    try:
        return decode_token(raw)
    except Exception:
        raise HTTPException(401, "Invalid or expired token")


def _validate_active_user_sync(user_data: dict, db: Session) -> None:
    """Enforces is_active + permission_version on every authenticated request.
    Super admins (listed in SUPER_ADMIN_USERS env) bypass the DB lookup entirely."""
    username = user_data.get("sub", "")
    if is_super_admin(username):
        return
    app_user = db.query(AppUser).filter(AppUser.username == username).first()
    if app_user is None or not app_user.is_active:
        raise HTTPException(403, "Access denied — contact your administrator")
    if user_data.get("pv", -1) != app_user.permission_version:
        raise HTTPException(401, "Token has been revoked — please log in again")


async def get_current_active_user(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> dict:
    """Single auth gate for all protected routes.
    Decodes JWT then enforces is_active + permission_version via _validate_active_user_sync."""
    _validate_active_user_sync(user, db)
    return user


async def get_current_app_user(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_active_user),
) -> AppUser | None:
    """Returns AppUser row for non-super-admins; None for super admins.
    is_active and permission_version already enforced by get_current_active_user."""
    username = user.get("sub", "")
    if is_super_admin(username):
        return None
    return db.query(AppUser).filter(AppUser.username == username).first()


async def require_admin(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_active_user),
) -> dict:
    username = user.get("sub", "")
    if is_super_admin(username):
        return user
    # is_active + pv already enforced by get_current_active_user; only check is_admin
    app_user = db.query(AppUser).filter(AppUser.username == username).first()
    if not app_user or not app_user.is_admin:
        _audit(username, "permission_denied", detail={"reason": "not_admin"})
        raise HTTPException(403, "Admin access required")
    return user


def require_permission(permission: str):
    """Phase 0: any active authenticated user has all permissions.
    is_active + permission_version enforced by get_current_active_user."""
    async def _check(
        user: dict = Depends(get_current_active_user),
    ) -> dict:
        return user
    return _check


# ── Audit logging ─────────────────────────────────────────────────────────────

def _audit(
    username: str,
    action: str,
    ip: str = "unknown",
    job_id: int | None = None,
    detail: dict | None = None,
):
    """Write an audit record using a dedicated session so caller session state
    never affects the write, and audit failure never breaks the response."""
    logger.info("audit: action=%s user=%s job_id=%s", action, username, job_id)
    _db = SessionLocal()
    try:
        _db.add(AuditLog(
            username=username,
            action=action,
            ip_address=ip,
            job_id=job_id,
            detail=json.dumps(detail, ensure_ascii=False) if detail else None,
        ))
        _db.commit()
        logger.info("audit: committed action=%s user=%s", action, username)
    except Exception as exc:
        logger.error("audit: write failed [action=%s user=%s]: %s", action, username, exc)
        try:
            _db.rollback()
        except Exception:
            pass
    finally:
        _db.close()


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ── Price helpers ─────────────────────────────────────────────────────────────

def _price_differs(old: str | None, new: str) -> bool:
    old_empty = not old or old == ""
    new_empty = not new or new == ""
    if old_empty and new_empty:
        return False
    if old_empty or new_empty:
        return True
    try:
        return abs(float(old) - float(new)) > 0.001
    except (ValueError, TypeError):
        return old != new


def _is_zero_price(price: str | None) -> bool:
    if not price or price.strip() == "":
        return True
    try:
        return float(price) == 0
    except (ValueError, TypeError):
        return False


def _stock_from_price(price: str | None) -> str:
    return "outofstock" if _is_zero_price(price) else "instock"


def _parse_wc_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


# ── Serialisers ───────────────────────────────────────────────────────────────

def _job_out(job: SyncJob) -> dict:
    return {
        "id": job.id,
        "created_at": job.created_at,
        "completed_at": job.completed_at,
        "status": job.status,
        "total_count": job.total_count,
        "updated_count": job.updated_count,
        "failed_count": job.failed_count,
        "skipped_count": job.skipped_count,
    }


def _item_out(item: SyncItem) -> dict:
    try:
        cats = json.loads(item.categories) if item.categories else []
    except Exception:
        cats = []
    return {
        "product_id": item.product_id,
        "product_name": item.product_name,
        "sku": item.sku or "",
        "old_price": item.old_price,
        "new_price": item.new_price,
        "sale_price": item.sale_price or "",
        "stock_status": item.stock_status or "",
        "stock_quantity": item.stock_quantity,
        "categories": cats,
        "row_color": item.row_color,
        "status": item.status,
        "error_message": item.error_message,
        "synced_at": item.synced_at,
        "last_price_updated": item.last_price_updated,
        "wc_date_modified": item.wc_date_modified,
        "changed": _price_differs(item.old_price, item.new_price),
    }


def _build_preview_row(
    pid: int,
    wc: dict,
    new_price: str,
    row_color: str | None = None,
    last_price_updated=None,
    sheet_name: str = "",
) -> dict:
    old_price = wc.get("price") or None
    lpu = last_price_updated
    if isinstance(lpu, datetime):
        lpu = lpu.isoformat()
    return {
        "product_id": pid,
        "product_name": sheet_name or wc.get("name", ""),
        "sku": wc.get("sku", ""),
        "old_price": old_price or "",
        "new_price": new_price,
        "sale_price": wc.get("sale_price", ""),
        "stock_status": wc.get("stock_status", ""),
        "stock_quantity": wc.get("stock_quantity"),
        "categories": wc.get("categories", []),
        "parent_id": wc.get("parent_id", 0),
        "row_color": row_color,
        "last_price_updated": lpu,
        "wc_date_modified": wc.get("wc_date_modified"),
        "changed": _price_differs(old_price, new_price),
        "found_in_wc": bool(wc),
    }


async def _sync_parent_stock(updates: list[dict], result_map: dict, db=None) -> None:
    """After variation price sync, set parent stock_status based on all its variations."""
    parents: dict[int, dict[int, str]] = {}
    for u in updates:
        pid = u.get("parent_id", 0)
        if pid and result_map.get(u["product_id"], {}).get("success"):
            parents.setdefault(pid, {})[u["product_id"]] = u["stock_status"]

    if not parents:
        return

    parent_statuses: dict[int, str] = {}
    for parent_id, var_statuses in parents.items():
        if any(s == "instock" for s in var_statuses.values()):
            parent_statuses[parent_id] = "instock"
        else:
            try:
                all_vars = await fetch_all_variations_stock(parent_id)
                merged = {v["id"]: var_statuses.get(v["id"], v["stock_status"]) for v in all_vars}
                parent_statuses[parent_id] = "outofstock" if all(s == "outofstock" for s in merged.values()) else "instock"
            except Exception:
                pass

    await update_parent_stock_statuses(parent_statuses)

    if db is not None:
        for parent_id, status in parent_statuses.items():
            _ch = patch_cached_product(db, parent_id, {"stock_status": status})
            logger.info(
                "_sync_parent_stock: patched parent cache pid=%d stock_status=%s hit=%s",
                parent_id, status, _ch,
            )


def _get_last_synced(db: Session, product_ids: list[int]) -> dict[int, datetime | None]:
    """Return {product_id: most_recent_synced_at} for successfully updated items."""
    if not product_ids:
        return {}
    rows = (
        db.query(SyncItem.product_id, func.max(SyncItem.synced_at).label("last_synced"))
        .filter(SyncItem.product_id.in_(product_ids), SyncItem.status == ItemStatus.updated)
        .group_by(SyncItem.product_id)
        .all()
    )
    return {r.product_id: r.last_synced for r in rows}


# ── Static dashboard ──────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    return (static_dir / "index.html").read_text(encoding="utf-8")


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    s = get_settings()
    return {"status": "ok", "wc_url": s.wc_url, "nextcloud_url": s.nextcloud_url}


# ── Cache management ──────────────────────────────────────────────────────────

@app.get("/api/cache/status")
async def cache_status(user: dict = Depends(get_current_active_user)):
    s = get_settings()
    info = get_cache_info()
    return {
        **info,
        "ttl_hours": s.wc_cache_ttl_hours,
        "auto_fetch_hours": s.wc_auto_fetch_hours,
    }


@app.post("/api/cache/clear")
async def cache_clear(user: dict = Depends(require_admin)):
    clear_product_cache()
    return {"message": "Product cache cleared"}


# ── DB product cache endpoints ────────────────────────────────────────────────

@app.get("/api/products")
async def list_cached_products(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    search: str | None = Query(None),
    product_type: str | None = Query(None),
    user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Return paginated products from the local DB cache with optional filters."""
    import math
    items, total = cache_get_page(db, page=page, limit=limit, search=search, product_type=product_type)
    return {
        "page": page,
        "limit": limit,
        "total": total,
        "total_pages": math.ceil(total / limit) if total else 0,
        "items": items,
    }


@app.get("/api/products/cache-status")
async def db_cache_status(user: dict = Depends(get_current_active_user), db: Session = Depends(get_db)):
    return cache_get_stats(db)


@app.post("/api/products/cache-clear")
async def db_cache_clear(user: dict = Depends(require_admin), db: Session = Depends(get_db)):
    count = cache_clear_all(db)
    db.commit()
    return {"message": f"Cleared {count} products from DB cache"}


@app.get("/api/products/{wc_id}/thumb")
async def product_thumb(
    wc_id: int,
    size: int = Query(96),
    db: Session = Depends(get_db),
):
    """Return a JPEG thumbnail for a product (96×96 by default; also 128, 256).
    Served from disk cache; generated lazily on first request using Pillow."""
    size = min(_THUMB_SIZES, key=lambda s: abs(s - size))  # snap to nearest valid size
    thumb_dir = _get_thumb_dir()
    thumb_path = _thumb_path(thumb_dir, wc_id, size)

    if thumb_path.exists():
        return Response(content=thumb_path.read_bytes(), media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=86400"})

    row = db.query(ProductCache).filter(ProductCache.wc_id == wc_id).first()

    logger.warning(
        "thumb: wc_id=%d row_found=%d image=%d parent_id=%s",
        wc_id,
        1 if row else 0,
        1 if (row and row.image_url) else 0,
        row.parent_id if row else "N/A",
    )

    # Case 1: known variation with no own image → fall back to parent image
    if row and not row.image_url and row.parent_id:
        parent = db.query(ProductCache).filter(ProductCache.wc_id == row.parent_id).first()
        logger.warning(
            "thumb: parent fallback parent_id=%d parent_found=%d parent_image=%d",
            row.parent_id,
            1 if parent else 0,
            1 if (parent and parent.image_url) else 0,
        )
        if parent and parent.image_url:
            logger.warning(
                "thumb: returning parent image for wc_id=%d parent_id=%d url=%s",
                wc_id, row.parent_id, parent.image_url,
            )
            row = parent

    # Case 2: unknown ID (not in products_cache) → resolve parent via SyncItem then WC API
    elif not row:
        parent_id: int | None = None
        sync_row = (
            db.query(SyncItem)
            .filter(SyncItem.product_id == wc_id, SyncItem.parent_id > 0)
            .order_by(SyncItem.id.desc())
            .first()
        )
        if sync_row:
            parent_id = sync_row.parent_id
            logger.warning("thumb: resolved parent_id=%d for wc_id=%d via SyncItem", parent_id, wc_id)
        else:
            parent_id = await resolve_variation_parent_id(wc_id)
            if parent_id:
                logger.warning("thumb: resolved parent_id=%d for wc_id=%d via WC API", parent_id, wc_id)

        if parent_id:
            parent = db.query(ProductCache).filter(ProductCache.wc_id == parent_id).first()
            if parent and parent.image_url:
                try:
                    upsert_products(db, [{"wc_id": wc_id, "parent_id": parent_id, "product_type": "variation"}])
                    db.commit()
                    logger.warning("thumb: stubbed variation row wc_id=%d parent_id=%d", wc_id, parent_id)
                except Exception:
                    db.rollback()
                row = parent

    if not row or not row.image_url:
        logger.warning("thumb: returning placeholder for wc_id=%d", wc_id)
        return Response(content=_EMPTY_THUMB, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=300"})

    if not _PIL_OK:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url=row.image_url)

    try:
        async with _THUMB_SEM:
            t0 = time.monotonic()
            async with httpx.AsyncClient(timeout=5, follow_redirects=True) as client:
                resp = await client.get(row.image_url)
                resp.raise_for_status()
            elapsed = time.monotonic() - t0
            if elapsed > 2:
                logger.warning("thumb download slow: wc_id=%d size=%d took %.1fs url=%s",
                               wc_id, size, elapsed, row.image_url)
        img = _PilImage.open(_io.BytesIO(resp.content))
        img.thumbnail((size, size), _PilImage.LANCZOS)
        canvas = _PilImage.new("RGB", (size, size), (248, 248, 248))
        offset = ((size - img.width) // 2, (size - img.height) // 2)
        paste_img = img.convert("RGBA") if img.mode in ("P", "LA") else img
        if paste_img.mode == "RGBA":
            canvas.paste(paste_img, offset, paste_img)
        else:
            canvas.paste(paste_img.convert("RGB"), offset)
        buf = _io.BytesIO()
        canvas.save(buf, format="JPEG", quality=85, optimize=True)
        thumb_bytes = buf.getvalue()
        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        thumb_path.write_bytes(thumb_bytes)
        return Response(content=thumb_bytes, media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=86400"})
    except Exception as exc:
        logger.warning("thumb generation failed for wc_id=%d size=%d: %s", wc_id, size, exc)
        return Response(content=_EMPTY_THUMB, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=60"})


@app.get("/api/fetch/full")
async def fetch_full_stream(request: Request, token: str | None = Query(None)):
    """Stream a full WooCommerce product sync into the DB cache."""
    logger.warning("FETCH_ROUTE_ENTERED: route=/api/fetch/full mode=full_sync ip=%s", _client_ip(request))
    creds = None
    raw = token
    if not raw:
        raw = request.headers.get("authorization", "").removeprefix("Bearer ").strip() or None
    if not raw:
        return StreamingResponse(
            iter(['data: {"error":"Not authenticated"}\n\n']),
            media_type="text/event-stream",
        )
    try:
        creds = decode_token(raw)
    except Exception:
        return StreamingResponse(
            iter(['data: {"error":"Invalid token"}\n\n']),
            media_type="text/event-stream",
        )
    _auth_db = SessionLocal()
    try:
        _validate_active_user_sync(creds, _auth_db)
    except HTTPException as _exc:
        return StreamingResponse(
            iter([f'data: {{"error":"{_exc.detail}"}}\n\n']),
            media_type="text/event-stream",
        )
    finally:
        _auth_db.close()

    async def _gen():
        def ev(d: dict) -> str:
            return f"data: {json.dumps(d, ensure_ascii=False)}\n\n"

        _t0 = time.monotonic()
        yield ev({"step": "start", "status": "running", "msg": "Starting fast product cache refresh (top-level products + images, no variation sub-requests)…"})
        try:
            yield ev({"step": "fetch", "status": "running", "msg": "Fetching product catalog from WooCommerce (~24 pages, images included)…"})
            fetch_task = asyncio.create_task(fetch_all_products_fast())
            while not fetch_task.done():
                yield ": keepalive\n\n"
                await asyncio.sleep(10)
            products, _ = await fetch_task

            simple_count = sum(1 for p in products if p.get("product_type") == "simple")
            variable_count = sum(1 for p in products if p.get("product_type") == "variable")
            with_img_fetch = sum(1 for p in products if p.get("image_url"))
            yield ev({
                "step": "fetch",
                "status": "done",
                "msg": f"Fetched {len(products)} products from WooCommerce — {simple_count} simple, {variable_count} variable parents, {with_img_fetch} with images",
                "count": len(products),
                "simple_count": simple_count,
                "variable_count": variable_count,
                "with_image": with_img_fetch,
            })

            yield ev({"step": "upsert", "status": "running", "msg": f"Saving {len(products)} products to local cache…"})
            _db = SessionLocal()
            try:
                inserted, updated, img_changed = upsert_products(_db, products, image_sync_authoritative=True)
                _db.commit()
                _invalidate_thumbs(img_changed, _db)
            finally:
                _db.close()

            _elapsed = time.monotonic() - _t0
            without_img = len(products) - with_img_fetch
            logger.warning(
                "fast_fetch complete: total=%d inserted=%d updated=%d with_image=%d without_image=%d elapsed=%.1fs",
                len(products), inserted, updated, with_img_fetch, without_img, _elapsed,
            )
            yield ev({
                "step": "done",
                "status": "ok",
                "msg": (
                    f"Product cache refreshed: {inserted} new, {updated} updated "
                    f"({with_img_fetch} with images, {without_img} without) in {_elapsed:.0f}s. "
                    f"Variation thumbnails fall back to parent image automatically."
                ),
                "inserted": inserted,
                "updated": updated,
                "total": len(products),
                "with_image": with_img_fetch,
                "without_image": without_img,
                "elapsed_seconds": round(_elapsed, 1),
            })

        except asyncio.CancelledError:
            logger.warning("fetch/full SSE stream cancelled")
            raise
        except Exception as exc:
            logger.exception("fetch/full failed: %s", exc)
            yield ev({"step": "error", "status": "error", "msg": str(exc)})

    return StreamingResponse(_gen(), media_type="text/event-stream", headers=_SSE_HEADERS)


@app.get("/api/fetch/deep-variations")
async def fetch_deep_variations_stream(request: Request, token: str | None = Query(None)):
    """Stream a full variation sync for all variable parents. Slow admin-only job."""
    logger.warning("FETCH_ROUTE_ENTERED: route=/api/fetch/deep-variations mode=deep_variation_sync ip=%s", _client_ip(request))
    raw = token
    if not raw:
        raw = request.headers.get("authorization", "").removeprefix("Bearer ").strip() or None
    if not raw:
        return StreamingResponse(
            iter(['data: {"error":"Not authenticated"}\n\n']),
            media_type="text/event-stream",
        )
    try:
        _deep_creds = decode_token(raw)
    except Exception:
        return StreamingResponse(
            iter(['data: {"error":"Invalid token"}\n\n']),
            media_type="text/event-stream",
        )
    _auth_db = SessionLocal()
    try:
        _validate_active_user_sync(_deep_creds, _auth_db)
    except HTTPException as _exc:
        return StreamingResponse(
            iter([f'data: {{"error":"{_exc.detail}"}}\n\n']),
            media_type="text/event-stream",
        )
    finally:
        _auth_db.close()

    async def _gen_deep():
        def ev(d: dict) -> str:
            return f"data: {json.dumps(d, ensure_ascii=False)}\n\n"

        yield ev({"step": "start", "status": "running", "msg": "Starting deep variation sync — fetching ALL products + ALL variations. This may take 40–60 minutes for 2000+ variable parents…"})
        try:
            yield ev({"step": "fetch", "status": "running", "msg": "Fetching all products and all variation pages from WooCommerce…"})
            fetch_task = asyncio.create_task(fetch_all_products_full())
            while not fetch_task.done():
                yield ": keepalive\n\n"
                await asyncio.sleep(10)
            products, var_warnings = await fetch_task

            for w in var_warnings:
                logger.warning("fetch/deep-variations warning: %s", w)
                yield ev({"step": "warning", "status": "warning", "msg": w})

            yield ev({
                "step": "fetch",
                "status": "done",
                "msg": f"Fetched {len(products)} products+variations from WooCommerce"
                       + (f" ({len(var_warnings)} warning(s))" if var_warnings else ""),
                "count": len(products),
                "warnings": len(var_warnings),
            })

            yield ev({"step": "upsert", "status": "running", "msg": f"Saving {len(products)} records to local cache…"})
            _db = SessionLocal()
            try:
                inserted, updated, img_changed = upsert_products(_db, products, image_sync_authoritative=True)
                _db.commit()
                _invalidate_thumbs(img_changed, _db)
            finally:
                _db.close()

            yield ev({
                "step": "done",
                "status": "ok",
                "msg": f"Deep sync complete: {inserted} new, {updated} updated ({len(products)} total)",
                "inserted": inserted,
                "updated": updated,
                "total": len(products),
            })

        except asyncio.CancelledError:
            logger.warning("fetch/deep-variations SSE stream cancelled")
            raise
        except Exception as exc:
            logger.exception("fetch/deep-variations failed: %s", exc)
            yield ev({"step": "error", "status": "error", "msg": str(exc)})

    return StreamingResponse(_gen_deep(), media_type="text/event-stream", headers=_SSE_HEADERS)


@app.get("/api/fetch/light")
async def fetch_light_stream(
    request: Request,
    token: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """Stream a light sync (only products modified since last sync) into the DB cache."""
    logger.warning("FETCH_ROUTE_ENTERED: route=/api/fetch/light mode=light_sync ip=%s", _client_ip(request))
    raw = token
    if not raw:
        raw = request.headers.get("authorization", "").removeprefix("Bearer ").strip() or None
    if not raw:
        return StreamingResponse(
            iter(['data: {"error":"Not authenticated"}\n\n']),
            media_type="text/event-stream",
        )
    try:
        _light_creds = decode_token(raw)
    except Exception:
        return StreamingResponse(
            iter(['data: {"error":"Invalid token"}\n\n']),
            media_type="text/event-stream",
        )
    try:
        _validate_active_user_sync(_light_creds, db)
    except HTTPException as _exc:
        return StreamingResponse(
            iter([f'data: {{"error":"{_exc.detail}"}}\n\n']),
            media_type="text/event-stream",
        )

    last_sync = get_last_sync_time(db)
    if last_sync is None:
        return StreamingResponse(
            iter(['data: {"error":"No prior full sync found. Run full sync first."}\n\n']),
            media_type="text/event-stream",
        )
    modified_after = last_sync.strftime("%Y-%m-%dT%H:%M:%S")

    async def _gen():
        def ev(d: dict) -> str:
            return f"data: {json.dumps(d, ensure_ascii=False)}\n\n"

        yield ev({"step": "start", "status": "running", "msg": f"Fetching products modified after {modified_after}…"})
        try:
            yield ev({"step": "fetch", "status": "running", "msg": "Connecting to WooCommerce…"})
            fetch_task = asyncio.create_task(fetch_products_modified_after(modified_after))
            while not fetch_task.done():
                yield ": keepalive\n\n"
                await asyncio.sleep(10)
            products, var_warnings = await fetch_task

            for w in var_warnings:
                logger.warning("fetch/light variation warning: %s", w)
                yield ev({"step": "warning", "status": "warning", "msg": w})

            yield ev({
                "step": "fetch",
                "status": "done",
                "msg": f"Fetched {len(products)} modified products",
                "count": len(products),
                "warnings": len(var_warnings),
            })

            yield ev({"step": "upsert", "status": "running", "msg": f"Updating {len(products)} products in local cache…"})
            _db = SessionLocal()
            try:
                inserted, updated, img_changed = upsert_products(_db, products, image_sync_authoritative=True)
                _db.commit()
                _invalidate_thumbs(img_changed, _db)
            finally:
                _db.close()

            yield ev({
                "step": "done",
                "status": "ok",
                "msg": f"Light sync complete: {inserted} new, {updated} updated",
                "inserted": inserted,
                "updated": updated,
                "total": len(products),
            })

        except asyncio.CancelledError:
            logger.warning("fetch/light SSE stream cancelled")
            raise
        except Exception as exc:
            logger.exception("fetch/light failed: %s", exc)
            yield ev({"step": "error", "status": "error", "msg": str(exc)})

    return StreamingResponse(_gen(), media_type="text/event-stream", headers=_SSE_HEADERS)


# ── Sheet debug (admin) ───────────────────────────────────────────────────────

@app.get("/api/debug/sheet")
async def debug_sheet(user: dict = Depends(require_admin)):
    """Download the sheet and return the first 12 rows × 8 cols as raw values."""
    import io as _io
    from openpyxl import load_workbook as _lw
    xlsx = await download_xlsx()
    wb = _lw(filename=_io.BytesIO(xlsx), data_only=True)
    ws = wb.active
    rows = []
    for r in range(1, 13):
        row = []
        for c in range(1, 9):
            v = ws.cell(row=r, column=c).value
            row.append({"col": c, "value": str(v) if v is not None else None, "type": type(v).__name__})
        rows.append({"row": r, "cells": row})
    return {"sheet_name": ws.title, "rows": rows}


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.post("/api/auth/login")
async def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    if not body.username or not body.password:
        raise HTTPException(400, "Username and password required")
    try:
        valid = await verify_nextcloud_credentials(body.username, body.password)
    except Exception as exc:
        raise HTTPException(503, f"Nextcloud unreachable: {exc}")
    if not valid:
        raise HTTPException(401, "Invalid Nextcloud credentials")
    ip = _client_ip(request)
    # Super admins bypass the app_users table entirely
    if is_super_admin(body.username):
        token = create_token(body.username, permission_version=0, role="admin")
        _audit(body.username, "login", ip)
        return {"token": token, "username": body.username, "role": "admin"}
    # Regular users: must exist in app_users and be active
    app_user = db.query(AppUser).filter(AppUser.username == body.username).first()
    if app_user is None or not app_user.is_active:
        _audit(body.username, "login_denied_not_in_access_list", ip)
        raise HTTPException(403, "Access not granted — contact your administrator")
    role = "admin" if app_user.is_admin else "user"
    token = create_token(body.username, permission_version=app_user.permission_version, role=role)
    _audit(body.username, "login_allowed_user_access", ip)
    return {"token": token, "username": body.username, "role": role}


@app.get("/api/auth/me")
async def me(user: dict = Depends(get_current_active_user)):
    return {"username": user["sub"], "role": user["role"]}


# ── App Users (admin) ─────────────────────────────────────────────────────────

def _app_user_dict(row: AppUser) -> dict:
    return {
        "id": row.id,
        "username": row.username,
        "display_name": row.display_name,
        "is_active": row.is_active,
        "is_admin": row.is_admin,
        "permission_version": row.permission_version,
        "notes": row.notes,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@app.get("/api/admin/app-users")
async def list_app_users(
    user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows = db.query(AppUser).order_by(AppUser.username).all()
    return [_app_user_dict(r) for r in rows]


@app.post("/api/admin/app-users", status_code=201)
async def create_app_user(
    body: AppUserCreate,
    user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if db.query(AppUser).filter(AppUser.username == body.username).first():
        raise HTTPException(409, "User already exists")
    row = AppUser(
        username=body.username,
        display_name=body.display_name,
        is_admin=body.is_admin,
        notes=body.notes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _app_user_dict(row)


@app.patch("/api/admin/app-users/{username}")
async def update_app_user(
    username: str,
    body: AppUserUpdate,
    user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    row = db.query(AppUser).filter(AppUser.username == username).first()
    if row is None:
        raise HTTPException(404, "User not found")
    if body.display_name is not None:
        row.display_name = body.display_name
    if body.is_active is not None:
        row.is_active = body.is_active
    if body.is_admin is not None:
        row.is_admin = body.is_admin
    if body.notes is not None:
        row.notes = body.notes
    row.updated_at = datetime.utcnow()
    db.commit()
    return _app_user_dict(row)


@app.delete("/api/admin/app-users/{username}", status_code=204)
async def delete_app_user(
    username: str,
    user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    row = db.query(AppUser).filter(AppUser.username == username).first()
    if row is None:
        raise HTTPException(404, "User not found")
    db.delete(row)
    db.commit()
    return Response(status_code=204)


@app.post("/api/admin/app-users/{username}/revoke-tokens")
async def revoke_user_tokens(
    username: str,
    user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    row = db.query(AppUser).filter(AppUser.username == username).first()
    if row is None:
        raise HTTPException(404, "User not found")
    row.permission_version = (row.permission_version or 1) + 1
    row.updated_at = datetime.utcnow()
    db.commit()
    return {"username": username, "permission_version": row.permission_version}


# ── Settings (admin) ──────────────────────────────────────────────────────────

@app.get("/api/settings")
async def get_app_settings(user: dict = Depends(require_admin)):
    s = get_settings()
    def mask(v: str) -> str:
        return v[:4] + "****" if len(v) > 4 else "****"
    return {
        "wc_url": s.wc_url,
        "wc_key": mask(s.wc_key),
        "wc_secret": mask(s.wc_secret),
        "nextcloud_url": s.nextcloud_url,
        "nextcloud_user": s.nextcloud_user,
        "nextcloud_file_path": s.nextcloud_file_path,
        "super_admin_users": s.super_admin_users,
        "wc_cache_ttl_hours": s.wc_cache_ttl_hours,
        "wc_auto_fetch_hours": s.wc_auto_fetch_hours,
    }


# ── Alarm thresholds ──────────────────────────────────────────────────────────

@app.get("/api/alarm-settings")
async def get_alarm_settings(user: dict = Depends(get_current_active_user), db: Session = Depends(get_db)):
    rows = db.query(AlarmThreshold).all()
    return [{"category_id": r.category_id, "threshold_percent": r.threshold_percent} for r in rows]


@app.put("/api/alarm-settings")
async def set_alarm_settings(
    thresholds: list[AlarmThresholdItem],
    user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    db.query(AlarmThreshold).delete()
    for t in thresholds:
        if t.threshold_percent > 0:
            db.add(AlarmThreshold(category_id=t.category_id, threshold_percent=t.threshold_percent))
    db.commit()
    return {"message": "Alarm thresholds saved"}


# ── Audit logs ────────────────────────────────────────────────────────────────

@app.get("/api/audit-logs")
async def get_audit_logs(
    limit: int = 200,
    user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    logs = db.query(AuditLog).order_by(AuditLog.timestamp.desc()).limit(limit).all()
    result = []
    for l in logs:
        entry = {
            "id": l.id,
            "username": l.username,
            "action": l.action,
            "timestamp": l.timestamp,
            "ip_address": l.ip_address,
            "job_id": l.job_id,
            "detail": None,
        }
        if l.detail:
            try:
                entry["detail"] = json.loads(l.detail)
            except Exception:
                entry["detail"] = l.detail
        result.append(entry)
    return result


# ── Categories (cached 5 min) ─────────────────────────────────────────────────

_cat_cache: dict = {"data": None, "ts": 0.0}

@app.get("/api/categories")
async def get_categories(user: dict = Depends(get_current_active_user)):
    if _cat_cache["data"] is not None and time.time() - _cat_cache["ts"] < 300:
        return _cat_cache["data"]
    try:
        data = await fetch_categories()
    except Exception as exc:
        if _cat_cache["data"] is not None:
            return _cat_cache["data"]  # serve stale on error
        raise HTTPException(502, f"Cannot fetch categories from WooCommerce: {exc}")
    _cat_cache["data"] = data
    _cat_cache["ts"] = time.time()
    return data


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.get("/api/dashboard")
async def get_dashboard(user: dict = Depends(get_current_active_user), db: Session = Depends(get_db)):
    total_syncs = db.query(SyncJob).filter(SyncJob.status == JobStatus.completed).count()

    latest_job = (
        db.query(SyncJob)
        .filter(SyncJob.status == JobStatus.completed)
        .order_by(SyncJob.created_at.desc())
        .first()
    )

    product_stats = {"total": 0, "in_stock": 0, "out_of_stock": 0}
    if latest_job:
        items = db.query(SyncItem).filter(SyncItem.job_id == latest_job.id).all()
        product_stats["total"] = len(items)
        product_stats["in_stock"] = sum(1 for i in items if i.stock_status == "instock")
        product_stats["out_of_stock"] = sum(1 for i in items if i.stock_status == "outofstock")

    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    recent_jobs = (
        db.query(SyncJob)
        .filter(SyncJob.status == JobStatus.completed, SyncJob.created_at >= thirty_days_ago)
        .order_by(SyncJob.created_at.asc())
        .all()
    )
    daily_syncs: dict[str, int] = defaultdict(int)
    for j in recent_jobs:
        daily_syncs[j.created_at.date().isoformat()] += 1

    recent_logs = db.query(AuditLog).order_by(AuditLog.timestamp.desc()).limit(8).all()

    return {
        "total_syncs": total_syncs,
        "latest_job": _job_out(latest_job) if latest_job else None,
        "product_stats": product_stats,
        "sync_chart": [{"date": k, "count": v} for k, v in sorted(daily_syncs.items())],
        "recent_logs": [
            {
                "username": l.username,
                "action": l.action,
                "timestamp": l.timestamp,
                "ip_address": l.ip_address,
            }
            for l in recent_logs
        ],
    }


# ── Analytics ─────────────────────────────────────────────────────────────────

@app.get("/api/analytics")
async def get_analytics(user: dict = Depends(get_current_active_user), db: Session = Depends(get_db)):
    # Get the most recent SyncItem per product_id (across all completed jobs)
    latest_id_sq = (
        db.query(func.max(SyncItem.id).label("max_id"))
        .join(SyncJob, SyncItem.job_id == SyncJob.id)
        .filter(SyncJob.status.in_([JobStatus.completed, JobStatus.preview]))
        .group_by(SyncItem.product_id)
        .subquery()
    )
    items = (
        db.query(SyncItem)
        .filter(SyncItem.id.in_(latest_id_sq))
        .all()
    )

    one_week_ago = datetime.utcnow() - timedelta(days=7)

    in_stock_no_price = []
    has_price_out_of_stock = []
    stale_products = []

    for item in items:
        d = _item_out(item)
        price_empty = not item.new_price or item.new_price in ("", "0.00")
        price_set = item.new_price and item.new_price not in ("", "0.00")

        if item.stock_status == "instock" and price_empty:
            in_stock_no_price.append(d)

        if price_set and item.stock_status == "outofstock":
            has_price_out_of_stock.append(d)

        last_update = item.wc_date_modified or item.last_price_updated or item.synced_at
        if last_update is None or last_update < one_week_ago:
            stale_products.append(d)

    return {
        "in_stock_no_price": in_stock_no_price,
        "has_price_out_of_stock": has_price_out_of_stock,
        "stale_products": stale_products,
    }


# ── Live price/stock update ───────────────────────────────────────────────────

@app.get("/api/products/{product_id}/lookup")
async def lookup_product(
    product_id: int,
    user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Resolve a product ID to its type and parent_id.
    Checks local DB cache first; falls back to a direct WooCommerce query."""
    row = db.query(ProductCache).filter(ProductCache.wc_id == product_id).first()
    if row:
        return {
            "found": True,
            "source": "cache",
            "wc_id": row.wc_id,
            "product_type": row.product_type or "simple",
            "parent_id": row.parent_id or 0,
            "name": row.name or "",
            "sku": row.sku or "",
            "status": row.status or "",
            "regular_price": row.regular_price or "",
            "final_price": row.final_price or "",
            "effective_price": row.final_price or row.regular_price or "",
            "sale_price": row.sale_price or "",
            "stock_status": row.stock_status or "",
            "stock_quantity": row.stock_quantity,
            "cache_version": row.cache_version or 0,
            "last_synced_at": row.last_synced_at.isoformat() if row.last_synced_at else None,
            "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
        }
    try:
        return await lookup_product_info(product_id)
    except Exception as exc:
        raise HTTPException(502, f"WooCommerce lookup failed: {exc}")


def _resolve_parent_id(db: Session, product_id: int, requested: int) -> int:
    """Return the best available parent_id for a product.
    Caller-supplied value always wins; falls back to DB cache."""
    if requested and requested > 0:
        return requested
    row = db.query(ProductCache).filter(ProductCache.wc_id == product_id).first()
    return (row.parent_id or 0) if row else 0


@app.put("/api/products/{product_id}/price")
async def update_price(
    product_id: int,
    body: PriceUpdateRequest,
    request: Request,
    user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    logger.info("update_price: product_id=%s user=%s", product_id, user.get("sub"))
    effective_parent_id = _resolve_parent_id(db, product_id, body.parent_id or 0)
    ip = _client_ip(request)

    # Read old price from cache before overwriting it
    cache_row = db.query(ProductCache).filter(ProductCache.wc_id == product_id).first()
    old_price = (cache_row.final_price or cache_row.regular_price) if cache_row else None

    try:
        await update_single_product(product_id, {"regular_price": body.new_price}, effective_parent_id)
    except Exception as exc:
        raise HTTPException(502, f"WooCommerce update failed: {exc}")

    # Patch cache and write audit BEFORE Nextcloud writeback — ensures the record
    # is always committed once WooCommerce accepts the change.
    cache_hit = patch_cached_product(db, product_id, {
        "regular_price": body.new_price,
        "final_price": body.new_price,
    })
    db.commit()
    logger.info("update_price: cache patched product_id=%s cache_hit=%s", product_id, cache_hit)
    _audit(user["sub"], "update_price", ip=ip, detail={
        "product_id": product_id,
        "parent_id": effective_parent_id,
        "old_price": old_price,
        "new_price": body.new_price,
        "cache_hit": cache_hit,
    })

    try:
        await write_price_to_sheet(product_id, body.new_price)
    except Exception as exc:
        raise HTTPException(502, f"Excel writeback failed: {exc}")

    now = datetime.utcnow()
    if body.job_id:
        item = (
            db.query(SyncItem)
            .filter(SyncItem.job_id == body.job_id, SyncItem.product_id == product_id)
            .first()
        )
        if item:
            item.new_price = body.new_price
            item.last_price_updated = now
            db.commit()

    result: dict = {"success": True, "product_id": product_id, "new_price": body.new_price}
    if not cache_hit:
        result["warning"] = "WooCommerce updated, but product was not present in local cache."
    return result


@app.put("/api/products/{product_id}/stock")
async def update_stock(
    product_id: int,
    body: StockUpdateRequest,
    request: Request,
    user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    logger.info("update_stock: product_id=%s user=%s", product_id, user.get("sub"))
    wc_payload: dict = {"stock_status": body.stock_status}
    if body.stock_quantity is not None:
        wc_payload["stock_quantity"] = body.stock_quantity
        wc_payload["manage_stock"] = True

    effective_parent_id = _resolve_parent_id(db, product_id, body.parent_id or 0)
    ip = _client_ip(request)

    # Read old stock from cache before overwriting it
    cache_row = db.query(ProductCache).filter(ProductCache.wc_id == product_id).first()
    old_stock_status = cache_row.stock_status if cache_row else None
    old_stock_quantity = cache_row.stock_quantity if cache_row else None

    try:
        await update_single_product(product_id, wc_payload, effective_parent_id)
    except Exception as exc:
        raise HTTPException(502, f"WooCommerce update failed: {exc}")

    cache_fields: dict = {"stock_status": body.stock_status}
    if body.stock_quantity is not None:
        cache_fields["stock_quantity"] = body.stock_quantity
    cache_hit = patch_cached_product(db, product_id, cache_fields)
    db.commit()
    logger.info("update_stock: cache patched product_id=%s cache_hit=%s", product_id, cache_hit)
    _audit(user["sub"], "update_stock", ip=ip, detail={
        "product_id": product_id,
        "parent_id": effective_parent_id,
        "old_stock_status": old_stock_status,
        "new_stock_status": body.stock_status,
        "old_stock_quantity": old_stock_quantity,
        "new_stock_quantity": body.stock_quantity,
        "cache_hit": cache_hit,
    })

    if body.job_id:
        item = (
            db.query(SyncItem)
            .filter(SyncItem.job_id == body.job_id, SyncItem.product_id == product_id)
            .first()
        )
        if item:
            item.stock_status = body.stock_status
            if body.stock_quantity is not None:
                item.stock_quantity = body.stock_quantity
            db.commit()

    result: dict = {"success": True, "product_id": product_id}
    if not cache_hit:
        result["warning"] = "WooCommerce updated, but product was not present in local cache."
    return result


# ── System diagnostics ────────────────────────────────────────────────────────

@app.get("/api/system/diagnostics")
async def system_diagnostics(user: dict = Depends(get_current_active_user), db: Session = Depends(get_db)):
    if not is_super_admin(user["sub"]):
        raise HTTPException(403, "Admin only")

    import subprocess
    settings = get_settings()
    products_count = db.query(func.count(ProductCache.wc_id)).scalar() or 0
    audit_count = db.query(func.count(AuditLog.id)).scalar() or 0
    last_fetch = get_last_sync_time(db)

    secret_bytes = len(settings.jwt_secret.encode())
    jwt_status = f"ok ({secret_bytes} bytes)" if secret_bytes >= 32 else f"INSECURE — only {secret_bytes} bytes, need 32+"

    try:
        git_hash = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            text=True, stderr=subprocess.DEVNULL, timeout=3
        ).strip()
    except Exception:
        git_hash = "unavailable"

    return {
        "db_path": settings.database_url,
        "products_cache_count": products_count,
        "audit_logs_count": audit_count,
        "last_full_fetch": last_fetch.isoformat() if last_fetch else None,
        "jwt_secret_status": jwt_status,
        "wc_url": settings.wc_url,
        "nextcloud_url": settings.nextcloud_url,
        "git_commit": git_hash,
    }


# ── 1. Create preview ─────────────────────────────────────────────────────────

@app.post("/api/preview")
async def create_preview(user: dict = Depends(get_current_active_user), db: Session = Depends(get_db)):
    logger.warning("FETCH_ROUTE_ENTERED: route=/api/preview mode=create_preview user=%s", user.get("sub", "?"))
    try:
        xlsx = await download_xlsx(force=True)
    except Exception as exc:
        raise HTTPException(502, f"Cannot download sheet from Nextcloud: {exc}")

    _xlsx_meta = get_cached_xlsx_meta()
    logger.info(
        "create_preview: xlsx downloaded size=%d etag=%s last_modified=%s",
        len(xlsx), _xlsx_meta.get("etag") or "", _xlsx_meta.get("last_modified") or "",
    )

    _sheet_hash = hashlib.md5(xlsx).hexdigest()
    sheet_items, dup_warnings = parse_price_list(xlsx)
    if not sheet_items:
        raise HTTPException(400, "No valid rows found.")

    product_ids = [i["product_id"] for i in sheet_items]

    # Use persistent DB cache; only fetch missing products from WooCommerce
    wc_data = get_cached_by_ids(db, product_ids)
    missing_ids = [pid for pid in product_ids if pid not in wc_data]
    if missing_ids:
        try:
            fresh = await fetch_product_prices(missing_ids, force=True)
        except Exception as exc:
            raise HTTPException(502, f"Cannot fetch prices from WooCommerce: {exc}")
        cache_rows = [wc_response_to_cache_dict(pid, d) for pid, d in fresh.items()]
        upsert_products(db, cache_rows)
        db.commit()
        wc_data.update(get_cached_by_ids(db, list(fresh.keys())))

    last_synced = _get_last_synced(db, product_ids)

    job = SyncJob(status=JobStatus.preview, total_count=len(sheet_items), sheet_hash=_sheet_hash)
    db.add(job)
    db.flush()

    preview_rows = []
    for row in sheet_items:
        pid = row["product_id"]
        wc = wc_data.get(pid, {})
        old_price = wc.get("price") or None
        sname = row.get("sheet_name") or wc.get("name") or None
        db.add(SyncItem(
            job_id=job.id, product_id=pid,
            parent_id=wc.get("parent_id") or 0,
            product_name=sname,
            sku=wc.get("sku") or None,
            old_price=old_price, new_price=row["new_price"],
            sale_price=wc.get("sale_price") or None,
            stock_status=wc.get("stock_status") or None,
            stock_quantity=wc.get("stock_quantity"),
            categories=json.dumps(wc.get("categories", [])),
            row_color=row.get("row_color"),
            last_price_updated=last_synced.get(pid),
            wc_date_modified=_parse_wc_dt(wc.get("wc_date_modified")),
        ))
        preview_rows.append(_build_preview_row(
            pid, wc, row["new_price"],
            row_color=row.get("row_color"),
            last_price_updated=last_synced.get(pid),
            sheet_name=row.get("sheet_name", ""),
        ))

    db.commit()
    changed = sum(1 for r in preview_rows if r["changed"])
    return {
        "job_id": job.id, "total": len(preview_rows),
        "changed_count": changed, "unchanged_count": len(preview_rows) - changed,
        "items": preview_rows,
        "duplicate_warnings": dup_warnings,
    }


# ── 2. Confirm sync ───────────────────────────────────────────────────────────

@app.post("/api/sync/{job_id}/confirm")
async def confirm_sync(job_id: int, user: dict = Depends(get_current_active_user), db: Session = Depends(get_db)):
    job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status != JobStatus.preview:
        raise HTTPException(400, f"Job is '{job.status}', expected 'preview'")

    job.status = JobStatus.running
    db.commit()

    items = db.query(SyncItem).filter(SyncItem.job_id == job_id).all()
    to_update = [i for i in items if _price_differs(i.old_price, i.new_price)]
    to_skip   = [i for i in items if not _price_differs(i.old_price, i.new_price)]

    for item in to_skip:
        item.status = ItemStatus.skipped
        item.synced_at = datetime.utcnow()

    if to_update:
        updates = [
            {"product_id": i.product_id, "new_price": i.new_price,
             "parent_id": i.parent_id or 0, "stock_status": _stock_from_price(i.new_price)}
            for i in to_update
        ]
        try:
            wc_results = await batch_update_prices(updates)
        except Exception as exc:
            job.status = JobStatus.failed
            db.commit()
            raise HTTPException(502, f"WooCommerce batch update failed: {exc}")

        now = datetime.utcnow()
        result_map = {r["product_id"]: r for r in wc_results}
        for item in to_update:
            r = result_map.get(item.product_id, {})
            item.status = ItemStatus.updated if r.get("success") else ItemStatus.failed
            item.error_message = r.get("error_message")
            item.synced_at = now
            if r.get("success"):
                item.last_price_updated = now
                item.stock_status = _stock_from_price(item.new_price)
                if _is_zero_price(item.new_price):
                    logger.info(
                        "confirm outofstock: pid=%d name=%r parent=%d "
                        "blank/zero price → stock_status=outofstock",
                        item.product_id, item.product_name or "", item.parent_id or 0,
                    )
                _ch = patch_cached_product(db, item.product_id, {
                    "regular_price": item.new_price,
                    "final_price": item.new_price,
                    "stock_status": _stock_from_price(item.new_price),
                })
                logger.info(
                    "confirm_sync: cache patched pid=%d price=%s hit=%s",
                    item.product_id, item.new_price, _ch,
                )

        await _sync_parent_stock(updates, result_map, db)

    job.updated_count = sum(1 for i in items if i.status == ItemStatus.updated)
    job.failed_count  = sum(1 for i in items if i.status == ItemStatus.failed)
    job.skipped_count = sum(1 for i in items if i.status == ItemStatus.skipped)
    job.status = JobStatus.completed
    job.completed_at = datetime.utcnow()
    db.commit()
    return {"job_id": job_id, "status": "completed",
            "updated": job.updated_count, "failed": job.failed_count, "skipped": job.skipped_count}


# ── 3. Cancel preview ─────────────────────────────────────────────────────────

@app.delete("/api/sync/{job_id}")
async def cancel_sync(job_id: int, user: dict = Depends(get_current_active_user), db: Session = Depends(get_db)):
    job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status != JobStatus.preview:
        raise HTTPException(400, "Only preview jobs can be cancelled")
    job.status = JobStatus.cancelled
    db.commit()
    return {"job_id": job_id, "status": "cancelled"}


# ── 4. List jobs ──────────────────────────────────────────────────────────────

@app.get("/api/jobs")
async def list_jobs(limit: int = 30, user: dict = Depends(get_current_active_user), db: Session = Depends(get_db)):
    jobs = db.query(SyncJob).order_by(SyncJob.created_at.desc()).limit(limit).all()
    return [_job_out(j) for j in jobs]


# ── 5. Job detail ─────────────────────────────────────────────────────────────

@app.get("/api/jobs/{job_id}")
async def get_job(job_id: int, user: dict = Depends(get_current_active_user), db: Session = Depends(get_db)):
    job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    items = db.query(SyncItem).filter(SyncItem.job_id == job_id).all()
    return {**_job_out(job), "items": [_item_out(i) for i in items]}


# ── 6. Spreadsheet metadata (HEAD only — no download) ────────────────────────

@app.get("/api/spreadsheet/meta")
async def spreadsheet_meta_endpoint(user: dict = Depends(get_current_active_user)):
    try:
        current = await fetch_spreadsheet_meta()
    except Exception as exc:
        raise HTTPException(502, f"Nextcloud HEAD request failed: {exc}")
    cached = get_cached_xlsx_meta()
    is_fresh = bool(current["etag"] and current["etag"] == cached.get("etag"))
    return {
        "current": {**current, "checked_at": datetime.utcnow().isoformat() + "Z"},
        "cached": cached,
        "is_fresh": is_fresh,
    }


# ── 7. Preview stream (SSE) ───────────────────────────────────────────────────

@app.get("/api/preview/stream")
async def preview_stream(
    request: Request,
    token: str | None = Query(None),
    pre_search: str | None = Query(None),
    pre_cat: str | None = Query(None),
):
    ip = _client_ip(request)
    _pre_search = (pre_search or "").strip().lower()
    _pre_cat = (pre_cat or "").strip()
    logger.warning(
        "FETCH_ROUTE_ENTERED: route=/api/preview/stream mode=preview_stream ip=%s pre_search=%r pre_cat=%r",
        ip, _pre_search, _pre_cat,
    )

    async def generate():
        db = SessionLocal()
        try:
            def ev(data: dict) -> str:
                return f"data: {json.dumps(data)}\n\n"

            if not token:
                yield ev({"step": "excel", "status": "error", "msg": "Not authenticated"}); return
            try:
                user_data = decode_token(token)
            except Exception:
                yield ev({"step": "excel", "status": "error", "msg": "Invalid or expired token"}); return
            try:
                _validate_active_user_sync(user_data, db)
            except HTTPException as _exc:
                yield ev({"step": "excel", "status": "error", "msg": _exc.detail}); return

            yield ev({"step": "excel", "status": "running", "msg": "Downloading price list from Nextcloud…"})
            try:
                xlsx = await download_xlsx(force=True)
            except Exception as exc:
                yield ev({"step": "excel", "status": "error", "msg": str(exc)}); return

            _xlsx_meta = get_cached_xlsx_meta()
            logger.info(
                "preview_stream: xlsx downloaded size=%d etag=%s last_modified=%s",
                len(xlsx), _xlsx_meta.get("etag") or "", _xlsx_meta.get("last_modified") or "",
            )

            _sheet_hash = hashlib.md5(xlsx).hexdigest()
            sheet_items, dup_warnings = parse_price_list(xlsx)
            if not sheet_items:
                yield ev({"step": "excel", "status": "error", "msg": "No valid rows found (IDs in col B, prices in col C from row 3)"}); return

            # ── Pre-fetch filters ─────────────────────────────────────────────
            total_in_sheet = len(sheet_items)
            filter_mode = "full"
            _filter_skipped = 0
            _filter_no_cache = 0
            if _pre_search or _pre_cat:
                all_ids = [i["product_id"] for i in sheet_items]
                filter_meta = get_cached_by_ids(db, all_ids)
                filtered_items = []
                skipped_no_cache = []
                for item in sheet_items:
                    pid = item["product_id"]
                    cached = filter_meta.get(pid)
                    if cached is None:
                        # Not in cache: include so we don't silently drop unknown products
                        filtered_items.append(item)
                        skipped_no_cache.append(pid)
                        continue
                    if _pre_search:
                        name = (cached.get("name") or "").lower()
                        sku  = (cached.get("sku") or "").lower()
                        if _pre_search not in name and _pre_search not in sku:
                            continue
                    if _pre_cat:
                        cats = cached.get("categories") or []
                        if not any(str(c.get("id", "")) == _pre_cat for c in cats):
                            continue
                    filtered_items.append(item)
                _filter_no_cache = len(skipped_no_cache)
                _filter_skipped = total_in_sheet - len(filtered_items)
                sheet_items = filtered_items
                filter_mode = "filtered"
                logger.info(
                    "preview_stream: pre-filter applied search=%r cat=%r "
                    "total=%d matched=%d skipped=%d no_cache=%d",
                    _pre_search, _pre_cat, total_in_sheet, len(sheet_items),
                    _filter_skipped, _filter_no_cache,
                )
                if not sheet_items:
                    yield ev({"step": "excel", "status": "error",
                              "msg": "No products match the selected filters. Clear filters or run a full fetch."}); return

            yield ev({
                "step": "excel", "status": "done",
                "msg": f"Found {len(sheet_items)} products in price list"
                       + (f" (filtered from {total_in_sheet} total)" if filter_mode == "filtered" else ""),
                "filter_mode": filter_mode,
            })
            if dup_warnings:
                yield ev({
                    "step": "excel", "status": "warning",
                    "msg": f"{len(dup_warnings)} duplicate product ID(s) detected across worksheets — last sheet wins",
                    "duplicate_warnings": dup_warnings,
                })

            product_ids = [i["product_id"] for i in sheet_items]
            cached_data = get_cached_by_ids(db, product_ids)
            missing_ids = [pid for pid in product_ids if pid not in cached_data]
            freshly_fetched_ids: set[int] = set(missing_ids)

            if missing_ids:
                yield ev({"step": "wc", "status": "running", "msg": f"{len(cached_data)} products from cache, fetching {len(missing_ids)} from WooCommerce…"})
                try:
                    fetch_task = asyncio.create_task(fetch_product_prices(missing_ids, force=True))
                    while not fetch_task.done():
                        yield ": keepalive\n\n"
                        await asyncio.sleep(10)
                    fresh_data = await fetch_task
                except Exception as exc:
                    yield ev({"step": "wc", "status": "error", "msg": str(exc)}); return
                cache_rows = [wc_response_to_cache_dict(pid, d) for pid, d in fresh_data.items()]
                upsert_products(db, cache_rows)  # image_url absent in cache_rows; discard return value
                db.commit()
                # Re-read from DB so wc_data uses _to_dict format (final_price or regular_price)
                # — same derivation the NEXT preview will use, preventing false "changed" rows.
                cached_data.update(get_cached_by_ids(db, list(fresh_data.keys())))
            else:
                yield ev({"step": "wc", "status": "running", "msg": f"Loading {len(cached_data)} products from local cache…"})

            wc_data = cached_data

            # Targeted variation image refresh — only for spreadsheet IDs that are
            # variations missing image_url, capped to avoid crawling the whole catalog.
            _VAR_PARENT_CAP = 30
            _var_rows_no_img = (
                db.query(ProductCache)
                .filter(
                    ProductCache.wc_id.in_(product_ids),
                    ProductCache.product_type == "variation",
                    ProductCache.image_url.is_(None),
                    ProductCache.parent_id > 0,
                )
                .all()
            )
            if _var_rows_no_img:
                _var_parent_ids = {r.parent_id for r in _var_rows_no_img}
                if len(_var_parent_ids) <= _VAR_PARENT_CAP:
                    _parent_rows = {
                        r.wc_id: r for r in db.query(ProductCache)
                        .filter(ProductCache.wc_id.in_(_var_parent_ids)).all()
                    }
                    if _parent_rows:
                        _parent_info: dict[int, tuple] = {}
                        for _pid, _pr in _parent_rows.items():
                            try:
                                _cats = json.loads(_pr.categories) if _pr.categories else []
                            except Exception:
                                _cats = []
                            _parent_info[_pid] = (_pr.name or "", _cats, _pr.image_url)
                        yield ev({"step": "wc", "status": "running",
                                  "msg": f"Fetching variation images for {len(_var_parent_ids)} parent(s) ({len(_var_rows_no_img)} variation(s) missing images)…"})
                        try:
                            _vt = asyncio.create_task(
                                fetch_variations_for_selected_parents(_var_parent_ids, _parent_info)
                            )
                            while not _vt.done():
                                yield ": keepalive\n\n"
                                await asyncio.sleep(5)
                            _var_products, _var_warn = await _vt
                            if _var_products:
                                upsert_products(db, _var_products, image_sync_authoritative=True)
                                db.commit()
                                wc_data.update(get_cached_by_ids(db, [p["wc_id"] for p in _var_products]))
                            for _w in _var_warn:
                                logger.warning("preview targeted variation: %s", _w)
                        except Exception as _ve:
                            logger.warning("preview_stream: targeted variation fetch error: %s", _ve)
                else:
                    logger.info(
                        "preview_stream: skipping targeted variation fetch — %d parents exceeds cap %d",
                        len(_var_parent_ids), _VAR_PARENT_CAP,
                    )

            yield ev({"step": "wc", "status": "done", "msg": f"Loaded {len(wc_data)} products ({len(product_ids) - len(missing_ids)} from cache, {len(missing_ids)} from WooCommerce)"})

            # Cache-meta for debug logging
            _cmeta: dict[int, tuple] = {}
            for _cr in db.query(ProductCache).filter(ProductCache.wc_id.in_(product_ids)).all():
                _cmeta[_cr.wc_id] = (_cr.cache_version, _cr.last_synced_at)

            yield ev({"step": "calc", "status": "running", "msg": "Calculating price differences…"})

            last_synced = _get_last_synced(db, product_ids)

            db.query(SyncJob).filter(SyncJob.status == JobStatus.preview).update({"status": JobStatus.cancelled})
            job = SyncJob(status=JobStatus.preview, total_count=len(sheet_items), sheet_hash=_sheet_hash)
            db.add(job)
            db.flush()

            preview_rows = []
            for row in sheet_items:
                pid = row["product_id"]
                wc = wc_data.get(pid, {})
                old_price = wc.get("price") or None
                sname = row.get("sheet_name") or wc.get("name") or None
                _cver, _csync = _cmeta.get(pid, (None, None))
                _src = "live_wc" if pid in freshly_fetched_ids else "cache"
                logger.debug(
                    "preview pid=%d sheet=%s wc_source=%s wc_price=%s cv=%s synced=%s",
                    pid, row["new_price"], _src, old_price or "",
                    _cver, _csync.isoformat() if _csync else None,
                )
                if _price_differs(old_price, row["new_price"]):
                    logger.info(
                        "preview[changed] pid=%d sheet=%s wc=%s wc_source=%s cv=%s synced=%s",
                        pid, row["new_price"], old_price or "", _src, _cver,
                        _csync.isoformat() if _csync else None,
                    )
                db.add(SyncItem(
                    job_id=job.id, product_id=pid,
                    parent_id=wc.get("parent_id") or 0,
                    product_name=sname,
                    sku=wc.get("sku") or None,
                    old_price=old_price, new_price=row["new_price"],
                    sale_price=wc.get("sale_price") or None,
                    stock_status=wc.get("stock_status") or None,
                    stock_quantity=wc.get("stock_quantity"),
                    categories=json.dumps(wc.get("categories", [])),
                    row_color=row.get("row_color"),
                    last_price_updated=last_synced.get(pid),
                    wc_date_modified=_parse_wc_dt(wc.get("wc_date_modified")),
                ))
                preview_rows.append(_build_preview_row(
                    pid, wc, row["new_price"],
                    row_color=row.get("row_color"),
                    last_price_updated=last_synced.get(pid),
                    sheet_name=row.get("sheet_name", ""),
                ))
            db.commit()

            _audit(user_data["sub"], "fetch", ip, job.id)

            changed = sum(1 for r in preview_rows if r["changed"])
            yield ev({"step": "calc", "status": "done", "msg": f"{changed} prices will change, {len(preview_rows) - changed} unchanged"})
            _wc_lookups = len(missing_ids) if missing_ids else 0
            _cache_hits = len(product_ids) - _wc_lookups
            yield ev({
                "step": "preview", "status": "done",
                "job_id": job.id, "total": len(preview_rows),
                "changed_count": changed, "unchanged_count": len(preview_rows) - changed,
                "items": preview_rows,
                "duplicate_warnings": dup_warnings,
                "filter_stats": {
                    "filter_mode": filter_mode,
                    "sheet_rows_scanned": total_in_sheet,
                    "rows_matched": len(preview_rows),
                    "rows_skipped": _filter_skipped,
                    "rows_no_cache": _filter_no_cache,
                    "wc_lookups": _wc_lookups,
                    "cache_hits": _cache_hits,
                },
            })
        finally:
            db.close()

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── 7. Apply stream (SSE) ─────────────────────────────────────────────────────

@app.get("/api/sync/{job_id}/apply-stream")
async def apply_stream(
    job_id: int,
    request: Request,
    token: str | None = Query(None),
    sid: list[int] | None = Query(None),
):
    ip = _client_ip(request)

    async def generate():
        db = SessionLocal()
        try:
            def ev(data: dict) -> str:
                return f"data: {json.dumps(data)}\n\n"

            if not token:
                yield ev({"type": "error", "msg": "Not authenticated"}); return
            try:
                user_data = decode_token(token)
            except Exception:
                yield ev({"type": "error", "msg": "Invalid or expired token"}); return
            try:
                _validate_active_user_sync(user_data, db)
            except HTTPException as _exc:
                yield ev({"type": "error", "msg": _exc.detail}); return

            job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
            if not job:
                yield ev({"type": "error", "msg": "Job not found"}); return
            if job.status != JobStatus.preview:
                yield ev({"type": "error", "msg": f"Job is '{job.status}', expected 'preview'"}); return

            # Stale-preview check: block Apply if xlsx was edited after this preview
            if job.sheet_hash:
                try:
                    _cur_xlsx = await download_xlsx(force=False)
                    _cur_hash = hashlib.md5(_cur_xlsx).hexdigest()
                    if _cur_hash != job.sheet_hash:
                        logger.warning(
                            "apply_stream: stale preview job=%d preview_hash=%s current_hash=%s",
                            job_id, job.sheet_hash, _cur_hash,
                        )
                        yield ev({
                            "type": "stale_preview",
                            "msg": (
                                "The spreadsheet was modified after this preview was created. "
                                "Applying would use stale product IDs. "
                                "Please re-run Fetch Preview to load the current sheet."
                            ),
                        })
                        return
                except Exception as _hce:
                    logger.warning("apply_stream: hash check failed (proceeding): %s", _hce)

            job.status = JobStatus.running
            db.commit()

            items = db.query(SyncItem).filter(SyncItem.job_id == job_id).all()

            selected_set = set(sid) if sid else None
            if selected_set:
                to_update = [i for i in items if _price_differs(i.old_price, i.new_price) and i.product_id in selected_set]
                to_skip   = [i for i in items if not _price_differs(i.old_price, i.new_price) or i.product_id not in selected_set]
            else:
                to_update = [i for i in items if _price_differs(i.old_price, i.new_price)]
                to_skip   = [i for i in items if not _price_differs(i.old_price, i.new_price)]

            yield ev({"type": "start", "total": len(to_update), "skipped": len(to_skip)})

            for item in to_skip:
                item.status = ItemStatus.skipped
                item.synced_at = datetime.utcnow()

            if to_update:
                updates = [
                    {"product_id": i.product_id, "new_price": i.new_price,
                     "parent_id": i.parent_id or 0, "stock_status": _stock_from_price(i.new_price)}
                    for i in to_update
                ]
                try:
                    wc_results = await batch_update_prices(updates)
                except Exception as exc:
                    job.status = JobStatus.failed
                    db.commit()
                    yield ev({"type": "error", "msg": f"WooCommerce batch update failed: {exc}"}); return

                now = datetime.utcnow()
                result_map = {r["product_id"]: r for r in wc_results}
                for item in to_update:
                    r = result_map.get(item.product_id, {})
                    item.status = ItemStatus.updated if r.get("success") else ItemStatus.failed
                    item.error_message = r.get("error_message")
                    item.synced_at = now
                    _ep = (
                        f"/products/{item.parent_id}/variations/{item.product_id}"
                        if (item.parent_id or 0) > 0
                        else f"/products/{item.product_id}"
                    )
                    logger.info(
                        "apply item: job=%d pid=%d name=%r old=%s new=%s "
                        "parent=%d endpoint=%s status=%s err=%s",
                        job_id, item.product_id, item.product_name or "",
                        item.old_price or "", item.new_price,
                        item.parent_id or 0, _ep, item.status.value,
                        item.error_message or "",
                    )
                    if r.get("success"):
                        item.last_price_updated = now
                        item.stock_status = _stock_from_price(item.new_price)
                        if _is_zero_price(item.new_price):
                            logger.info(
                                "apply outofstock: pid=%d name=%r parent=%d "
                                "blank/zero price → stock_status=outofstock",
                                item.product_id, item.product_name or "", item.parent_id or 0,
                            )
                        _ch = patch_cached_product(db, item.product_id, {
                            "regular_price": item.new_price,
                            "final_price": item.new_price,
                            "stock_status": _stock_from_price(item.new_price),
                        })
                        logger.info(
                            "apply_stream: cache patched pid=%d price=%s hit=%s",
                            item.product_id, item.new_price, _ch,
                        )
                    yield ev({
                        "type": "item",
                        "product_id": item.product_id,
                        "product_name": item.product_name or "",
                        "sku": item.sku or "",
                        "status": item.status.value,
                        "old_price": item.old_price or "",
                        "new_price": item.new_price,
                        "error": item.error_message or "",
                    })

                await _sync_parent_stock(updates, result_map, db)

            job.updated_count = sum(1 for i in items if i.status == ItemStatus.updated)
            job.failed_count  = sum(1 for i in items if i.status == ItemStatus.failed)
            job.skipped_count = sum(1 for i in items if i.status == ItemStatus.skipped)
            job.status = JobStatus.completed
            job.completed_at = datetime.utcnow()
            db.commit()

            _audit(user_data["sub"], "apply", ip, job.id)

            yield ev({"type": "done", "job_id": job_id,
                      "updated": job.updated_count, "failed": job.failed_count, "skipped": job.skipped_count})
        finally:
            db.close()

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── 8. Write back to sheet ────────────────────────────────────────────────────

@app.post("/api/jobs/{job_id}/writeback")
async def writeback(job_id: int, user: dict = Depends(get_current_active_user), db: Session = Depends(get_db)):
    job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status != JobStatus.completed:
        raise HTTPException(400, "Job must be completed before writing back to sheet")

    items = db.query(SyncItem).filter(SyncItem.job_id == job_id).all()
    payload = [{"product_id": i.product_id, "status": i.status.value,
                "synced_at": i.synced_at.isoformat() if i.synced_at else "",
                "error_message": i.error_message or ""} for i in items]
    try:
        await write_back_to_sheet(payload)
    except Exception as exc:
        raise HTTPException(502, f"Failed to write back to Nextcloud sheet: {exc}")

    return {"message": "Results written back to spreadsheet (columns E, F, G)"}
