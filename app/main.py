import json
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Header, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import inspect as sa_inspect, text
from sqlalchemy.orm import Session

from .config import get_settings
from .database import Base, SessionLocal, engine, get_db
from .models import AlarmThreshold, AuditLog, ItemStatus, JobStatus, SyncItem, SyncJob
from .services.auth import create_token, decode_token, is_super_admin, verify_nextcloud_credentials
from .services.nextcloud import download_xlsx, parse_price_list, write_back_to_sheet
from .services.woocommerce import batch_update_prices, fetch_categories, fetch_product_prices

Base.metadata.create_all(bind=engine)


def _run_column_migrations():
    """Add new columns / tables to existing databases."""
    with engine.connect() as conn:
        inspector = sa_inspect(engine)
        existing_tables = inspector.get_table_names()

        if "sync_items" in existing_tables:
            existing_cols = {c["name"] for c in inspector.get_columns("sync_items")}
            for col_name, col_type in [
                ("sku", "TEXT"), ("sale_price", "TEXT"), ("stock_status", "TEXT"),
                ("stock_quantity", "INTEGER"), ("categories", "TEXT"),
            ]:
                if col_name not in existing_cols:
                    conn.execute(text(f"ALTER TABLE sync_items ADD COLUMN {col_name} {col_type}"))

        conn.commit()


_run_column_migrations()

app = FastAPI(title="WooPrice Sync", docs_url="/docs")

static_dir = Path(__file__).parent.parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# ── Pydantic models ───────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class AlarmThresholdItem(BaseModel):
    category_id: int | None = None
    threshold_percent: float


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

def _audit(db: Session, username: str, action: str, ip: str = "unknown", job_id: int | None = None):
    db.add(AuditLog(username=username, action=action, ip_address=ip, job_id=job_id))
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
        "status": item.status,
        "error_message": item.error_message,
        "synced_at": item.synced_at,
        "changed": _price_differs(item.old_price, item.new_price),
    }


def _build_preview_row(pid: int, wc: dict, new_price: str) -> dict:
    old_price = wc.get("price") or None
    return {
        "product_id": pid,
        "product_name": wc.get("name", ""),
        "sku": wc.get("sku", ""),
        "old_price": old_price or "",
        "new_price": new_price,
        "sale_price": wc.get("sale_price", ""),
        "stock_status": wc.get("stock_status", ""),
        "stock_quantity": wc.get("stock_quantity"),
        "categories": wc.get("categories", []),
        "changed": _price_differs(old_price, new_price),
        "found_in_wc": bool(wc),
    }


# ── Static dashboard ──────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    return (static_dir / "index.html").read_text(encoding="utf-8")


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    s = get_settings()
    return {"status": "ok", "wc_url": s.wc_url, "nextcloud_url": s.nextcloud_url}


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
    return [
        {
            "id": l.id,
            "username": l.username,
            "action": l.action,
            "timestamp": l.timestamp,
            "ip_address": l.ip_address,
            "job_id": l.job_id,
        }
        for l in logs
    ]


# ── Categories ────────────────────────────────────────────────────────────────

@app.get("/api/categories")
async def get_categories(user: dict = Depends(get_current_user)):
    try:
        return await fetch_categories()
    except Exception as exc:
        raise HTTPException(502, f"Cannot fetch categories from WooCommerce: {exc}")


# ── 1. Create preview ─────────────────────────────────────────────────────────

