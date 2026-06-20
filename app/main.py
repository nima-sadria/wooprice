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
from sqlalchemy import func, inspect as sa_inspect, or_, text
from sqlalchemy.orm import Session

from .config import get_settings
from .database import Base, SessionLocal, engine, get_db
from .models import (
    AlarmThreshold, AppUser, AuditLog, ChangeHistory, ChangeTracking, DailyMetrics,
    ItemStatus, JobStatus, ProductCache, SyncItem, SyncJob,
)
from .validation import ValidationLevel, validate_items, worst_level
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
                # Phase B — granular change flags
                ("change_status",    "TEXT"),
                ("price_changed",    "INTEGER DEFAULT 0"),
                ("stock_changed",    "INTEGER DEFAULT 0"),
                ("name_changed",     "INTEGER DEFAULT 0"),
                ("category_changed", "INTEGER DEFAULT 0"),
                ("missing_cost",     "INTEGER DEFAULT 0"),
                ("missing_image",    "INTEGER DEFAULT 0"),
                # Phase C — validation + precise change detection
                ("validation_level",    "TEXT"),
                ("wc_price_at_preview", "TEXT"),
                ("wc_stock_at_preview", "TEXT"),
            ]:
                if col_name not in existing_cols:
                    conn.execute(text(f"ALTER TABLE sync_items ADD COLUMN {col_name} {col_type}"))

        if "audit_logs" in existing_tables:
            existing_cols = {c["name"] for c in inspector.get_columns("audit_logs")}
            if "detail" not in existing_cols:
                conn.execute(text("ALTER TABLE audit_logs ADD COLUMN detail TEXT"))

        if "sync_jobs" in existing_tables:
            existing_cols = {c["name"] for c in inspector.get_columns("sync_jobs")}
            for col_name, col_type in [
                ("sheet_hash",           "TEXT"),
                # Phase B — change detection summary counts
                ("changed_count",        "INTEGER DEFAULT 0"),
                ("unchanged_count",      "INTEGER DEFAULT 0"),
                ("new_count",            "INTEGER DEFAULT 0"),
                ("invalid_count",        "INTEGER DEFAULT 0"),
                ("price_changed_count",  "INTEGER DEFAULT 0"),
                ("stock_changed_count",  "INTEGER DEFAULT 0"),
                ("missing_image_count",  "INTEGER DEFAULT 0"),
                # Phase B — dry run
                ("dry_run_summary",      "TEXT"),
                ("dry_run_status",       "TEXT"),
                ("dry_run_completed_at", "TIMESTAMP"),
                ("dry_run_scope",        "TEXT"),
            ]:
                if col_name not in existing_cols:
                    conn.execute(text(f"ALTER TABLE sync_jobs ADD COLUMN {col_name} {col_type}"))

        if "alarm_thresholds" in existing_tables:
            existing_cols = {c["name"] for c in inspector.get_columns("alarm_thresholds")}
            for col_name, col_type in [
                ("critical_threshold_percent", "REAL"),
                ("block_enabled",              "INTEGER DEFAULT 0"),
            ]:
                if col_name not in existing_cols:
                    conn.execute(text(f"ALTER TABLE alarm_thresholds ADD COLUMN {col_name} {col_type}"))

        if "products_cache" in existing_tables:
            existing_cols = {c["name"] for c in inspector.get_columns("products_cache")}
            for col_name, col_type in [
                ("image_url", "TEXT"),
                ("image_source", "TEXT"),
                ("image_last_synced_at", "TIMESTAMP"),
            ]:
                if col_name not in existing_cols:
                    conn.execute(text(f"ALTER TABLE products_cache ADD COLUMN {col_name} {col_type}"))

        # ── Phase C — new tables (idempotent CREATE TABLE IF NOT EXISTS) ──────
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS change_history (
                id INTEGER PRIMARY KEY,
                product_id INTEGER NOT NULL,
                parent_id INTEGER DEFAULT 0,
                old_price TEXT,
                new_price TEXT,
                old_stock_status TEXT,
                new_stock_status TEXT,
                old_manage_stock BOOLEAN,
                new_manage_stock BOOLEAN,
                old_stock_quantity INTEGER,
                new_stock_quantity INTEGER,
                changed_at TIMESTAMP,
                username TEXT,
                job_id INTEGER,
                source TEXT,
                rollback_of_id INTEGER REFERENCES change_history(id)
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_change_history_product_id ON change_history(product_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_change_history_job_id ON change_history(job_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_change_history_changed_at ON change_history(changed_at)"))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS change_tracking (
                id INTEGER PRIMARY KEY,
                product_id INTEGER NOT NULL,
                detected_at TIMESTAMP,
                field_name TEXT,
                old_value TEXT,
                new_value TEXT,
                source TEXT,
                job_id INTEGER
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_change_tracking_product_id ON change_tracking(product_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_change_tracking_job_id ON change_tracking(job_id)"))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS daily_metrics (
                id INTEGER PRIMARY KEY,
                date TEXT NOT NULL UNIQUE,
                total_products INTEGER DEFAULT 0,
                changed_products INTEGER DEFAULT 0,
                updated_products INTEGER DEFAULT 0,
                failed_products INTEGER DEFAULT 0,
                validation_errors INTEGER DEFAULT 0,
                apply_jobs INTEGER DEFAULT 0,
                rollback_jobs INTEGER DEFAULT 0,
                created_at TIMESTAMP
            )
        """))

        conn.commit()


_run_column_migrations()


def _parse_bootstrap_entry(entry: str) -> tuple[str, str | None]:
    """Parse 'username' or 'username:email' format from bootstrap env vars."""
    entry = entry.strip()
    if ":" in entry:
        username, email = entry.split(":", 1)
        email = email.strip().lower() or None
        return username.strip(), email
    return entry, None


def _run_bootstrap_users() -> None:
    """Idempotent startup seed: creates app_users rows from BOOTSTRAP_APP_ADMINS /
    BOOTSTRAP_APP_USERS env vars. Supports 'username' or 'username:email' format.
    Never overwrites existing rows; backfills email if previously unset."""
    s = get_settings()
    admin_entries = [_parse_bootstrap_entry(e) for e in s.bootstrap_app_admins.split(",") if e.strip()]
    user_entries = [_parse_bootstrap_entry(e) for e in s.bootstrap_app_users.split(",") if e.strip()]
    if not admin_entries and not user_entries:
        return
    db = SessionLocal()
    try:
        seeded: list[str] = []
        email_filled: list[str] = []
        for username, email in admin_entries:
            existing = db.query(AppUser).filter(AppUser.username == username).first()
            if not existing:
                row = AppUser(username=username, display_name=username, is_admin=True, is_active=True, email=email)
                _apply_perm_defaults(row)
                db.add(row)
                seeded.append(f"{username}(admin)")
            elif email and not existing.email:
                existing.email = email
                existing.updated_at = datetime.utcnow()
                email_filled.append(username)
        for username, email in user_entries:
            existing = db.query(AppUser).filter(AppUser.username == username).first()
            if not existing:
                row = AppUser(username=username, display_name=username, is_admin=False, is_active=True, email=email)
                _apply_perm_defaults(row)
                db.add(row)
                seeded.append(f"{username}(user)")
            elif email and not existing.email:
                existing.email = email
                existing.updated_at = datetime.utcnow()
                email_filled.append(username)
        if seeded or email_filled:
            db.commit()
            if seeded:
                logger.warning("startup: bootstrap seeded app_users: %s", ", ".join(seeded))
            if email_filled:
                logger.info("startup: bootstrap backfilled emails for: %s", ", ".join(email_filled))
        else:
            logger.info("startup: bootstrap: all configured users already present")
    except Exception as exc:
        logger.error("startup: bootstrap seeding failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


_run_bootstrap_users()


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
_assets_dir = static_dir / "assets"
if _assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="react-assets")


# ── Pydantic models ───────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class AlarmThresholdItem(BaseModel):
    category_id: int | None = None
    threshold_percent: float
    critical_threshold_percent: float | None = None
    block_enabled: bool = False


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
    email: str | None = None
    is_admin: bool = False
    notes: str | None = None
    can_access_site: bool | None = None    # None = use smart default (admin → True, user → True)
    can_fetch: bool | None = None
    can_apply: bool | None = None
    can_edit_price: bool | None = None
    can_edit_stock: bool | None = None
    can_view_logs: bool | None = None      # None = use smart default (admin → True, user → False)
    can_view_settings: bool | None = None


class AppUserUpdate(BaseModel):
    display_name: str | None = None
    email: str | None = None
    is_active: bool | None = None
    is_admin: bool | None = None
    notes: str | None = None
    can_access_site: bool | None = None
    can_fetch: bool | None = None
    can_apply: bool | None = None
    can_edit_price: bool | None = None
    can_edit_stock: bool | None = None
    can_view_logs: bool | None = None
    can_view_settings: bool | None = None


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


def validate_sse_token(token: str | None, db: Session) -> dict:
    """Validate a query-param SSE token: decode JWT → is_active → permission_version.
    Raises HTTPException on any failure. All SSE routes must call this instead of
    decode_token() directly so revoked/inactive users are rejected consistently."""
    if not token:
        raise HTTPException(401, "Not authenticated")
    try:
        user_data = decode_token(token)
    except Exception:
        raise HTTPException(401, "Invalid or expired token")
    _validate_active_user_sync(user_data, db)
    return user_data


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


def _enforce_permission(user_data: dict, permission: str, db: Session) -> None:
    """Check a named permission for the requesting user.
    Super-admins and DB admins pass unconditionally.
    For all other users, can_access_site is enforced as a global gate before
    any specific permission is checked.
    Raises HTTP 403 and writes a permission_denied audit record on failure."""
    username = user_data.get("sub", "")
    if is_super_admin(username):
        return
    app_user = db.query(AppUser).filter(AppUser.username == username).first()
    if not app_user:
        raise HTTPException(403, "Access denied")
    if app_user.is_admin:
        return
    if not app_user.can_access_site:
        _audit(username, "permission_denied", detail={"permission": "can_access_site"})
        raise HTTPException(403, "Site access revoked")
    if not getattr(app_user, permission, False):
        _audit(username, "permission_denied", detail={"permission": permission})
        raise HTTPException(403, "Permission denied")


def _enforce_admin_sync(user_data: dict, db: Session) -> None:
    """Synchronous admin gate for SSE outer-handlers that cannot use Depends()."""
    username = user_data.get("sub", "")
    if is_super_admin(username):
        return
    app_user = db.query(AppUser).filter(AppUser.username == username).first()
    if not app_user or not app_user.is_admin:
        _audit(username, "permission_denied", detail={"reason": "not_admin"})
        raise HTTPException(403, "Admin access required")


def require_permission(permission: str):
    """Dependency that enforces a named permission.
    Super-admins and DB admins always pass. Raises HTTP 403 on failure."""
    async def _check(
        db: Session = Depends(get_db),
        user: dict = Depends(get_current_active_user),
    ) -> dict:
        _enforce_permission(user, permission, db)
        return user
    return _check


def _resolve_login_identifier(identifier: str, db: Session) -> str | None:
    """Resolve a login input to a canonical Nextcloud username.
    If identifier contains '@', treat it as an email and look it up in app_users.email
    (case-insensitive). Returns the canonical username, or None if the email is unknown.
    Non-email identifiers are returned as-is (username login)."""
    if "@" not in identifier:
        return identifier.strip()
    email_lower = identifier.strip().lower()
    app_user = db.query(AppUser).filter(
        func.lower(AppUser.email) == email_lower
    ).first()
    return app_user.username if app_user else None


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


# ── Phase C: change history + analytics helpers ───────────────────────────────

def _record_change_history(
    db: Session,
    *,
    product_id: int,
    parent_id: int = 0,
    old_price: str | None = None,
    new_price: str | None = None,
    old_stock_status: str | None = None,
    new_stock_status: str | None = None,
    old_stock_quantity: int | None = None,
    new_stock_quantity: int | None = None,
    old_manage_stock: bool | None = None,
    new_manage_stock: bool | None = None,
    username: str | None = None,
    job_id: int | None = None,
    source: str = "apply",
    rollback_of_id: int | None = None,
) -> ChangeHistory:
    """Insert a change_history row capturing prior state before a WC update.
    Caller is responsible for committing the session. Returns the (un-flushed) row."""
    # Snapshot brand from products_cache at the moment of the change
    _cache_row = db.get(ProductCache, product_id)
    _brand_id = _cache_row.brand_id if _cache_row else None

    # Pre-compute price delta percentage for future velocity analytics
    _delta_pct: float | None = None
    _old_f = _safe_price_float(old_price)
    _new_f = _safe_price_float(new_price)
    if _old_f is not None and _new_f is not None and _old_f != 0:
        _delta_pct = round((_new_f - _old_f) / _old_f * 100, 4)

    row = ChangeHistory(
        product_id=product_id,
        parent_id=parent_id or 0,
        old_price=old_price,
        new_price=new_price,
        old_stock_status=old_stock_status,
        new_stock_status=new_stock_status,
        old_manage_stock=old_manage_stock,
        new_manage_stock=new_manage_stock,
        old_stock_quantity=old_stock_quantity,
        new_stock_quantity=new_stock_quantity,
        changed_at=datetime.utcnow(),
        username=username,
        job_id=job_id,
        source=source,
        rollback_of_id=rollback_of_id,
        brand_id=_brand_id,
        price_delta_pct=_delta_pct,
    )
    db.add(row)
    return row


def _upsert_daily_metrics(db: Session, date: str, **increments: int) -> None:
    """Increment (or initialise) the daily_metrics row for `date` (YYYY-MM-DD).
    Uses its own nested logic on the caller's session; caller commits."""
    row = db.query(DailyMetrics).filter(DailyMetrics.date == date).first()
    if row is None:
        row = DailyMetrics(date=date, created_at=datetime.utcnow())
        db.add(row)
        db.flush()
    for field, delta in increments.items():
        if not hasattr(row, field):
            continue
        current = getattr(row, field, 0) or 0
        setattr(row, field, current + (delta or 0))


def _today_str() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


def _record_change_tracking(
    db: Session,
    *,
    product_id: int,
    field_name: str,
    old_value: str | None,
    new_value: str | None,
    source: str,
    job_id: int | None = None,
) -> None:
    """Insert a change_tracking row for a single detected field drift. Caller commits."""
    db.add(ChangeTracking(
        product_id=product_id,
        detected_at=datetime.utcnow(),
        field_name=field_name,
        old_value=None if old_value is None else str(old_value),
        new_value=None if new_value is None else str(new_value),
        source=source,
        job_id=job_id,
    ))


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


# ── Phase B: Change classification helpers ────────────────────────────────────

def _is_valid_price(price: str | None) -> bool:
    """True for any numeric string (including '0'). False for None/empty/non-numeric."""
    if price is None or str(price).strip() == "":
        return False
    try:
        float(price)
        return True
    except (ValueError, TypeError):
        return False


def _safe_price_float(v) -> float | None:
    """Parse a price string to float, returning None for empty/null/non-numeric values.
    Delegates to validation._to_float which normalises Persian/Arabic digits."""
    from .validation import _to_float as _vto_float
    return _vto_float(v)


def _row_has_image(cache_row, parent_cache_row=None) -> bool:
    """True if the row's own product/variation has an image, or its parent does.

    A WooCommerce variation commonly has no image of its own and visually inherits
    the parent product's gallery image — that is not a real "missing image" problem,
    so the warning must only fire when neither the row nor its parent has an image.
    """
    if cache_row and getattr(cache_row, "image_url", None):
        return True
    if parent_cache_row and getattr(parent_cache_row, "image_url", None):
        return True
    return False


def _classify_row(
    pid: int,
    new_price: str,
    wc: dict,
    last_price_updated,
    cache_row,
    price_parse_error: bool = False,
    parent_cache_row=None,
) -> dict:
    """Classify one preview row. Returns change_status + boolean flags.

    change_status values:
      'invalid'              — price failed to parse as a number, or product_id missing
      'missing_from_wc_cache'— product not found in WooCommerce
      'new'                  — found in WC, has changes, never synced by WooPrice
      'changed'              — found in WC, has changes, previously synced
      'unchanged'            — found in WC, price and stock match exactly

    Business rule: a BLANK sheet price is NOT invalid — it is an explicit signal that
    the product should be marked out of stock (see _stock_from_price/_is_zero_price).
    Only a genuine parse failure (non-numeric garbage caught by the sheet parser and
    flagged via price_parse_error) is classified as 'invalid'.

    `parent_cache_row` (optional) is the ProductCache row for cache_row.parent_id, used
    as an image fallback — see _row_has_image().
    """
    if not pid or pid <= 0 or price_parse_error:
        return {
            "change_status": "invalid",
            "price_changed": 0, "stock_changed": 0,
            "name_changed": 0, "category_changed": 0,
            "missing_cost": 0, "missing_image": 0,
        }

    if not wc:
        return {
            "change_status": "missing_from_wc_cache",
            "price_changed": 0, "stock_changed": 0,
            "name_changed": 0, "category_changed": 0,
            "missing_cost": 0,
            "missing_image": 0 if _row_has_image(cache_row, parent_cache_row) else 1,
        }

    old_price = wc.get("price") or None
    wc_stock  = wc.get("stock_status") or "instock"
    new_stock = _stock_from_price(new_price)

    price_chg     = 1 if _price_differs(old_price, new_price) else 0
    stock_chg     = 1 if new_stock != wc_stock else 0
    missing_cost  = 1 if (not old_price or str(old_price).strip() == "") else 0
    missing_image = 0 if _row_has_image(cache_row, parent_cache_row) else 1

    if price_chg or stock_chg:
        cs = "new" if last_price_updated is None else "changed"
    else:
        cs = "unchanged"

    return {
        "change_status": cs,
        "price_changed": price_chg,
        "stock_changed": stock_chg,
        "name_changed": 0,
        "category_changed": 0,
        "missing_cost": missing_cost,
        "missing_image": missing_image,
    }


def _row_validation_level(pid: int, new_price: str, old_price: str | None, cache_row) -> str | None:
    """Phase C: compute the worst validation level for a single preview row.
    Returns 'info'|'warning'|'error'|'critical' or None when there are no findings."""
    from .validation import validate_price, validate_product
    try:
        results = validate_product(pid, cache_row) + validate_price(pid, new_price, old_price)
        lvl = worst_level(results)
        return lvl.value if lvl is not None else None
    except Exception:
        return None


def _should_apply(item: "SyncItem") -> bool:  # type: ignore[name-defined]
    """True if item should be sent to WooCommerce. Uses stored change_status when available."""
    cs = getattr(item, "change_status", None)
    if cs:
        return cs in ("changed", "new")
    return _price_differs(item.old_price, item.new_price)


APPLYABLE_DRY_RUN_STATES: frozenset[str] = frozenset({"passed", "warnings"})


def _normalize_scope(
    selected_ids: "set[int] | None",
    *,
    items: "list | None" = None,
    job: "SyncJob | None" = None,  # type: ignore[name-defined]
) -> "set[int]":
    """Return an explicit product-id set for the apply/dry-run scope.

    Priority:
    1. selected_ids if not None — caller supplied an explicit selection.
    2. items if provided — dry_run_sync path; all item product_ids.
    3. job.dry_run_scope if stored — apply path; reuse scope that was analysed.
    4. empty set — fallback (should not happen in normal flow).
    """
    if selected_ids is not None:
        return set(selected_ids)
    if items is not None:
        return {i.product_id for i in items}
    if job is not None:
        scope_raw = getattr(job, "dry_run_scope", None)
        if scope_raw:
            return set(json.loads(scope_raw))
    return set()


def _check_dry_run_guards(
    job: "SyncJob",  # type: ignore[name-defined]
    selected_ids: "set[int] | None",
) -> "tuple[bool, str, str, int]":
    """Validate all dry-run gates synchronously.

    selected_ids MUST already be normalised via _normalize_scope before calling.
    Returns (ok, event_type, message, http_status). http_status is 0 when ok=True.
    """
    dr_status = getattr(job, "dry_run_status", None)
    # Allow-list: only passed/warnings are applyable; everything else is rejected.
    if dr_status not in APPLYABLE_DRY_RUN_STATES:
        if dr_status is None:
            return False, "error", "dry_run_required: Run a dry run before applying.", 400
        if dr_status == "blocked":
            return False, "error", "apply_blocked_by_dry_run: Dry run found critical errors. Fix them and re-run.", 409
        if dr_status == "invalidated":
            return False, "error", "dry_run_invalidated: Items were edited after the last dry run. Re-run dry run.", 409
        return False, "error", (
            f"dry_run_required: Dry run status '{dr_status}' is not applyable. Re-run dry run."
        ), 409
    # Scope check (selected_ids is already normalised — compares set vs set).
    scope_raw = getattr(job, "dry_run_scope", None)
    if scope_raw is not None:
        dr_scope = set(json.loads(scope_raw))
        cur_scope = selected_ids if selected_ids is not None else set()
        if cur_scope != dr_scope:
            return False, "error", (
                "dry_run_scope_mismatch: Selection changed since dry run was run. "
                "Re-run dry run with the current selection."
            ), 409
    return True, "", "", 0


async def _check_sheet_hash(job: "SyncJob") -> tuple[bool, str, str]:  # type: ignore[name-defined]
    """Compare current xlsx hash to the hash stored when the preview was created.

    Returns (ok, event_type, message). event_type is 'stale_preview' when not ok.

    Fails closed: if the sheet cannot be downloaded or hashed, freshness cannot be
    verified, so the apply is blocked rather than allowed to proceed unverified.
    """
    if not getattr(job, "sheet_hash", None):
        return True, "", ""
    try:
        _cur_xlsx = await download_xlsx(force=False)
        _cur_hash = hashlib.md5(_cur_xlsx).hexdigest()
    except Exception as _hce:
        logger.warning("_check_sheet_hash: verification failed, blocking apply: %s", _hce)
        return False, "freshness_unverifiable", (
            "Could not verify the spreadsheet is still current "
            "(download or hash check failed). Applying is blocked until freshness "
            "can be confirmed. Please retry or re-run Fetch Preview."
        )
    if _cur_hash != job.sheet_hash:
        return False, "stale_preview", (
            "The spreadsheet was modified after this preview was created. "
            "Applying would use stale product IDs. "
            "Please re-run Fetch Preview to load the current sheet."
        )
    return True, "", ""


def _invalidate_dry_run(job: "SyncJob") -> None:  # type: ignore[name-defined]
    """Mark the job's dry run as invalidated due to item edits. Caller must commit."""
    job.dry_run_status = "invalidated"
    job.dry_run_scope = None
    job.dry_run_summary = None


def _invalidate_dry_runs_for_product(db: "Session", product_id: int) -> int:  # type: ignore[name-defined]
    """Invalidate every active dry run (in preview jobs) that contains product_id.

    'Active' means dry_run_status IS set and is not already 'invalidated'.
    This is called unconditionally after any successful WooCommerce update so that
    no dry run can remain valid after WC state has changed, regardless of job_id.
    Caller must commit after this returns.
    """
    from sqlalchemy import and_

    affected_jobs = (
        db.query(SyncJob)  # type: ignore[name-defined]
        .join(SyncItem, SyncItem.job_id == SyncJob.id)  # type: ignore[name-defined]
        .filter(
            SyncItem.product_id == product_id,
            SyncJob.status == JobStatus.preview,  # type: ignore[name-defined]
            SyncJob.dry_run_status.isnot(None),
            SyncJob.dry_run_status != "invalidated",
        )
        .distinct()
        .all()
    )
    for job in affected_jobs:
        _invalidate_dry_run(job)
    if affected_jobs:
        logger.info(
            "_invalidate_dry_runs_for_product: invalidated %d job(s) for product_id=%d",
            len(affected_jobs), product_id,
        )
    return len(affected_jobs)


def _split_items_for_apply(
    items: list, selected_ids: "set[int] | None"
) -> "tuple[list, list]":
    """Return (to_update, to_skip) filtered by _should_apply and optional selection scope."""
    if selected_ids:
        to_update = [i for i in items if _should_apply(i) and i.product_id in selected_ids]
        to_skip   = [i for i in items if not _should_apply(i) or i.product_id not in selected_ids]
    else:
        to_update = [i for i in items if _should_apply(i)]
        to_skip   = [i for i in items if not _should_apply(i)]
    return to_update, to_skip


def _resolve_alarm_threshold(
    item: "SyncItem",  # type: ignore[name-defined]
    alarm_threshold: float,
    category_thresholds: dict | None,
) -> dict:
    """Resolve the effective {warning, critical, block_enabled} threshold for one item.

    category_thresholds maps category_id (None = global) -> {warning, critical, block_enabled}.
    When the item belongs to a category with its own row, that row wins; otherwise the
    global row (or the bare `alarm_threshold` float, for backward-compatible callers
    that don't pass category_thresholds at all) applies.
    """
    default = {"warning": alarm_threshold, "critical": None, "block_enabled": False}
    if not category_thresholds:
        return default
    try:
        cats = json.loads(item.categories) if getattr(item, "categories", None) else []
    except (ValueError, TypeError):
        cats = []
    for c in cats:
        cid = c.get("id") if isinstance(c, dict) else None
        if cid is not None and cid in category_thresholds:
            return category_thresholds[cid]
    return category_thresholds.get(None, default)


def _compute_dry_run_summary(
    items: list,
    alarm_threshold: float,
    selected_ids: set | None = None,
    cache_map: dict | None = None,
    category_thresholds: dict | None = None,
) -> dict:
    """Pure computation — no WooCommerce calls. Returns dry-run summary dict.

    Critical errors are detected across ALL items (invalid + missing_from_wc_cache rows
    are blockers regardless of selection). products_to_update is scoped to selected_ids.

    `category_thresholds` (optional) maps category_id (None = global) -> a dict of
    {warning, critical, block_enabled} — see _resolve_alarm_threshold. When omitted,
    every item just uses the flat `alarm_threshold` as its warning threshold with no
    critical/blocking behavior (legacy callers keep working unchanged).

    Phase C: the reusable validation engine (app/validation.py) is also run across the
    items that would actually be applied. Any `critical` validation finding is promoted
    into critical_errors (and therefore blocks the apply); error/warning findings are
    surfaced as warnings. The raw findings are returned under `validation` for the UI.
    """
    critical_errors: list[dict] = []

    # Step 1: scan every item for blockers — selection does not exempt invalid/missing rows
    for item in items:
        cs = getattr(item, "change_status", None)
        pid = item.product_id
        name = item.product_name or ""
        if cs == "invalid":
            if not pid or pid <= 0:
                critical_errors.append({"type": "invalid_product_id", "product_id": pid, "name": name})
            elif not _is_valid_price(item.new_price):
                critical_errors.append({"type": "invalid_price", "product_id": pid, "name": name, "value": item.new_price})
        elif cs == "missing_from_wc_cache":
            critical_errors.append({"type": "missing_woocommerce_product", "product_id": pid, "name": name})

    # Step 2: products_to_update = changed/new rows, scoped to selection when provided
    to_apply = [
        i for i in items
        if getattr(i, "change_status", None) in ("changed", "new")
        and (selected_ids is None or i.product_id in selected_ids)
    ]

    warnings_list: list[dict] = []
    price_increases = price_decreases = 0
    stock_to_instock = stock_to_outofstock = 0
    price_chg_count = stock_chg_count = 0

    for item in to_apply:
        pid = item.product_id
        name = item.product_name or ""

        # Pricing direction
        try:
            new_f = float(item.new_price)
            old_f = float(item.old_price or 0)
            if new_f > old_f:
                price_increases += 1
            elif new_f < old_f:
                price_decreases += 1
        except (ValueError, TypeError):
            pass

        # Stock transitions
        new_stock = _stock_from_price(item.new_price)
        old_stock = item.stock_status or "instock"
        if new_stock == "instock" and old_stock == "outofstock":
            stock_to_instock += 1
        elif new_stock == "outofstock" and old_stock == "instock":
            stock_to_outofstock += 1

        if getattr(item, "price_changed", 0):
            price_chg_count += 1
        if getattr(item, "stock_changed", 0):
            stock_chg_count += 1

        # Warnings
        if getattr(item, "missing_image", 0):
            warnings_list.append({"type": "missing_image", "product_id": pid, "name": name})
        if getattr(item, "missing_cost", 0):
            warnings_list.append({"type": "missing_cost", "product_id": pid, "name": name})
        if _is_zero_price(item.new_price):
            warnings_list.append({"type": "out_of_stock_marker", "product_id": pid, "name": name})
        thr = _resolve_alarm_threshold(item, alarm_threshold, category_thresholds)
        if item.old_price and item.new_price:
            try:
                old_f2 = float(item.old_price)
                if old_f2 > 0:
                    pct = abs(float(item.new_price) - old_f2) / old_f2 * 100
                    if thr["block_enabled"] and thr["critical"] is not None and pct > thr["critical"]:
                        critical_errors.append({
                            "type": "extreme_price_change",
                            "product_id": pid, "name": name,
                            "change_pct": round(pct, 1), "threshold": thr["critical"],
                        })
                    elif thr["warning"] < float("inf") and pct > thr["warning"]:
                        warnings_list.append({
                            "type": "large_price_change",
                            "product_id": pid, "name": name,
                            "change_pct": round(pct, 1), "threshold": thr["warning"],
                        })
            except (ValueError, TypeError, ZeroDivisionError):
                pass

    # Phase C: run the reusable validation engine over the apply set.
    validation_findings: list[dict] = []
    try:
        v_results = validate_items(to_apply, cache_map or {})
        for vr in v_results:
            vd = vr.to_dict()
            validation_findings.append(vd)
            if vr.level == ValidationLevel.critical:
                critical_errors.append({
                    "type": f"validation_{vr.rule}",
                    "product_id": vr.product_id,
                    "name": "",
                    "value": vr.value,
                    "message": vr.message,
                })
            elif vr.level in (ValidationLevel.error, ValidationLevel.warning):
                warnings_list.append({
                    "type": f"validation_{vr.rule}",
                    "product_id": vr.product_id,
                    "name": "",
                    "value": vr.value,
                    "message": vr.message,
                })
    except Exception as _ve:  # validation must never crash the dry run
        logger.warning("_compute_dry_run_summary: validation engine error: %s", _ve)

    dr_status = "blocked" if critical_errors else ("warnings" if warnings_list else "passed")

    return {
        "products_to_update":   len(to_apply),
        "price_increases":      price_increases,
        "price_decreases":      price_decreases,
        "stock_to_instock":     stock_to_instock,
        "stock_to_outofstock":  stock_to_outofstock,
        "price_changed_count":  price_chg_count,
        "stock_changed_count":  stock_chg_count,
        "critical_errors":      critical_errors,
        "warnings":             warnings_list,
        "validation":           validation_findings,
        "dry_run_status":       dr_status,
    }


# ── Serialisers ───────────────────────────────────────────────────────────────

def _job_out(job: SyncJob) -> dict:
    dr_raw = getattr(job, "dry_run_summary", None)
    return {
        "id": job.id,
        "created_at": job.created_at,
        "completed_at": job.completed_at,
        "status": job.status,
        "total_count": job.total_count,
        "updated_count": job.updated_count,
        "failed_count": job.failed_count,
        "skipped_count": job.skipped_count,
        # Phase B — change detection counts
        "changed_count":       getattr(job, "changed_count", 0) or 0,
        "unchanged_count":     getattr(job, "unchanged_count", 0) or 0,
        "new_count":           getattr(job, "new_count", 0) or 0,
        "invalid_count":       getattr(job, "invalid_count", 0) or 0,
        "price_changed_count": getattr(job, "price_changed_count", 0) or 0,
        "stock_changed_count": getattr(job, "stock_changed_count", 0) or 0,
        "missing_image_count": getattr(job, "missing_image_count", 0) or 0,
        # Phase B — dry run
        "dry_run_status":       getattr(job, "dry_run_status", None),
        "dry_run_completed_at": getattr(job, "dry_run_completed_at", None),
        "dry_run_summary":      json.loads(dr_raw) if dr_raw else None,
        "dry_run_scope":        json.loads(getattr(job, "dry_run_scope", None) or "null"),
    }


def _item_out(item: SyncItem) -> dict:
    try:
        cats = json.loads(item.categories) if item.categories else []
    except Exception:
        cats = []
    cs = getattr(item, "change_status", None)
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
        # Phase B — granular change fields
        "change_status":    cs,
        "price_changed":    bool(getattr(item, "price_changed", 0)),
        "stock_changed":    bool(getattr(item, "stock_changed", 0)),
        "missing_cost":     bool(getattr(item, "missing_cost", 0)),
        "missing_image":    bool(getattr(item, "missing_image", 0)),
        # backward compat: "changed" is True for anything that will be applied
        "changed": (cs in ("changed", "new")) if cs else _price_differs(item.old_price, item.new_price),
    }


def _build_preview_row(
    pid: int,
    wc: dict,
    new_price: str,
    row_color: str | None = None,
    last_price_updated=None,
    sheet_name: str = "",
    classification: dict | None = None,
) -> dict:
    old_price = wc.get("price") or None
    lpu = last_price_updated
    if isinstance(lpu, datetime):
        lpu = lpu.isoformat()
    result = {
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
    if classification:
        result.update(classification)
        cs = classification.get("change_status")
        result["changed"] = cs in ("changed", "new")
        result["found_in_wc"] = cs not in ("missing_from_wc_cache", "invalid")
    return result


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
async def cache_status(user: dict = Depends(require_permission("can_fetch"))):
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
    user: dict = Depends(require_permission("can_fetch")),
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
async def db_cache_status(user: dict = Depends(require_permission("can_fetch")), db: Session = Depends(get_db)):
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
    Served from disk cache; generated lazily on first request using Pillow.

    PUBLIC BY DESIGN — no authentication required. Exposes only image data;
    no price, stock, or catalogue information is returned. The browser workspace
    table loads thumbnails without token forwarding. Consider rate limiting if
    abuse is detected in production.
    """
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
    raw = token or request.headers.get("authorization", "").removeprefix("Bearer ").strip() or None
    _auth_db = SessionLocal()
    try:
        creds = validate_sse_token(raw, _auth_db)
        _enforce_permission(creds, "can_fetch", _auth_db)
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
    raw = token or request.headers.get("authorization", "").removeprefix("Bearer ").strip() or None
    _auth_db = SessionLocal()
    try:
        creds = validate_sse_token(raw, _auth_db)
        _enforce_admin_sync(creds, _auth_db)
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
    raw = token or request.headers.get("authorization", "").removeprefix("Bearer ").strip() or None
    try:
        creds = validate_sse_token(raw, db)
        _enforce_permission(creds, "can_fetch", db)
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
    login_identifier = body.username.strip()
    ip = _client_ip(request)

    # Resolve email → canonical username (non-email identifiers pass through unchanged)
    canonical_username = _resolve_login_identifier(login_identifier, db)
    if canonical_username is None:
        _audit("unknown", "login_denied_unknown_email", ip, detail={"login_identifier": login_identifier})
        raise HTTPException(403, "Access not granted — contact your administrator")

    id_detail = {"login_identifier": login_identifier} if login_identifier != canonical_username else None

    try:
        valid = await verify_nextcloud_credentials(canonical_username, body.password)
    except Exception as exc:
        raise HTTPException(503, f"Nextcloud unreachable: {exc}")
    if not valid:
        _audit(canonical_username, "login_failed", ip, detail=id_detail)
        raise HTTPException(401, "Invalid Nextcloud credentials")

    # Super admins bypass the app_users table entirely
    if is_super_admin(canonical_username):
        token = create_token(canonical_username, permission_version=0, role="admin")
        _audit(canonical_username, "login", ip, detail=id_detail)
        return {"token": token, "username": canonical_username, "role": "admin"}

    # Regular users: must exist in app_users and be active
    app_user = db.query(AppUser).filter(AppUser.username == canonical_username).first()
    if app_user is None or not app_user.is_active:
        _audit(canonical_username, "login_denied_not_in_access_list", ip, detail=id_detail)
        raise HTTPException(403, "Access not granted — contact your administrator")

    role = "admin" if app_user.is_admin else "user"
    token = create_token(canonical_username, permission_version=app_user.permission_version, role=role)
    _audit(canonical_username, "login_allowed_user_access", ip, detail=id_detail)
    return {"token": token, "username": canonical_username, "role": role}


@app.get("/api/auth/me")
async def me(
    user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    username = user["sub"]
    if is_super_admin(username):
        return {
            "username": username,
            "role": user["role"],
            "is_admin": True,
            "permissions": {p: True for p in _ALL_PERM_FIELDS},
        }
    app_user = db.query(AppUser).filter(AppUser.username == username).first()
    if app_user is None:
        raise HTTPException(403, "User not found in access list — contact your administrator")
    perms = {p: bool(getattr(app_user, p, False)) for p in _ALL_PERM_FIELDS}
    if app_user.is_admin:
        perms = {p: True for p in _ALL_PERM_FIELDS}
    return {
        "username": username,
        "role": user["role"],
        "is_admin": app_user.is_admin,
        "permissions": perms,
    }


# ── App Users (admin) ─────────────────────────────────────────────────────────

def _app_user_dict(row: AppUser) -> dict:
    return {
        "id": row.id,
        "username": row.username,
        "display_name": row.display_name,
        "email": row.email,
        "is_active": row.is_active,
        "is_admin": row.is_admin,
        "permission_version": row.permission_version,
        "notes": row.notes,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "permissions": {
            "can_access_site":   row.can_access_site,
            "can_fetch":         row.can_fetch,
            "can_apply":         row.can_apply,
            "can_edit_price":    row.can_edit_price,
            "can_edit_stock":    row.can_edit_stock,
            "can_view_logs":     row.can_view_logs,
            "can_view_settings": row.can_view_settings,
        },
    }


_ALL_PERM_FIELDS = (
    "can_access_site", "can_fetch", "can_apply",
    "can_edit_price", "can_edit_stock", "can_view_logs", "can_view_settings",
)


def _apply_perm_defaults(row: AppUser) -> None:
    """Set all permission columns on a newly created AppUser based on is_admin."""
    all_true = row.is_admin
    row.can_access_site   = True
    row.can_fetch         = True
    row.can_apply         = True
    row.can_edit_price    = True
    row.can_edit_stock    = True
    row.can_view_logs     = all_true
    row.can_view_settings = all_true


@app.get("/api/admin/app-users")
async def list_app_users(
    user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows = db.query(AppUser).order_by(AppUser.username).all()
    return [_app_user_dict(r) for r in rows]


@app.post("/api/admin/app-users", status_code=201)
async def create_app_user(
    request: Request,
    body: AppUserCreate,
    user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if db.query(AppUser).filter(AppUser.username == body.username).first():
        raise HTTPException(409, "User already exists")
    email_val: str | None = body.email.strip().lower() if body.email and body.email.strip() else None
    if email_val:
        if db.query(AppUser).filter(func.lower(AppUser.email) == email_val).first():
            raise HTTPException(409, "Email already assigned to another user")
    row = AppUser(
        username=body.username,
        display_name=body.display_name,
        email=email_val,
        is_admin=body.is_admin,
        notes=body.notes,
    )
    _apply_perm_defaults(row)
    for field in _ALL_PERM_FIELDS:
        override = getattr(body, field, None)
        if override is not None:
            setattr(row, field, override)
    db.add(row)
    db.commit()
    db.refresh(row)
    caller = user.get("sub", "")
    _audit(caller, "user_access_create", ip=_client_ip(request),
           detail={"target": body.username, "is_admin": body.is_admin})
    return _app_user_dict(row)


@app.patch("/api/admin/app-users/{username}")
async def update_app_user(
    request: Request,
    username: str,
    body: AppUserUpdate,
    user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    row = db.query(AppUser).filter(AppUser.username == username).first()
    if row is None:
        raise HTTPException(404, "User not found")
    caller = user.get("sub", "")
    # Lockout guards: prevent accidental self-lockout
    if username == caller:
        if body.is_active is False:
            raise HTTPException(400, "Cannot deactivate your own account — ask another admin")
        if body.is_admin is False:
            active_admin_count = (
                db.query(AppUser)
                .filter(AppUser.is_admin == True, AppUser.is_active == True)
                .count()
            )
            if active_admin_count <= 1:
                raise HTTPException(
                    400, "Cannot remove admin from the last active DB admin — add another admin first"
                )
    if body.display_name is not None:
        row.display_name = body.display_name
    if body.email is not None:
        email_val = body.email.strip().lower() if body.email.strip() else None
        if email_val:
            conflict = db.query(AppUser).filter(
                func.lower(AppUser.email) == email_val,
                AppUser.username != username,
            ).first()
            if conflict:
                raise HTTPException(409, "Email already assigned to another user")
        row.email = email_val
    perm_changed = False
    if body.is_active is not None and body.is_active != row.is_active:
        row.is_active = body.is_active
        perm_changed = True
        _audit(caller, "user_access_disable" if not body.is_active else "user_access_enable",
               ip=_client_ip(request), detail={"target": username})
    admin_changed = body.is_admin is not None and body.is_admin != row.is_admin
    if admin_changed:
        row.is_admin = body.is_admin
        perm_changed = True
        _audit(caller, "user_access_admin_grant" if body.is_admin else "user_access_admin_revoke",
               ip=_client_ip(request), detail={"target": username})
    if body.notes is not None:
        row.notes = body.notes
    for field in _ALL_PERM_FIELDS:
        override = getattr(body, field, None)
        if override is not None and override != getattr(row, field, None):
            setattr(row, field, override)
            perm_changed = True
    if perm_changed:
        row.permission_version = (row.permission_version or 1) + 1
    row.updated_at = datetime.utcnow()
    db.commit()
    _audit(caller, "user_access_update", ip=_client_ip(request),
           detail={"target": username, "perm_bumped": perm_changed})
    return _app_user_dict(row)


@app.delete("/api/admin/app-users/{username}", status_code=204)
async def delete_app_user(
    request: Request,
    username: str,
    user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    caller = user.get("sub", "")
    if username == caller:
        raise HTTPException(400, "Cannot delete your own account")
    row = db.query(AppUser).filter(AppUser.username == username).first()
    if row is None:
        raise HTTPException(404, "User not found")
    if row.is_admin:
        active_admin_count = (
            db.query(AppUser)
            .filter(AppUser.is_admin == True, AppUser.is_active == True)
            .count()
        )
        if active_admin_count <= 1:
            raise HTTPException(
                400, "Cannot delete the last active DB admin — add another admin first"
            )
    db.delete(row)
    db.commit()
    _audit(caller, "user_access_delete", ip=_client_ip(request), detail={"target": username})
    return Response(status_code=204)


@app.post("/api/admin/app-users/{username}/revoke-tokens")
async def revoke_user_tokens(
    request: Request,
    username: str,
    user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    caller = user.get("sub", "")
    if username == caller:
        raise HTTPException(400, "Cannot revoke your own tokens — log out instead")
    row = db.query(AppUser).filter(AppUser.username == username).first()
    if row is None:
        raise HTTPException(404, "User not found")
    row.permission_version = (row.permission_version or 1) + 1
    row.updated_at = datetime.utcnow()
    db.commit()
    _audit(caller, "token_revoke", ip=_client_ip(request),
           detail={"target": username, "new_pv": row.permission_version})
    return {"username": username, "permission_version": row.permission_version}


# ── Settings (admin) ──────────────────────────────────────────────────────────

@app.get("/api/settings")
async def get_app_settings(user: dict = Depends(require_permission("can_view_settings"))):
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
async def get_alarm_settings(user: dict = Depends(require_permission("can_view_settings")), db: Session = Depends(get_db)):
    rows = db.query(AlarmThreshold).all()
    return [{
        "category_id": r.category_id,
        "threshold_percent": r.threshold_percent,
        "critical_threshold_percent": r.critical_threshold_percent,
        "block_enabled": bool(r.block_enabled),
    } for r in rows]


@app.put("/api/alarm-settings")
async def set_alarm_settings(
    thresholds: list[AlarmThresholdItem],
    user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    db.query(AlarmThreshold).delete()
    for t in thresholds:
        if t.threshold_percent > 0:
            db.add(AlarmThreshold(
                category_id=t.category_id,
                threshold_percent=t.threshold_percent,
                critical_threshold_percent=t.critical_threshold_percent,
                block_enabled=t.block_enabled,
            ))
    db.commit()
    return {"message": "Alarm thresholds saved"}


# ── Audit logs ────────────────────────────────────────────────────────────────

@app.get("/api/audit-logs")
async def get_audit_logs(
    limit: int = 200,
    user: dict = Depends(require_permission("can_view_logs")),
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
async def get_categories(user: dict = Depends(require_permission("can_access_site"))):
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
async def get_dashboard(user: dict = Depends(require_permission("can_access_site")), db: Session = Depends(get_db)):
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
async def get_analytics(user: dict = Depends(require_permission("can_access_site")), db: Session = Depends(get_db)):
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


def _compute_brand_coverage(rows: list[tuple]) -> dict:
    """Pure aggregation step for brand coverage — kept separate from the route
    so it's directly testable without a DB.

    rows: [(brand_id, brand_name, product_count), ...] already grouped by brand.
    brand_id is None means WooCommerce has no brand assigned for those
    products — surfaced explicitly as 'unknown_brand', never guessed.
    """
    total = sum(count for _, _, count in rows)
    brands = []
    unknown_count = 0
    for brand_id, brand_name, count in rows:
        if brand_id is None:
            unknown_count += count
            continue
        brands.append({"brand_id": brand_id, "brand_name": brand_name, "product_count": count})
    brands.sort(key=lambda b: b["product_count"], reverse=True)
    return {
        "total_products": total,
        "brand_count": len(brands),
        "brands": brands,
        "unknown_brand": {"brand_id": None, "brand_name": "Unknown brand", "product_count": unknown_count},
        "coverage_percent": round((total - unknown_count) / total * 100, 1) if total else 0.0,
    }


@app.get("/api/analytics/brands")
async def get_brand_coverage(user: dict = Depends(require_permission("can_access_site")), db: Session = Depends(get_db)):
    """Read-only brand coverage report computed from the local products_cache.

    Counts top-level products only (parent_id == 0) — variations always
    inherit their parent's brand (see services/woocommerce.py), so including
    them too would double-count the same brand assignment.
    """
    rows = (
        db.query(ProductCache.brand_id, ProductCache.brand_name, func.count(ProductCache.wc_id))
        .filter(ProductCache.parent_id == 0)
        .group_by(ProductCache.brand_id, ProductCache.brand_name)
        .all()
    )
    return _compute_brand_coverage(rows)


# ── Analytics Dashboard v1 ────────────────────────────────────────────────────

def _today_utc_start() -> datetime:
    n = datetime.utcnow()
    return n.replace(hour=0, minute=0, second=0, microsecond=0)


def _updated_today_product_ids(db: Session) -> set[int]:
    """Return product_ids that had at least one completed Apply today (UTC)."""
    rows = (
        db.query(ChangeHistory.product_id)
        .filter(ChangeHistory.source == "apply", ChangeHistory.changed_at >= _today_utc_start())
        .distinct()
        .all()
    )
    return {r.product_id for r in rows}


def _pc_summary(p: ProductCache) -> dict:
    return {
        "wc_id": p.wc_id,
        "name": p.name or "",
        "sku": p.sku or "",
        "stock_status": p.stock_status or "",
        "final_price": p.final_price or "",
    }


@app.get("/api/analytics/admin/overview")
async def analytics_admin_overview(
    user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Admin overview cards: today's activity + live product-health counts."""
    today = _today_str()
    dm = db.query(DailyMetrics).filter(DailyMetrics.date == today).first()
    today_start = _today_utc_start()

    # HIGH 1: updated_today from change_history (source=apply), distinct products
    updated_today = (
        db.query(func.count(func.distinct(ChangeHistory.product_id)))
        .filter(ChangeHistory.source == "apply", ChangeHistory.changed_at >= today_start)
        .scalar() or 0
    )

    total = db.query(func.count()).select_from(ProductCache).scalar() or 0
    out_of_stock = (
        db.query(func.count()).select_from(ProductCache)
        .filter(ProductCache.stock_status == "outofstock").scalar() or 0
    )
    # HIGH 2: missing image — top-level products only (parent_id=0); variations inherit from parent
    missing_image = (
        db.query(func.count()).select_from(ProductCache)
        .filter(ProductCache.parent_id == 0, ProductCache.image_url.is_(None)).scalar() or 0
    )
    missing_price = (
        db.query(func.count()).select_from(ProductCache)
        .filter(or_(ProductCache.final_price.is_(None), ProductCache.final_price == "")).scalar() or 0
    )
    price_changes_today = (
        db.query(func.count()).select_from(ChangeHistory)
        .filter(ChangeHistory.source == "apply", ChangeHistory.changed_at >= today_start)
        .scalar() or 0
    )

    return {
        "total_products": total,
        "updated_products_today": updated_today,
        "apply_count_today": dm.apply_jobs if dm else 0,
        "rollback_count_today": dm.rollback_jobs if dm else 0,
        "price_changes_today": price_changes_today,
        "out_of_stock": out_of_stock,
        "missing_image": missing_image,
        "missing_price": missing_price,
    }


@app.get("/api/analytics/admin/top-movements")
async def analytics_admin_top_movements(
    user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Biggest price increases and decreases today (by percentage).

    MEDIUM 4: Use pre-computed price_delta_pct for SQL ordering/limiting.
    Falls back to Python-side computation only for legacy rows where the column is NULL.
    """
    today_start = _today_utc_start()
    base_filter = [
        ChangeHistory.source == "apply",
        ChangeHistory.changed_at >= today_start,
        ChangeHistory.old_price.isnot(None),
        ChangeHistory.new_price.isnot(None),
    ]

    # SQL path: rows with price_delta_pct already computed — bounded by LIMIT
    sql_rows = (
        db.query(ChangeHistory)
        .filter(*base_filter, ChangeHistory.price_delta_pct.isnot(None))
        .order_by(func.abs(ChangeHistory.price_delta_pct).desc())
        .limit(40)
        .all()
    )
    # Python fallback: pre-migration rows without price_delta_pct (should be empty after rollout)
    legacy_rows = (
        db.query(ChangeHistory)
        .filter(*base_filter, ChangeHistory.price_delta_pct.is_(None))
        .all()
    )

    seen: dict[int, dict] = {}  # product_id → best movement (largest abs delta)

    def _add(row: ChangeHistory, delta_pct: float) -> None:
        if abs(delta_pct) < 0.01:
            return
        pid = row.product_id
        if pid not in seen or abs(delta_pct) > abs(seen[pid]["delta_pct"]):
            seen[pid] = {
                "product_id": pid,
                "old_price": row.old_price,
                "new_price": row.new_price,
                "delta_pct": round(delta_pct, 1),
                "name": "",
                "sku": "",
            }

    for row in sql_rows:
        _add(row, row.price_delta_pct)

    for row in legacy_rows:
        old_f = _safe_price_float(row.old_price)
        new_f = _safe_price_float(row.new_price)
        if old_f is None or new_f is None or old_f == 0:
            continue
        _add(row, (new_f - old_f) / old_f * 100)

    movements = list(seen.values())
    if movements:
        pids = list(seen)
        cache_map = {
            r.wc_id: r
            for r in db.query(ProductCache).filter(ProductCache.wc_id.in_(pids)).all()
        }
        for m in movements:
            cr = cache_map.get(m["product_id"])
            if cr:
                m["name"] = cr.name or ""
                m["sku"] = cr.sku or ""

    increases = sorted([m for m in movements if m["delta_pct"] > 0], key=lambda x: x["delta_pct"], reverse=True)[:10]
    decreases = sorted([m for m in movements if m["delta_pct"] < 0], key=lambda x: x["delta_pct"])[:10]
    return {"increases": increases, "decreases": decreases}


@app.get("/api/analytics/admin/trend")
async def analytics_admin_trend(
    days: int = Query(default=7, ge=1, le=30),
    user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Daily metrics for the last N days (1–30), with zero-fill for missing days."""
    end = datetime.utcnow().date()
    start_str = str(end - timedelta(days=days - 1))
    rows = (
        db.query(DailyMetrics)
        .filter(DailyMetrics.date >= start_str)
        .order_by(DailyMetrics.date)
        .all()
    )
    date_map = {r.date: r for r in rows}
    data = []
    for i in range(days):
        d = str(end - timedelta(days=days - 1 - i))
        dm = date_map.get(d)
        data.append({
            "date": d,
            "updated_products": dm.updated_products if dm else 0,
            "apply_jobs": dm.apply_jobs if dm else 0,
            "rollback_jobs": dm.rollback_jobs if dm else 0,
            "changed_products": dm.changed_products if dm else 0,
        })
    return {"days": days, "data": data}


@app.get("/api/analytics/seller/categories")
async def analytics_seller_categories(
    user: dict = Depends(require_permission("can_access_site")),
    db: Session = Depends(get_db),
):
    """Per-category coverage: total products, updated today, drill-down lists."""
    updated_ids = _updated_today_product_ids(db)
    products = (
        db.query(ProductCache)
        .filter(ProductCache.parent_id == 0)
        .all()
    )

    cat_map: dict[int, dict] = {}
    for p in products:
        try:
            cats = json.loads(p.categories) if p.categories else []
        except Exception:
            cats = []
        updated = p.wc_id in updated_ids
        entry = _pc_summary(p)
        entry["updated_today"] = updated
        for c in cats:
            cid = c.get("id")
            if cid is None:
                continue
            if cid not in cat_map:
                cat_map[cid] = {
                    "category_id": cid,
                    "category_name": c.get("name", ""),
                    "total": 0,
                    "updated_today": 0,
                    "products_updated": [],
                    "products_not_updated": [],
                }
            cat_map[cid]["total"] += 1
            if updated:
                cat_map[cid]["updated_today"] += 1
                cat_map[cid]["products_updated"].append(entry)
            else:
                cat_map[cid]["products_not_updated"].append(entry)

    result = sorted(cat_map.values(), key=lambda x: x["total"], reverse=True)
    for r in result:
        r["update_pct"] = round(r["updated_today"] / r["total"] * 100, 1) if r["total"] else 0.0

    return {"categories": result, "scale_note": "Python JSON parsing — refactor to junction table if catalog exceeds 10k products"}


@app.get("/api/analytics/seller/brands")
async def analytics_seller_brands(
    user: dict = Depends(require_permission("can_access_site")),
    db: Session = Depends(get_db),
):
    """Per-brand coverage: total products, updated today via Apply, drill-down lists."""
    updated_ids = _updated_today_product_ids(db)
    products = (
        db.query(ProductCache)
        .filter(ProductCache.parent_id == 0)
        .all()
    )

    brand_map: dict = {}
    for p in products:
        bid = p.brand_id
        updated = p.wc_id in updated_ids
        entry = _pc_summary(p)
        entry["updated_today"] = updated
        if bid not in brand_map:
            brand_map[bid] = {
                "brand_id": bid,
                "brand_name": p.brand_name if bid is not None else "Unknown Brand",
                "total": 0,
                "updated_today": 0,
                "products_updated": [],
                "products_not_updated": [],
            }
        brand_map[bid]["total"] += 1
        if updated:
            brand_map[bid]["updated_today"] += 1
            brand_map[bid]["products_updated"].append(entry)
        else:
            brand_map[bid]["products_not_updated"].append(entry)

    known = sorted(
        [v for v in brand_map.values() if v["brand_id"] is not None],
        key=lambda x: x["total"], reverse=True,
    )
    unknown = brand_map.get(None, {
        "brand_id": None, "brand_name": "Unknown Brand",
        "total": 0, "updated_today": 0,
        "products_updated": [], "products_not_updated": [],
    })
    total = sum(v["total"] for v in brand_map.values())
    total_known = sum(v["total"] for v in known)
    for v in list(known) + [unknown]:
        v["update_pct"] = round(v["updated_today"] / v["total"] * 100, 1) if v["total"] else 0.0

    return {
        "total_products": total,
        "brand_count": len(known),
        "coverage_percent": round(total_known / total * 100, 1) if total else 0.0,
        "brands": known,
        "unknown_brand": unknown,
    }


@app.get("/api/analytics/seller/staleness")
async def analytics_seller_staleness(
    user: dict = Depends(require_permission("can_access_site")),
    db: Session = Depends(get_db),
):
    """Products by staleness bucket based on last Apply date.
    Stale = never applied, or last apply > 3 days ago."""
    now = datetime.utcnow()
    cutoff_3 = now - timedelta(days=3)
    cutoff_5 = now - timedelta(days=5)

    last_apply_sq = (
        db.query(
            ChangeHistory.product_id,
            func.max(ChangeHistory.changed_at).label("last_applied"),
        )
        .filter(ChangeHistory.source == "apply")
        .group_by(ChangeHistory.product_id)
        .subquery()
    )

    rows = (
        db.query(ProductCache, last_apply_sq.c.last_applied)
        .outerjoin(last_apply_sq, ProductCache.wc_id == last_apply_sq.c.product_id)
        .all()
    )

    stale_3_5: list[dict] = []
    stale_5_plus: list[dict] = []
    never_updated: list[dict] = []

    for p, last_applied in rows:
        entry = _pc_summary(p)
        entry["last_applied"] = last_applied.isoformat() if last_applied else None
        if last_applied is None:
            never_updated.append(entry)
        elif last_applied < cutoff_5:
            stale_5_plus.append(entry)
        elif last_applied < cutoff_3:
            stale_3_5.append(entry)

    return {
        "stale_3_5": stale_3_5,
        "stale_5_plus": stale_5_plus,
        "never_updated": never_updated,
        "counts": {
            "stale_3_5": len(stale_3_5),
            "stale_5_plus": len(stale_5_plus),
            "never_updated": len(never_updated),
        },
    }


# ── Live price/stock update ───────────────────────────────────────────────────

@app.get("/api/products/{product_id}/lookup")
async def lookup_product(
    product_id: int,
    user: dict = Depends(require_permission("can_fetch")),
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
    user: dict = Depends(require_permission("can_edit_price")),
    db: Session = Depends(get_db),
):
    logger.info("update_price: product_id=%s user=%s", product_id, user.get("sub"))
    effective_parent_id = _resolve_parent_id(db, product_id, body.parent_id or 0)
    ip = _client_ip(request)

    # Read old price from cache before overwriting it
    cache_row = db.query(ProductCache).filter(ProductCache.wc_id == product_id).first()
    old_price = (cache_row.final_price or cache_row.regular_price) if cache_row else None
    old_stock_status = cache_row.stock_status if cache_row else None
    old_stock_quantity = cache_row.stock_quantity if cache_row else None

    # Phase C: record change_history (prior state) BEFORE the WC update, in its own
    # session so the record survives even if the WC call below raises afterwards.
    _ch_db = SessionLocal()
    try:
        _record_change_history(
            _ch_db,
            product_id=product_id,
            parent_id=effective_parent_id,
            old_price=old_price,
            new_price=body.new_price,
            old_stock_status=old_stock_status,
            new_stock_status=_stock_from_price(body.new_price),
            old_stock_quantity=old_stock_quantity,
            username=user["sub"],
            job_id=body.job_id,
            source="direct_edit",
        )
        _ch_db.commit()
    except Exception as _che:
        logger.warning("update_price: change_history write failed pid=%s: %s", product_id, _che)
        _ch_db.rollback()
    finally:
        _ch_db.close()

    try:
        await update_single_product(product_id, {"regular_price": body.new_price}, effective_parent_id)
    except Exception as exc:
        raise HTTPException(502, f"WooCommerce update failed: {exc}")

    # WooCommerce state has changed. Commit cache patch + dry-run invalidation atomically
    # BEFORE the Excel writeback so that even if writeback raises, the dry run is already
    # invalidated and apply cannot proceed on stale analysis.
    # Invalidation is unconditional — does not require job_id from the caller.
    cache_hit = patch_cached_product(db, product_id, {
        "regular_price": body.new_price,
        "final_price": body.new_price,
    })
    _invalidate_dry_runs_for_product(db, product_id)
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
    user: dict = Depends(require_permission("can_edit_stock")),
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
    old_price = (cache_row.final_price or cache_row.regular_price) if cache_row else None

    # Phase C: record change_history (prior state) BEFORE the WC update.
    _ch_db = SessionLocal()
    try:
        _record_change_history(
            _ch_db,
            product_id=product_id,
            parent_id=effective_parent_id,
            old_price=old_price,
            new_price=old_price,  # stock-only edit does not change price
            old_stock_status=old_stock_status,
            new_stock_status=body.stock_status,
            old_stock_quantity=old_stock_quantity,
            new_stock_quantity=body.stock_quantity,
            new_manage_stock=True if body.stock_quantity is not None else None,
            username=user["sub"],
            job_id=body.job_id,
            source="direct_edit",
        )
        _ch_db.commit()
    except Exception as _che:
        logger.warning("update_stock: change_history write failed pid=%s: %s", product_id, _che)
        _ch_db.rollback()
    finally:
        _ch_db.close()

    try:
        await update_single_product(product_id, wc_payload, effective_parent_id)
    except Exception as exc:
        raise HTTPException(502, f"WooCommerce update failed: {exc}")

    # Commit cache patch + dry-run invalidation atomically before Excel writeback
    # (same fail-safe pattern as update_price; unconditional — no job_id needed).
    cache_fields: dict = {"stock_status": body.stock_status}
    if body.stock_quantity is not None:
        cache_fields["stock_quantity"] = body.stock_quantity
    cache_hit = patch_cached_product(db, product_id, cache_fields)
    _invalidate_dry_runs_for_product(db, product_id)
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
        raise HTTPException(403, "Super-admin only")
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
async def create_preview(user: dict = Depends(require_permission("can_fetch")), db: Session = Depends(get_db)):
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
    cache_by_id = {r.wc_id: r for r in db.query(ProductCache).filter(ProductCache.wc_id.in_(product_ids)).all()}

    # Parent rows for image fallback — a variation missing its own image_url should
    # not warn missing_image if its parent has one (see _row_has_image).
    _parent_ids_for_image = {
        r.parent_id for r in cache_by_id.values()
        if getattr(r, "parent_id", 0) and not getattr(r, "image_url", None)
    }
    parent_cache_by_id: dict = {}
    if _parent_ids_for_image:
        parent_cache_by_id = {
            r.wc_id: r for r in db.query(ProductCache).filter(ProductCache.wc_id.in_(_parent_ids_for_image)).all()
        }

    job = SyncJob(status=JobStatus.preview, total_count=len(sheet_items), sheet_hash=_sheet_hash)
    db.add(job)
    db.flush()

    preview_rows = []
    clfs = []
    for row in sheet_items:
        pid = row["product_id"]
        wc = wc_data.get(pid) or {}
        old_price = wc.get("price") or None
        sname = row.get("sheet_name") or wc.get("name") or None
        _row_cache = cache_by_id.get(pid)
        _row_parent_cache = parent_cache_by_id.get(getattr(_row_cache, "parent_id", 0))
        clf = _classify_row(
            pid, row["new_price"], wc, last_synced.get(pid), _row_cache,
            price_parse_error=row.get("price_parse_error", False),
            parent_cache_row=_row_parent_cache,
        )
        clfs.append(clf)
        _cr = cache_by_id.get(pid)
        _vlevel = _row_validation_level(pid, row["new_price"], old_price, _cr)
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
            change_status=clf["change_status"],
            price_changed=clf["price_changed"],
            stock_changed=clf["stock_changed"],
            name_changed=clf["name_changed"],
            category_changed=clf["category_changed"],
            missing_cost=clf["missing_cost"],
            missing_image=clf["missing_image"],
            validation_level=_vlevel,
            wc_price_at_preview=old_price,
            wc_stock_at_preview=wc.get("stock_status") or None,
        ))
        # Phase C: change_tracking for sheet-vs-cache price drift
        if clf["price_changed"]:
            _record_change_tracking(
                db, product_id=pid, field_name="price",
                old_value=old_price, new_value=row["new_price"],
                source="sheet", job_id=job.id,
            )
        preview_rows.append(_build_preview_row(
            pid, wc, row["new_price"],
            row_color=row.get("row_color"),
            last_price_updated=last_synced.get(pid),
            sheet_name=row.get("sheet_name", ""),
            classification=clf,
        ))

    # Accumulate summary counts on job
    job.changed_count       = sum(1 for c in clfs if c["change_status"] == "changed")
    job.new_count           = sum(1 for c in clfs if c["change_status"] == "new")
    job.unchanged_count     = sum(1 for c in clfs if c["change_status"] == "unchanged")
    job.invalid_count       = sum(1 for c in clfs if c["change_status"] == "invalid")
    job.price_changed_count = sum(1 for c in clfs if c["price_changed"])
    job.stock_changed_count = sum(1 for c in clfs if c["stock_changed"])
    job.missing_image_count = sum(1 for c in clfs if c["missing_image"])

    # Phase C: daily analytics
    _validation_errs = sum(
        1 for c in clfs if c["change_status"] in ("invalid", "missing_from_wc_cache")
    )
    _upsert_daily_metrics(
        db, _today_str(),
        changed_products=(job.changed_count + job.new_count),
        validation_errors=_validation_errs,
    )

    db.commit()
    _changed = job.changed_count + job.new_count
    return {
        "job_id": job.id, "total": len(preview_rows),
        "changed_count":   _changed,
        "unchanged_count": job.unchanged_count,
        "new_count":       job.new_count,
        "invalid_count":   job.invalid_count,
        "price_changed_count": job.price_changed_count,
        "stock_changed_count": job.stock_changed_count,
        "missing_image_count": job.missing_image_count,
        "items": preview_rows,
        "duplicate_warnings": dup_warnings,
    }


# ── 2. Confirm sync ───────────────────────────────────────────────────────────

@app.post("/api/sync/{job_id}/confirm")
async def confirm_sync(
    job_id: int,
    request: Request,
    sid: list[int] | None = Query(None),
    user: dict = Depends(require_permission("can_apply")),
    db: Session = Depends(get_db),
):
    ip = _client_ip(request)
    username = user["sub"]
    job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status != JobStatus.preview:
        raise HTTPException(400, f"Job is '{job.status}', expected 'preview'")

    # Normalise scope: if caller sent no sid, fall back to the stored dry_run_scope
    # so that job-wide apply matches a job-wide dry run without a scope mismatch.
    selected_ids = _normalize_scope(set(sid) if sid else None, job=job)

    # Spreadsheet freshness check
    sheet_ok, _, sheet_msg = await _check_sheet_hash(job)
    if not sheet_ok:
        raise HTTPException(409, sheet_msg)

    # All dry-run guards (allow-list status check + normalised scope check)
    dr_ok, _, dr_msg, dr_status_code = _check_dry_run_guards(job, selected_ids)
    if not dr_ok:
        if "blocked" in dr_msg or "invalidated" in dr_msg:
            _audit(username, "apply_blocked_by_dry_run", ip, job_id,
                   {"dry_run_status": getattr(job, "dry_run_status", None), "reason": dr_msg})
        raise HTTPException(dr_status_code, dr_msg)
    _audit(username, "apply_confirmed_after_dry_run", ip, job_id,
           {"dry_run_status": getattr(job, "dry_run_status", None)})

    job.status = JobStatus.running
    db.commit()

    items = db.query(SyncItem).filter(SyncItem.job_id == job_id).all()
    to_update, to_skip = _split_items_for_apply(items, selected_ids or None)

    _audit(username, "apply_started", ip, job_id,
           {"to_update": len(to_update), "to_skip": len(to_skip)})

    for item in to_skip:
        item.status = ItemStatus.skipped
        item.synced_at = datetime.utcnow()

    if to_update:
        updates = [
            {"product_id": i.product_id, "new_price": i.new_price,
             "parent_id": i.parent_id or 0, "stock_status": _stock_from_price(i.new_price)}
            for i in to_update
        ]
        # Phase C: record change_history (prior state) BEFORE the WC update.
        _ch_cache = {
            r.wc_id: r for r in db.query(ProductCache).filter(
                ProductCache.wc_id.in_([i.product_id for i in to_update])
            ).all()
        }
        for _it in to_update:
            _cr = _ch_cache.get(_it.product_id)
            _record_change_history(
                db,
                product_id=_it.product_id,
                parent_id=_it.parent_id or 0,
                old_price=(_cr.final_price or _cr.regular_price) if _cr else _it.old_price,
                new_price=_it.new_price,
                old_stock_status=_cr.stock_status if _cr else _it.stock_status,
                new_stock_status=_stock_from_price(_it.new_price),
                old_stock_quantity=_cr.stock_quantity if _cr else _it.stock_quantity,
                username=username,
                job_id=job_id,
                source="apply",
            )
        db.commit()
        try:
            wc_results = await batch_update_prices(updates)
        except Exception as exc:
            job.status = JobStatus.failed
            db.commit()
            _audit(username, "apply_failed", ip, job_id, {"error": str(exc)})
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
                _audit(username, "product_price_changed", ip, job_id, {
                    "product_id": item.product_id,
                    "old_value": item.old_price,
                    "new_value": item.new_price,
                    "source": "apply",
                })
                if getattr(item, "stock_changed", 0):
                    _audit(username, "product_stock_changed", ip, job_id, {
                        "product_id": item.product_id,
                        "new_value": _stock_from_price(item.new_price),
                        "source": "apply",
                    })

        await _sync_parent_stock(updates, result_map, db)

    job.updated_count = sum(1 for i in items if i.status == ItemStatus.updated)
    job.failed_count  = sum(1 for i in items if i.status == ItemStatus.failed)
    job.skipped_count = sum(1 for i in items if i.status == ItemStatus.skipped)
    job.status = JobStatus.completed
    job.completed_at = datetime.utcnow()
    _upsert_daily_metrics(
        db, _today_str(),
        apply_jobs=1,
        updated_products=job.updated_count,
        failed_products=job.failed_count,
    )
    db.commit()
    _audit(username, "apply_completed", ip, job_id, {
        "updated": job.updated_count,
        "failed": job.failed_count,
        "skipped": job.skipped_count,
    })
    return {"job_id": job_id, "status": "completed",
            "updated": job.updated_count, "failed": job.failed_count, "skipped": job.skipped_count}


# ── 3. Cancel preview ─────────────────────────────────────────────────────────

@app.delete("/api/sync/{job_id}")
async def cancel_sync(job_id: int, user: dict = Depends(require_permission("can_apply")), db: Session = Depends(get_db)):
    job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status != JobStatus.preview:
        raise HTTPException(400, "Only preview jobs can be cancelled")
    job.status = JobStatus.cancelled
    db.commit()
    return {"job_id": job_id, "status": "cancelled"}


# ── 3b. Dry run ───────────────────────────────────────────────────────────────

@app.post("/api/sync/{job_id}/dry-run")
async def dry_run_sync(
    job_id: int,
    request: Request,
    sid: list[int] | None = Query(None),
    user: dict = Depends(require_permission("can_apply")),
    db: Session = Depends(get_db),
):
    ip = _client_ip(request)
    username = user["sub"]

    job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status != JobStatus.preview:
        raise HTTPException(400, f"Job is '{job.status}', expected 'preview'")

    selected_ids = set(sid) if sid else None
    _audit(username, "dry_run_started", ip, job_id, {"scope": sorted(selected_ids) if selected_ids else None})

    try:
        items = db.query(SyncItem).filter(SyncItem.job_id == job_id).all()

        all_thr = db.query(AlarmThreshold).all()
        global_row = next((t for t in all_thr if t.category_id is None), None)
        alarm_threshold = global_row.threshold_percent if global_row else float("inf")
        category_thresholds = {
            t.category_id: {
                "warning": t.threshold_percent,
                "critical": t.critical_threshold_percent,
                "block_enabled": bool(t.block_enabled),
            }
            for t in all_thr
        } if all_thr else None

        _pids = [i.product_id for i in items]
        cache_map = {
            r.wc_id: r for r in db.query(ProductCache).filter(ProductCache.wc_id.in_(_pids)).all()
        } if _pids else {}
        summary = _compute_dry_run_summary(items, alarm_threshold, selected_ids, cache_map, category_thresholds)
        # Phase C: emit a validation_failed audit when the engine flags blockers.
        _v_critical = [v for v in summary.get("validation", []) if v.get("level") == "critical"]
        if _v_critical:
            _audit(username, "validation_failed", ip, job_id, {
                "critical_count": len(_v_critical),
                "rules": sorted({v.get("rule") for v in _v_critical}),
            })
        dr_status = summary["dry_run_status"]

        # Always store an explicit scope (never null) via _normalize_scope.
        effective_scope = sorted(_normalize_scope(selected_ids, items=items))
        scope_json = json.dumps(effective_scope, ensure_ascii=False)
        job.dry_run_summary      = json.dumps(summary, ensure_ascii=False)
        job.dry_run_status       = dr_status
        job.dry_run_completed_at = datetime.utcnow()
        job.dry_run_scope        = scope_json
        db.commit()

        _audit(username, "dry_run_completed", ip, job_id, {
            "status": dr_status,
            "products_to_update": summary["products_to_update"],
            "critical_errors": len(summary["critical_errors"]),
            "warnings": len(summary["warnings"]),
            "scope_size": len(effective_scope),
        })

        return {"job_id": job_id, "dry_run_scope": effective_scope, **summary}

    except Exception as exc:
        logger.error("dry_run_sync: job=%d error=%s", job_id, exc)
        _audit(username, "dry_run_failed", ip, job_id, {"error": str(exc)})
        raise HTTPException(500, f"Dry run computation failed: {exc}")


# ── 4. List jobs ──────────────────────────────────────────────────────────────

@app.get("/api/jobs")
async def list_jobs(limit: int = 30, user: dict = Depends(require_permission("can_view_logs")), db: Session = Depends(get_db)):
    jobs = db.query(SyncJob).order_by(SyncJob.created_at.desc()).limit(limit).all()
    return [_job_out(j) for j in jobs]


# ── 5. Job detail ─────────────────────────────────────────────────────────────

@app.get("/api/jobs/{job_id}")
async def get_job(job_id: int, user: dict = Depends(require_permission("can_view_logs")), db: Session = Depends(get_db)):
    job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    items = db.query(SyncItem).filter(SyncItem.job_id == job_id).all()
    return {**_job_out(job), "items": [_item_out(i) for i in items]}


# ── 6. Spreadsheet metadata (HEAD only — no download) ────────────────────────

@app.get("/api/spreadsheet/meta")
async def spreadsheet_meta_endpoint(user: dict = Depends(require_permission("can_fetch"))):
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
    pre_cat: list[int] | None = Query(None),
):
    ip = _client_ip(request)
    _pre_search = (pre_search or "").strip().lower()
    _pre_cat_ids: set[int] = set(pre_cat) if pre_cat else set()
    logger.warning(
        "FETCH_ROUTE_ENTERED: route=/api/preview/stream mode=preview_stream ip=%s pre_search=%r pre_cat=%r",
        ip, _pre_search, sorted(_pre_cat_ids),
    )

    async def generate():
        db = SessionLocal()
        try:
            def ev(data: dict) -> str:
                return f"data: {json.dumps(data)}\n\n"

            try:
                user_data = validate_sse_token(token, db)
                _enforce_permission(user_data, "can_fetch", db)
            except HTTPException as _exc:
                yield ev({"step": "excel", "status": "error", "msg": _exc.detail}); return

            _audit(user_data["sub"], "fetch_started", ip, None,
                   {"pre_search": _pre_search or None, "pre_cat": sorted(_pre_cat_ids) or None})

            yield ev({"step": "excel", "status": "running", "msg": "Downloading price list from Nextcloud…"})
            try:
                xlsx = await download_xlsx(force=True)
            except Exception as exc:
                _audit(user_data["sub"], "fetch_failed", ip, None, {"stage": "download", "error": str(exc)})
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
            if _pre_search or _pre_cat_ids:
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
                    if _pre_cat_ids:
                        cats = cached.get("categories") or []
                        if not any(c.get("id") in _pre_cat_ids for c in cats):
                            continue
                    filtered_items.append(item)
                _filter_no_cache = len(skipped_no_cache)
                _filter_skipped = total_in_sheet - len(filtered_items)
                sheet_items = filtered_items
                filter_mode = "filtered"
                logger.info(
                    "preview_stream: pre-filter applied search=%r cat=%r "
                    "total=%d matched=%d skipped=%d no_cache=%d",
                    _pre_search, sorted(_pre_cat_ids), total_in_sheet, len(sheet_items),
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
                    _audit(user_data["sub"], "fetch_failed", ip, None, {"stage": "woocommerce", "error": str(exc)})
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
                            _parent_info[_pid] = (_pr.name or "", _cats, _pr.image_url, (_pr.brand_id, _pr.brand_name))
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

            # Cache-meta for debug logging + image check
            _cmeta: dict[int, tuple] = {}
            cache_by_id: dict[int, "ProductCache"] = {}  # type: ignore[name-defined]
            for _cr in db.query(ProductCache).filter(ProductCache.wc_id.in_(product_ids)).all():
                _cmeta[_cr.wc_id] = (_cr.cache_version, _cr.last_synced_at)
                cache_by_id[_cr.wc_id] = _cr

            # Parent rows for image fallback — a variation missing its own image_url
            # should not warn missing_image if its parent has one (see _row_has_image).
            _parent_ids_for_image = {
                _cr.parent_id for _cr in cache_by_id.values()
                if getattr(_cr, "parent_id", 0) and not getattr(_cr, "image_url", None)
            }
            parent_cache_by_id: dict[int, "ProductCache"] = {}  # type: ignore[name-defined]
            if _parent_ids_for_image:
                for _pr in db.query(ProductCache).filter(ProductCache.wc_id.in_(_parent_ids_for_image)).all():
                    parent_cache_by_id[_pr.wc_id] = _pr

            yield ev({"step": "calc", "status": "running", "msg": "Calculating price differences…"})

            last_synced = _get_last_synced(db, product_ids)

            db.query(SyncJob).filter(SyncJob.status == JobStatus.preview).update({"status": JobStatus.cancelled})
            job = SyncJob(status=JobStatus.preview, total_count=len(sheet_items), sheet_hash=_sheet_hash)
            db.add(job)
            db.flush()

            preview_rows = []
            clfs = []
            for row in sheet_items:
                pid = row["product_id"]
                wc = wc_data.get(pid) or {}
                old_price = wc.get("price") or None
                sname = row.get("sheet_name") or wc.get("name") or None
                _cver, _csync = _cmeta.get(pid, (None, None))
                _src = "live_wc" if pid in freshly_fetched_ids else "cache"
                _row_cache = cache_by_id.get(pid)
                _row_parent_cache = parent_cache_by_id.get(getattr(_row_cache, "parent_id", 0))
                clf = _classify_row(
                    pid, row["new_price"], wc, last_synced.get(pid), _row_cache,
                    price_parse_error=row.get("price_parse_error", False),
                    parent_cache_row=_row_parent_cache,
                )
                clfs.append(clf)
                logger.debug(
                    "preview pid=%d sheet=%s wc_source=%s wc_price=%s cv=%s synced=%s change_status=%s",
                    pid, row["new_price"], _src, old_price or "",
                    _cver, _csync.isoformat() if _csync else None, clf["change_status"],
                )
                if clf["change_status"] in ("changed", "new"):
                    logger.info(
                        "preview[%s] pid=%d sheet=%s wc=%s wc_source=%s cv=%s synced=%s",
                        clf["change_status"], pid, row["new_price"], old_price or "", _src, _cver,
                        _csync.isoformat() if _csync else None,
                    )
                _cr_pre = cache_by_id.get(pid)
                _vlevel = _row_validation_level(pid, row["new_price"], old_price, _cr_pre)
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
                    change_status=clf["change_status"],
                    price_changed=clf["price_changed"],
                    stock_changed=clf["stock_changed"],
                    name_changed=clf["name_changed"],
                    category_changed=clf["category_changed"],
                    missing_cost=clf["missing_cost"],
                    missing_image=clf["missing_image"],
                    validation_level=_vlevel,
                    wc_price_at_preview=old_price,
                    wc_stock_at_preview=wc.get("stock_status") or None,
                ))
                # Phase C: change_tracking for sheet-vs-cache price drift
                if clf["price_changed"]:
                    _record_change_tracking(
                        db, product_id=pid, field_name="price",
                        old_value=old_price, new_value=row["new_price"],
                        source="sheet", job_id=job.id,
                    )
                preview_rows.append(_build_preview_row(
                    pid, wc, row["new_price"],
                    row_color=row.get("row_color"),
                    last_price_updated=last_synced.get(pid),
                    sheet_name=row.get("sheet_name", ""),
                    classification=clf,
                ))

            # Accumulate summary counts on job
            job.changed_count       = sum(1 for c in clfs if c["change_status"] == "changed")
            job.new_count           = sum(1 for c in clfs if c["change_status"] == "new")
            job.unchanged_count     = sum(1 for c in clfs if c["change_status"] == "unchanged")
            job.invalid_count       = sum(1 for c in clfs if c["change_status"] == "invalid")
            job.price_changed_count = sum(1 for c in clfs if c["price_changed"])
            job.stock_changed_count = sum(1 for c in clfs if c["stock_changed"])
            job.missing_image_count = sum(1 for c in clfs if c["missing_image"])

            # Phase C: daily analytics
            _validation_errs = sum(
                1 for c in clfs if c["change_status"] in ("invalid", "missing_from_wc_cache")
            )
            _upsert_daily_metrics(
                db, _today_str(),
                changed_products=(job.changed_count + job.new_count),
                validation_errors=_validation_errs,
            )
            db.commit()

            _audit(user_data["sub"], "fetch", ip, job.id)
            _audit(user_data["sub"], "fetch_completed", ip, job.id, {
                "total": len(preview_rows),
                "changed": job.changed_count + job.new_count,
                "invalid": _validation_errs,
            })

            _changed = job.changed_count + job.new_count
            yield ev({"step": "calc", "status": "done",
                      "msg": f"{_changed} will change ({job.changed_count} changed, {job.new_count} new), {job.unchanged_count} unchanged"})
            _wc_lookups = len(missing_ids) if missing_ids else 0
            _cache_hits = len(product_ids) - _wc_lookups
            yield ev({
                "step": "preview", "status": "done",
                "job_id": job.id, "total": len(preview_rows),
                "changed_count":       _changed,
                "unchanged_count":     job.unchanged_count,
                "new_count":           job.new_count,
                "invalid_count":       job.invalid_count,
                "price_changed_count": job.price_changed_count,
                "stock_changed_count": job.stock_changed_count,
                "missing_image_count": job.missing_image_count,
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

            try:
                user_data = validate_sse_token(token, db)
                _enforce_permission(user_data, "can_apply", db)
            except HTTPException as _exc:
                yield ev({"type": "error", "msg": _exc.detail}); return

            job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
            if not job:
                yield ev({"type": "error", "msg": "Job not found"}); return
            if job.status != JobStatus.preview:
                yield ev({"type": "error", "msg": f"Job is '{job.status}', expected 'preview'"}); return

            # Spreadsheet freshness check
            sheet_ok, sheet_etype, sheet_msg = await _check_sheet_hash(job)
            if not sheet_ok:
                logger.warning("apply_stream: stale preview job=%d", job_id)
                yield ev({"type": sheet_etype, "msg": sheet_msg}); return

            # Normalise scope then run all dry-run guards (allow-list + scope check)
            selected_ids = _normalize_scope(set(sid) if sid else None, job=job)
            dr_ok, dr_etype, dr_msg, _ = _check_dry_run_guards(job, selected_ids)
            if not dr_ok:
                if "blocked" in dr_msg or "invalidated" in dr_msg:
                    _audit(user_data["sub"], "apply_blocked_by_dry_run", ip, job_id,
                           {"dry_run_status": getattr(job, "dry_run_status", None), "reason": dr_msg})
                yield ev({"type": dr_etype, "msg": dr_msg}); return

            _audit(user_data["sub"], "apply_confirmed_after_dry_run", ip, job_id,
                   {"dry_run_status": getattr(job, "dry_run_status", None)})

            job.status = JobStatus.running
            db.commit()

            items = db.query(SyncItem).filter(SyncItem.job_id == job_id).all()

            # selected_ids is already normalised; pass None when empty (→ apply-all)
            to_update, to_skip = _split_items_for_apply(items, selected_ids or None)

            _audit(user_data["sub"], "apply_started", ip, job_id,
                   {"to_update": len(to_update), "to_skip": len(to_skip)})

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
                # Phase C: record change_history (prior state) BEFORE the WC update.
                _ch_cache = {
                    r.wc_id: r for r in db.query(ProductCache).filter(
                        ProductCache.wc_id.in_([i.product_id for i in to_update])
                    ).all()
                }
                for _it in to_update:
                    _cr = _ch_cache.get(_it.product_id)
                    _new_stock = _stock_from_price(_it.new_price)
                    _record_change_history(
                        db,
                        product_id=_it.product_id,
                        parent_id=_it.parent_id or 0,
                        old_price=(_cr.final_price or _cr.regular_price) if _cr else _it.old_price,
                        new_price=_it.new_price,
                        old_stock_status=_cr.stock_status if _cr else _it.stock_status,
                        new_stock_status=_new_stock,
                        old_stock_quantity=_cr.stock_quantity if _cr else _it.stock_quantity,
                        username=user_data["sub"],
                        job_id=job_id,
                        source="apply",
                    )
                db.commit()

                now = datetime.utcnow()
                result_map: dict[int, dict] = {}
                completed = 0
                total_to_update = len(to_update)
                _APPLY_CHUNK_SIZE = 10

                for _chunk_start in range(0, total_to_update, _APPLY_CHUNK_SIZE):
                    chunk_items = to_update[_chunk_start:_chunk_start + _APPLY_CHUNK_SIZE]
                    chunk_updates = updates[_chunk_start:_chunk_start + _APPLY_CHUNK_SIZE]
                    try:
                        chunk_wc_results = await batch_update_prices(chunk_updates)
                        chunk_result_map = {r["product_id"]: r for r in chunk_wc_results}
                    except Exception as exc:
                        logger.warning(
                            "apply_stream: chunk update failed job=%d pids=%s: %s",
                            job_id, [i.product_id for i in chunk_items], exc,
                        )
                        _audit(user_data["sub"], "apply_chunk_failed", ip, job_id, {
                            "product_ids": [i.product_id for i in chunk_items],
                            "error": str(exc),
                        })
                        chunk_result_map = {
                            i.product_id: {"success": False, "error_message": str(exc)}
                            for i in chunk_items
                        }
                    result_map.update(chunk_result_map)

                    for item in chunk_items:
                        r = chunk_result_map.get(item.product_id, {})
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
                            # Phase C: per-product audit events
                            _audit(user_data["sub"], "product_price_changed", ip, job_id, {
                                "product_id": item.product_id,
                                "old_value": item.old_price,
                                "new_value": item.new_price,
                                "source": "apply",
                            })
                            if getattr(item, "stock_changed", 0):
                                _audit(user_data["sub"], "product_stock_changed", ip, job_id, {
                                    "product_id": item.product_id,
                                    "new_value": _stock_from_price(item.new_price),
                                    "source": "apply",
                                })
                        completed += 1
                        yield ev({
                            "type": "item",
                            "product_id": item.product_id,
                            "product_name": item.product_name or "",
                            "sku": item.sku or "",
                            "status": item.status.value,
                            "old_price": item.old_price or "",
                            "new_price": item.new_price,
                            "error": item.error_message or "",
                            "completed": completed,
                            "total": total_to_update,
                            "percentage": round(completed / total_to_update * 100),
                        })
                    # Commit progress per chunk so completed work survives a mid-apply crash.
                    db.commit()

                await _sync_parent_stock(updates, result_map, db)

            job.updated_count = sum(1 for i in items if i.status == ItemStatus.updated)
            job.failed_count  = sum(1 for i in items if i.status == ItemStatus.failed)
            job.skipped_count = sum(1 for i in items if i.status == ItemStatus.skipped)
            job.status = JobStatus.completed
            job.completed_at = datetime.utcnow()
            # Phase C: analytics + completion audit
            _upsert_daily_metrics(
                db, _today_str(),
                apply_jobs=1,
                updated_products=job.updated_count,
                failed_products=job.failed_count,
            )
            db.commit()

            _audit(user_data["sub"], "apply", ip, job.id)
            _audit(user_data["sub"], "apply_completed", ip, job.id, {
                "updated": job.updated_count,
                "failed": job.failed_count,
                "skipped": job.skipped_count,
            })

            yield ev({"type": "done", "job_id": job_id,
                      "updated": job.updated_count, "failed": job.failed_count, "skipped": job.skipped_count})
        finally:
            db.close()

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── 8. Write back to sheet ────────────────────────────────────────────────────

@app.post("/api/jobs/{job_id}/writeback")
async def writeback(job_id: int, user: dict = Depends(require_permission("can_apply")), db: Session = Depends(get_db)):
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


# ── 9. Rollback (Phase C — admin only) ────────────────────────────────────────

async def _rollback_one(db: Session, entry: ChangeHistory, username: str) -> dict:
    """Restore the prior state captured in a single change_history entry via WooCommerce.

    Returns a per-product result dict. Records a new change_history row with
    source='rollback' and rollback_of_id pointing to the reverted entry, and patches
    the local cache. Raises on WooCommerce failure (caller decides how to surface)."""
    pid = entry.product_id
    parent_id = entry.parent_id or 0

    # Build the WC payload from the OLD (pre-change) state. Price restore is primary;
    # stock status restore is included when we have a recorded old value.
    payload: dict = {}
    if entry.old_price is not None and str(entry.old_price).strip() != "":
        payload["regular_price"] = str(entry.old_price)
    if entry.old_stock_status:
        payload["stock_status"] = entry.old_stock_status
    if entry.old_stock_quantity is not None:
        payload["stock_quantity"] = entry.old_stock_quantity
        payload["manage_stock"] = True

    if not payload:
        return {"product_id": pid, "success": False,
                "error_message": "Nothing to restore — recorded prior state was empty."}

    # Capture current cache state to record as the 'old' of the rollback row.
    cache_row = db.query(ProductCache).filter(ProductCache.wc_id == pid).first()
    cur_price = (cache_row.final_price or cache_row.regular_price) if cache_row else entry.new_price
    cur_stock = cache_row.stock_status if cache_row else entry.new_stock_status

    await update_single_product(pid, payload, parent_id)

    # Patch local cache to reflect the restored values.
    patch_fields: dict = {}
    if "regular_price" in payload:
        patch_fields["regular_price"] = payload["regular_price"]
        patch_fields["final_price"] = payload["regular_price"]
    if "stock_status" in payload:
        patch_fields["stock_status"] = payload["stock_status"]
    if "stock_quantity" in payload:
        patch_fields["stock_quantity"] = payload["stock_quantity"]
    if patch_fields:
        patch_cached_product(db, pid, patch_fields)

    # Record the rollback itself as a new change_history row.
    _record_change_history(
        db,
        product_id=pid,
        parent_id=parent_id,
        old_price=cur_price,
        new_price=payload.get("regular_price", cur_price),
        old_stock_status=cur_stock,
        new_stock_status=payload.get("stock_status", cur_stock),
        old_stock_quantity=cache_row.stock_quantity if cache_row else None,
        new_stock_quantity=payload.get("stock_quantity"),
        username=username,
        job_id=entry.job_id,
        source="rollback",
        rollback_of_id=entry.id,
    )

    # WC state changed — invalidate any active dry runs for this product.
    _invalidate_dry_runs_for_product(db, pid)

    return {"product_id": pid, "success": True,
            "restored_price": payload.get("regular_price"),
            "restored_stock_status": payload.get("stock_status")}


@app.post("/api/rollback/product/{product_id}")
async def rollback_product(
    product_id: int,
    request: Request,
    user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Roll back the most recent change_history entry for a single product (admin only)."""
    ip = _client_ip(request)
    username = user["sub"]

    # Latest non-rollback change for this product (don't roll back a rollback by default).
    entry = (
        db.query(ChangeHistory)
        .filter(ChangeHistory.product_id == product_id, ChangeHistory.source != "rollback")
        .order_by(ChangeHistory.changed_at.desc(), ChangeHistory.id.desc())
        .first()
    )
    if entry is None:
        raise HTTPException(404, "No change history found for this product — nothing to roll back.")

    _audit(username, "rollback_started", ip, entry.job_id,
           {"product_id": product_id, "change_history_id": entry.id, "scope": "product"})
    try:
        result = await _rollback_one(db, entry, username)
        if not result.get("success"):
            db.rollback()
            _audit(username, "rollback_failed", ip, entry.job_id,
                   {"product_id": product_id, "reason": result.get("error_message")})
            raise HTTPException(400, result.get("error_message") or "Rollback failed")
        _upsert_daily_metrics(db, _today_str(), rollback_jobs=1)
        db.commit()
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.error("rollback_product: pid=%d error=%s", product_id, exc)
        _audit(username, "rollback_failed", ip, entry.job_id,
               {"product_id": product_id, "error": str(exc)})
        raise HTTPException(502, f"Rollback failed: {exc}")

    _audit(username, "rollback_completed", ip, entry.job_id,
           {"product_id": product_id, "change_history_id": entry.id, "scope": "product"})
    return {"product_id": product_id, "status": "rolled_back", **result}


@app.post("/api/rollback/job/{job_id}")
async def rollback_job(
    job_id: int,
    request: Request,
    user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Roll back every change_history entry for a job, in reverse chronological order.
    Admin only. Rejects jobs with more than 500 recorded changes."""
    ip = _client_ip(request)
    username = user["sub"]

    entries = (
        db.query(ChangeHistory)
        .filter(ChangeHistory.job_id == job_id, ChangeHistory.source == "apply")
        .order_by(ChangeHistory.changed_at.desc(), ChangeHistory.id.desc())
        .all()
    )
    if not entries:
        raise HTTPException(404, "No applied changes found for this job — nothing to roll back.")
    if len(entries) > 500:
        raise HTTPException(400, f"Job has {len(entries)} changes — rollback is limited to 500 products.")

    _audit(username, "rollback_started", ip, job_id, {"scope": "job", "count": len(entries)})

    succeeded = 0
    failed = 0
    results: list[dict] = []
    # Roll back each entry independently; one failure must not abort the rest.
    for entry in entries:
        try:
            res = await _rollback_one(db, entry, username)
            if res.get("success"):
                db.commit()
                succeeded += 1
            else:
                db.rollback()
                failed += 1
            results.append(res)
        except Exception as exc:
            db.rollback()
            failed += 1
            results.append({"product_id": entry.product_id, "success": False, "error_message": str(exc)})
            logger.warning("rollback_job: job=%d pid=%d error=%s", job_id, entry.product_id, exc)

    try:
        _upsert_daily_metrics(db, _today_str(), rollback_jobs=1)
        db.commit()
    except Exception:
        db.rollback()

    if succeeded == 0:
        _audit(username, "rollback_failed", ip, job_id,
               {"scope": "job", "succeeded": succeeded, "failed": failed})
        raise HTTPException(502, "Rollback failed for all products in the job.")

    _audit(username, "rollback_completed", ip, job_id,
           {"scope": "job", "succeeded": succeeded, "failed": failed})
    return {"job_id": job_id, "status": "rolled_back",
            "succeeded": succeeded, "failed": failed, "results": results}


# ── SPA catch-all ─────────────────────────────────────────────────────────────

@app.get("/{full_path:path}", response_class=HTMLResponse)
async def spa_fallback(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not Found")
    return (static_dir / "index.html").read_text(encoding="utf-8")
