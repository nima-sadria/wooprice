import asyncio
import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

_SSE_HEADERS = {
    "X-Accel-Buffering": "no",   # tell nginx: do not buffer this stream
    "Cache-Control": "no-cache",
    "Content-Type": "text/event-stream",
}

from fastapi import Depends, FastAPI, HTTPException, Header, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func, inspect as sa_inspect, text
from sqlalchemy.orm import Session

from .config import get_settings
from .database import Base, SessionLocal, engine, get_db
from .models import AlarmThreshold, AuditLog, ItemStatus, JobStatus, ProductCache, SyncItem, SyncJob
from .services.auth import create_token, decode_token, is_super_admin, verify_nextcloud_credentials
from .services.nextcloud import download_xlsx, parse_price_list, write_back_to_sheet, write_price_to_sheet
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
    fetch_all_products_full,
    fetch_all_variations_stock,
    fetch_categories,
    fetch_product_prices,
    fetch_products_modified_after,
    get_cache_info,
    lookup_product_info,
    update_parent_stock_statuses,
    update_single_product,
)

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

        conn.commit()


_run_column_migrations()

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


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")
    return user


# ── Audit logging ─────────────────────────────────────────────────────────────

def _audit(
    db: Session,
    username: str,
    action: str,
    ip: str = "unknown",
    job_id: int | None = None,
    detail: dict | None = None,
):
    db.add(AuditLog(
        username=username,
        action=action,
        ip_address=ip,
        job_id=job_id,
        detail=json.dumps(detail, ensure_ascii=False) if detail else None,
    ))
    db.commit()


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