@app.post("/api/preview")
async def create_preview(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        xlsx = await download_xlsx()
    except Exception as exc:
        raise HTTPException(502, f"Cannot download sheet from Nextcloud: {exc}")

    sheet_items = parse_price_list(xlsx)
    if not sheet_items:
        raise HTTPException(400, "No valid rows found.")

    product_ids = [i["product_id"] for i in sheet_items]
    try:
        wc_data = await fetch_product_prices(product_ids)
    except Exception as exc:
        raise HTTPException(502, f"Cannot fetch prices from WooCommerce: {exc}")

    job = SyncJob(status=JobStatus.preview, total_count=len(sheet_items))
    db.add(job)
    db.flush()

    preview_rows = []
    for row in sheet_items:
        pid = row["product_id"]
        wc = wc_data.get(pid, {})
        old_price = wc.get("price") or None
        db.add(SyncItem(
            job_id=job.id, product_id=pid,
            parent_id=wc.get("parent_id") or 0,
            product_name=wc.get("name") or None,
            sku=wc.get("sku") or None,
            old_price=old_price, new_price=row["new_price"],
            sale_price=wc.get("sale_price") or None,
            stock_status=wc.get("stock_status") or None,
            stock_quantity=wc.get("stock_quantity"),
            categories=json.dumps(wc.get("categories", [])),
        ))
        preview_rows.append(_build_preview_row(pid, wc, row["new_price"]))

    db.commit()
    changed = sum(1 for r in preview_rows if r["changed"])
    return {"job_id": job.id, "total": len(preview_rows), "changed_count": changed,
            "unchanged_count": len(preview_rows) - changed, "items": preview_rows}


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
        updates = [{"product_id": i.product_id, "new_price": i.new_price, "parent_id": i.parent_id or 0} for i in to_update]
        try:
            wc_results = await batch_update_prices(updates)
        except Exception as exc:
            job.status = JobStatus.failed
            db.commit()
            raise HTTPException(502, f"WooCommerce batch update failed: {exc}")

        result_map = {r["product_id"]: r for r in wc_results}
        for item in to_update:
            r = result_map.get(item.product_id, {})
            item.status = ItemStatus.updated if r.get("success") else ItemStatus.failed
            item.error_message = r.get("error_message")
            item.synced_at = datetime.utcnow()

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
                xlsx = await download_xlsx()
            except Exception as exc:
                yield ev({"step": "excel", "status": "error", "msg": str(exc)}); return

            sheet_items = parse_price_list(xlsx)
            if not sheet_items:
                yield ev({"step": "excel", "status": "error", "msg": "No valid rows found (expected product IDs in col A, prices in col B from row 3)"}); return
            yield ev({"step": "excel", "status": "done", "msg": f"Found {len(sheet_items)} products in price list"})

            yield ev({"step": "wc", "status": "running", "msg": f"Fetching current data from WooCommerce for {len(sheet_items)} products…"})
            product_ids = [i["product_id"] for i in sheet_items]
            try:
                wc_data = await fetch_product_prices(product_ids)
            except Exception as exc:
                yield ev({"step": "wc", "status": "error", "msg": str(exc)}); return
            yield ev({"step": "wc", "status": "done", "msg": f"Fetched data for {len(wc_data)} products from WooCommerce"})

            yield ev({"step": "calc", "status": "running", "msg": "Calculating price differences…"})

            job = SyncJob(status=JobStatus.preview, total_count=len(sheet_items))
            db.add(job)
            db.flush()

            preview_rows = []
            for row in sheet_items:
                pid = row["product_id"]
                wc = wc_data.get(pid, {})
                old_price = wc.get("price") or None
                db.add(SyncItem(
                    job_id=job.id, product_id=pid,
                    parent_id=wc.get("parent_id") or 0,
                    product_name=wc.get("name") or None,
                    sku=wc.get("sku") or None,
                    old_price=old_price, new_price=row["new_price"],
                    sale_price=wc.get("sale_price") or None,
                    stock_status=wc.get("stock_status") or None,
                    stock_quantity=wc.get("stock_quantity"),
                    categories=json.dumps(wc.get("categories", [])),
                ))
                preview_rows.append(_build_preview_row(pid, wc, row["new_price"]))
            db.commit()

            _audit(db, user_data["sub"], "fetch", ip, job.id)

            changed = sum(1 for r in preview_rows if r["changed"])
            yield ev({"step": "calc", "status": "done", "msg": f"{changed} prices will change, {len(preview_rows) - changed} unchanged"})
            yield ev({
                "step": "preview", "status": "done",
                "job_id": job.id, "total": len(preview_rows),
                "changed_count": changed, "unchanged_count": len(preview_rows) - changed,
                "items": preview_rows,
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
    sid: list[int] | None = Query(None),  # selected product IDs
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

            # Respect selected product IDs if provided
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
                updates = [{"product_id": i.product_id, "new_price": i.new_price, "parent_id": i.parent_id or 0} for i in to_update]
                try:
                    wc_results = await batch_update_prices(updates)
                except Exception as exc:
                    job.status = JobStatus.failed
                    db.commit()
                    yield ev({"type": "error", "msg": f"WooCommerce batch update failed: {exc}"}); return

                result_map = {r["product_id"]: r for r in wc_results}
                for item in to_update:
                    r = result_map.get(item.product_id, {})
                    item.status = ItemStatus.updated if r.get("success") else ItemStatus.failed
                    item.error_message = r.get("error_message")
                    item.synced_at = datetime.utcnow()
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