async def _sync_parent_stock(updates: list[dict], result_map: dict) -> None:
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
async def cache_status(user: dict = Depends(get_current_user)):
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
    user: dict = Depends(get_current_user),
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
async def db_cache_status(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    return cache_get_stats(db)


@app.post("/api/products/cache-clear")
async def db_cache_clear(user: dict = Depends(require_admin), db: Session = Depends(get_db)):
    count = cache_clear_all(db)
    db.commit()
    return {"message": f"Cleared {count} products from DB cache"}


@app.get("/api/fetch/full")
async def fetch_full_stream(request: Request, token: str | None = Query(None)):
    """Stream a full WooCommerce product sync into the DB cache."""
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

    async def _gen():
        def ev(d: dict) -> str:
            return f"data: {json.dumps(d, ensure_ascii=False)}\n\n"

        yield ev({"step": "start", "status": "running", "msg": "Starting full WooCommerce product sync…"})
        try:
            # Phase 1: fetch from WooCommerce — keepalive every 10 s so nginx
            # does not close the connection before the catalog is downloaded.
            yield ev({"step": "fetch", "status": "running", "msg": "Connecting to WooCommerce, fetching product catalog…"})
            fetch_task = asyncio.create_task(fetch_all_products_full())
            while not fetch_task.done():
                yield ": keepalive\n\n"
                await asyncio.sleep(10)
            products, var_warnings = await fetch_task  # re-raises if the task failed

            # Phase 2: report per-variation warnings
            for w in var_warnings:
                logger.warning("fetch/full variation warning: %s", w)
                yield ev({"step": "warning", "status": "warning", "msg": w})

            yield ev({
                "step": "fetch",
                "status": "done",
                "msg": f"Fetched {len(products)} products from WooCommerce"
                       + (f" ({len(var_warnings)} variation warning(s))" if var_warnings else ""),
                "count": len(products),
                "warnings": len(var_warnings),
            })

            # Phase 3: upsert into persistent DB cache
            yield ev({"step": "upsert", "status": "running", "msg": f"Saving {len(products)} products to local cache…"})
            _db = SessionLocal()
            try:
                inserted, updated = upsert_products(_db, products)
                _db.commit()
            finally:
                _db.close()

            yield ev({
                "step": "done",
                "status": "ok",
                "msg": f"Cache updated: {inserted} new, {updated} updated ({len(products)} total)",
                "inserted": inserted,
                "updated": updated,
                "total": len(products),
            })

        except asyncio.CancelledError:
            logger.warning("fetch/full SSE stream cancelled")
            raise
        except Exception as exc:
            logger.exception("fetch/full failed: %s", exc)
            yield ev({"step": "error", "status": "error", "msg": str(exc)})

    return StreamingResponse(_gen(), media_type="text/event-stream", headers=_SSE_HEADERS)


@app.get("/api/fetch/light")
async def fetch_light_stream(
    request: Request,
    token: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """Stream a light sync (only products modified since last sync) into the DB cache."""
    raw = token
    if not raw:
        raw = request.headers.get("authorization", "").removeprefix("Bearer ").strip() or None
    if not raw:
        return StreamingResponse(
            iter(['data: {"error":"Not authenticated"}\n\n']),
            media_type="text/event-stream",
        )
    try:
        decode_token(raw)
    except Exception:
        return StreamingResponse(
            iter(['data: {"error":"Invalid token"}\n\n']),
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
                inserted, updated = upsert_products(_db, products)
                _db.commit()
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
    token = create_token(body.username)
    role = "admin" if is_super_admin(body.username) else "user"
    _audit(db, body.username, "login", _client_ip(request))
    return {"token": token, "username": body.username, "role": role}


@app.get("/api/auth/me")
async def me(user: dict = Depends(get_current_user)):
    return {"username": user["sub"], "role": user["role"]}


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
async def get_alarm_settings(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
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
    user: dict = Depends(get_current_user),
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
async def get_categories(user: dict = Depends(get_current_user)):
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
async def get_dashboard(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
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
async def get_analytics(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
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
    user: dict = Depends(get_current_user),
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
            "last_synced_at": row.last_synced_at.isoformat() if row.last_synced_at else None,
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
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    effective_parent_id = _resolve_parent_id(db, product_id, body.parent_id or 0)

    # Read old price from cache before overwriting it
    cache_row = db.query(ProductCache).filter(ProductCache.wc_id == product_id).first()
    old_price = cache_row.final_price or cache_row.regular_price if cache_row else None

    try:
        await update_single_product(product_id, {"regular_price": body.new_price}, effective_parent_id)
    except Exception as exc:
        raise HTTPException(502, f"WooCommerce update failed: {exc}")

    try:
        await write_price_to_sheet(product_id, body.new_price)
    except Exception as exc:
        raise HTTPException(502, f"Excel writeback failed: {exc}")

    cache_hit = patch_cached_product(db, product_id, {
        "regular_price": body.new_price,
        "final_price": body.new_price,
    })

    _audit(db, user["sub"], "update_price", detail={
        "product_id": product_id,
        "parent_id": effective_parent_id,
        "old_price": old_price,
        "new_price": body.new_price,
        "cache_hit": cache_hit,
    })
    # _audit calls db.commit(), so no separate commit needed here

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
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    wc_payload: dict = {"stock_status": body.stock_status}
    if body.stock_quantity is not None:
        wc_payload["stock_quantity"] = body.stock_quantity
        wc_payload["manage_stock"] = True

    effective_parent_id = _resolve_parent_id(db, product_id, body.parent_id or 0)

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

    _audit(db, user["sub"], "update_stock", detail={
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


# ── 1. Create preview ─────────────────────────────────────────────────────────

@app.post("/api/preview")
async def create_preview(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        xlsx = await download_xlsx(force=True)
    except Exception as exc:
        raise HTTPException(502, f"Cannot download sheet from Nextcloud: {exc}")

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
        wc_data.update(fresh)

    last_synced = _get_last_synced(db, product_ids)

    job = SyncJob(status=JobStatus.preview, total_count=len(sheet_items))
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
async def confirm_sync(job_id: int, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
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

        await _sync_parent_stock(updates, result_map)

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
async def cancel_sync(job_id: int, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
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
async def list_jobs(limit: int = 30, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    jobs = db.query(SyncJob).order_by(SyncJob.created_at.desc()).limit(limit).all()
    return [_job_out(j) for j in jobs]


# ── 5. Job detail ─────────────────────────────────────────────────────────────

@app.get("/api/jobs/{job_id}")
async def get_job(job_id: int, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    items = db.query(SyncItem).filter(SyncItem.job_id == job_id).all()
    return {**_job_out(job), "items": [_item_out(i) for i in items]}


# ── 6. Preview stream (SSE) ───────────────────────────────────────────────────

@app.get("/api/preview/stream")
async def preview_stream(request: Request, token: str | None = Query(None)):
    ip = _client_ip(request)

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

            yield ev({"step": "excel", "status": "running", "msg": "Downloading price list from Nextcloud…"})
            try:
                xlsx = await download_xlsx(force=True)
            except Exception as exc:
                yield ev({"step": "excel", "status": "error", "msg": str(exc)}); return

            sheet_items, dup_warnings = parse_price_list(xlsx)
            if not sheet_items:
                yield ev({"step": "excel", "status": "error", "msg": "No valid rows found (IDs in col B, prices in col C from row 3)"}); return
            yield ev({"step": "excel", "status": "done", "msg": f"Found {len(sheet_items)} products in price list"})
            if dup_warnings:
                yield ev({
                    "step": "excel", "status": "warning",
                    "msg": f"{len(dup_warnings)} duplicate product ID(s) detected across worksheets — last sheet wins",
                    "duplicate_warnings": dup_warnings,
                })

            product_ids = [i["product_id"] for i in sheet_items]
            cached_data = get_cached_by_ids(db, product_ids)
            missing_ids = [pid for pid in product_ids if pid not in cached_data]

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
                upsert_products(db, cache_rows)
                db.commit()
                cached_data.update(fresh_data)
            else:
                yield ev({"step": "wc", "status": "running", "msg": f"Loading {len(cached_data)} products from local cache…"})

            wc_data = cached_data
            yield ev({"step": "wc", "status": "done", "msg": f"Loaded {len(wc_data)} products ({len(product_ids) - len(missing_ids)} from cache, {len(missing_ids)} from WooCommerce)"})

            yield ev({"step": "calc", "status": "running", "msg": "Calculating price differences…"})

            last_synced = _get_last_synced(db, product_ids)

            db.query(SyncJob).filter(SyncJob.status == JobStatus.preview).update({"status": JobStatus.cancelled})
            job = SyncJob(status=JobStatus.preview, total_count=len(sheet_items))
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

            _audit(db, user_data["sub"], "fetch", ip, job.id)

            changed = sum(1 for r in preview_rows if r["changed"])
            yield ev({"step": "calc", "status": "done", "msg": f"{changed} prices will change, {len(preview_rows) - changed} unchanged"})
            yield ev({
                "step": "preview", "status": "done",
                "job_id": job.id, "total": len(preview_rows),
                "changed_count": changed, "unchanged_count": len(preview_rows) - changed,
                "items": preview_rows,
                "duplicate_warnings": dup_warnings,
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

            job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
            if not job:
                yield ev({"type": "error", "msg": "Job not found"}); return
            if job.status != JobStatus.preview:
                yield ev({"type": "error", "msg": f"Job is '{job.status}', expected 'preview'"}); return

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
                    if r.get("success"):
                        item.last_price_updated = now
                        item.stock_status = _stock_from_price(item.new_price)
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

                await _sync_parent_stock(updates, result_map)

            job.updated_count = sum(1 for i in items if i.status == ItemStatus.updated)
            job.failed_count  = sum(1 for i in items if i.status == ItemStatus.failed)
            job.skipped_count = sum(1 for i in items if i.status == ItemStatus.skipped)
            job.status = JobStatus.completed
            job.completed_at = datetime.utcnow()
            db.commit()

            _audit(db, user_data["sub"], "apply", ip, job.id)

            yield ev({"type": "done", "job_id": job_id,
                      "updated": job.updated_count, "failed": job.failed_count, "skipped": job.skipped_count})
        finally:
            db.close()

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── 8. Write back to sheet ────────────────────────────────────────────────────

@app.post("/api/jobs/{job_id}/writeback")
async def writeback(job_id: int, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
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
