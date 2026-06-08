import json
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from .config import get_settings
from .database import Base, SessionLocal, engine, get_db
from .models import ItemStatus, JobStatus, SyncItem, SyncJob
from .services.nextcloud import download_xlsx, parse_price_list, write_back_to_sheet
from .services.woocommerce import batch_update_prices, fetch_product_prices

Base.metadata.create_all(bind=engine)

app = FastAPI(title="WooPrice Sync", docs_url="/docs")

static_dir = Path(__file__).parent.parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# ── helpers ───────────────────────────────────────────────────────────────────

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
    return {
        "product_id": item.product_id,
        "product_name": item.product_name,
        "old_price": item.old_price,
        "new_price": item.new_price,
        "status": item.status,
        "error_message": item.error_message,
        "synced_at": item.synced_at,
        "changed": _price_differs(item.old_price, item.new_price),
    }


# ── static dashboard ──────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    return (static_dir / "index.html").read_text(encoding="utf-8")


# ── health ────────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    s = get_settings()
    return {"status": "ok", "wc_url": s.wc_url, "nextcloud_url": s.nextcloud_url}


# ── 1. create preview ─────────────────────────────────────────────────────────

@app.post("/api/preview")
async def create_preview(db: Session = Depends(get_db)):
    try:
        xlsx = await download_xlsx()
    except Exception as exc:
        raise HTTPException(502, f"Cannot download sheet from Nextcloud: {exc}")

    sheet_items = parse_price_list(xlsx)
    if not sheet_items:
        raise HTTPException(
            400,
            "No valid rows found. Expected product IDs in column A and prices in "
            "column B, starting from row 3.",
        )

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
        item = SyncItem(
            job_id=job.id,
            product_id=pid,
            parent_id=wc.get("parent_id") or 0,
            product_name=wc.get("name") or None,
            old_price=old_price,
            new_price=row["new_price"],
        )
        db.add(item)
        preview_rows.append(
            {
                "product_id": pid,
                "product_name": wc.get("name", ""),
                "old_price": old_price or "",
                "new_price": row["new_price"],
                "changed": _price_differs(old_price, row["new_price"]),
                "found_in_wc": pid in wc_data,
            }
        )

    db.commit()

    changed = sum(1 for r in preview_rows if r["changed"])
    return {
        "job_id": job.id,
        "total": len(preview_rows),
        "changed_count": changed,
        "unchanged_count": len(preview_rows) - changed,
        "items": preview_rows,
    }


# ── 2. confirm → execute sync ─────────────────────────────────────────────────

@app.post("/api/sync/{job_id}/confirm")
async def confirm_sync(job_id: int, db: Session = Depends(get_db)):
    job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status != JobStatus.preview:
        raise HTTPException(400, f"Job is '{job.status}', expected 'preview'")

    job.status = JobStatus.running
    db.commit()

    items = db.query(SyncItem).filter(SyncItem.job_id == job_id).all()

    to_update = [i for i in items if _price_differs(i.old_price, i.new_price)]
    to_skip = [i for i in items if not _price_differs(i.old_price, i.new_price)]

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
    job.failed_count = sum(1 for i in items if i.status == ItemStatus.failed)
    job.skipped_count = sum(1 for i in items if i.status == ItemStatus.skipped)
    job.status = JobStatus.completed
    job.completed_at = datetime.utcnow()
    db.commit()

    return {
        "job_id": job_id,
        "status": "completed",
        "updated": job.updated_count,
        "failed": job.failed_count,
        "skipped": job.skipped_count,
    }


# ── 3. cancel preview ─────────────────────────────────────────────────────────

@app.delete("/api/sync/{job_id}")
async def cancel_sync(job_id: int, db: Session = Depends(get_db)):
    job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status != JobStatus.preview:
        raise HTTPException(400, "Only preview jobs can be cancelled")
    job.status = JobStatus.cancelled
    db.commit()
    return {"job_id": job_id, "status": "cancelled"}


# ── 4. list jobs ──────────────────────────────────────────────────────────────

@app.get("/api/jobs")
async def list_jobs(limit: int = 30, db: Session = Depends(get_db)):
    jobs = (
        db.query(SyncJob).order_by(SyncJob.created_at.desc()).limit(limit).all()
    )
    return [_job_out(j) for j in jobs]


# ── 5. job detail ─────────────────────────────────────────────────────────────

@app.get("/api/jobs/{job_id}")
async def get_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    items = db.query(SyncItem).filter(SyncItem.job_id == job_id).all()
    return {**_job_out(job), "items": [_item_out(i) for i in items]}


# ── 6. preview stream (SSE) ───────────────────────────────────────────────────

@app.get("/api/preview/stream")
async def preview_stream():
    async def generate():
        db = SessionLocal()
        try:
            def ev(data: dict) -> str:
                return f"data: {json.dumps(data)}\n\n"

            yield ev({"step": "excel", "status": "running", "msg": "Downloading price list from Nextcloud…"})
            try:
                xlsx = await download_xlsx()
            except Exception as exc:
                yield ev({"step": "excel", "status": "error", "msg": str(exc)})
                return

            sheet_items = parse_price_list(xlsx)
            if not sheet_items:
                yield ev({"step": "excel", "status": "error", "msg": "No valid rows found (expected product IDs in col A, prices in col B from row 3)"})
                return
            yield ev({"step": "excel", "status": "done", "msg": f"Found {len(sheet_items)} products in price list"})

            yield ev({"step": "wc", "status": "running", "msg": f"Fetching current prices from WooCommerce for {len(sheet_items)} products…"})
            product_ids = [i["product_id"] for i in sheet_items]
            try:
                wc_data = await fetch_product_prices(product_ids)
            except Exception as exc:
                yield ev({"step": "wc", "status": "error", "msg": str(exc)})
                return
            yield ev({"step": "wc", "status": "done", "msg": f"Fetched prices for {len(wc_data)} products from WooCommerce"})

            yield ev({"step": "calc", "status": "running", "msg": "Calculating price differences…"})

            job = SyncJob(status=JobStatus.preview, total_count=len(sheet_items))
            db.add(job)
            db.flush()

            preview_rows = []
            for row in sheet_items:
                pid = row["product_id"]
                wc = wc_data.get(pid, {})
                old_price = wc.get("price") or None
                item = SyncItem(
                    job_id=job.id,
                    product_id=pid,
                    parent_id=wc.get("parent_id") or 0,
                    product_name=wc.get("name") or None,
                    old_price=old_price,
                    new_price=row["new_price"],
                )
                db.add(item)
                preview_rows.append({
                    "product_id": pid,
                    "product_name": wc.get("name", ""),
                    "old_price": old_price or "",
                    "new_price": row["new_price"],
                    "changed": _price_differs(old_price, row["new_price"]),
                    "found_in_wc": pid in wc_data,
                })
            db.commit()

            changed = sum(1 for r in preview_rows if r["changed"])
            yield ev({"step": "calc", "status": "done", "msg": f"{changed} prices will change, {len(preview_rows) - changed} are unchanged"})

            yield ev({
                "step": "preview", "status": "done",
                "job_id": job.id,
                "total": len(preview_rows),
                "changed_count": changed,
                "unchanged_count": len(preview_rows) - changed,
                "items": preview_rows,
            })
        finally:
            db.close()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── 7. apply stream (SSE) ─────────────────────────────────────────────────────

@app.get("/api/sync/{job_id}/apply-stream")
async def apply_stream(job_id: int):
    async def generate():
        db = SessionLocal()
        try:
            def ev(data: dict) -> str:
                return f"data: {json.dumps(data)}\n\n"

            job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
            if not job:
                yield ev({"type": "error", "msg": "Job not found"})
                return
            if job.status != JobStatus.preview:
                yield ev({"type": "error", "msg": f"Job is '{job.status}', expected 'preview'"})
                return

            job.status = JobStatus.running
            db.commit()

            items = db.query(SyncItem).filter(SyncItem.job_id == job_id).all()
            to_update = [i for i in items if _price_differs(i.old_price, i.new_price)]
            to_skip = [i for i in items if not _price_differs(i.old_price, i.new_price)]

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
                    yield ev({"type": "error", "msg": f"WooCommerce batch update failed: {exc}"})
                    return

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
                        "status": item.status.value,
                        "old_price": item.old_price or "",
                        "new_price": item.new_price,
                        "error": item.error_message or "",
                    })

            job.updated_count = sum(1 for i in items if i.status == ItemStatus.updated)
            job.failed_count = sum(1 for i in items if i.status == ItemStatus.failed)
            job.skipped_count = sum(1 for i in items if i.status == ItemStatus.skipped)
            job.status = JobStatus.completed
            job.completed_at = datetime.utcnow()
            db.commit()

            yield ev({
                "type": "done",
                "job_id": job_id,
                "updated": job.updated_count,
                "failed": job.failed_count,
                "skipped": job.skipped_count,
            })
        finally:
            db.close()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── 8. write back to sheet ────────────────────────────────────────────────────

@app.post("/api/jobs/{job_id}/writeback")
async def writeback(job_id: int, db: Session = Depends(get_db)):
    job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status != JobStatus.completed:
        raise HTTPException(400, "Job must be completed before writing back to sheet")

    items = db.query(SyncItem).filter(SyncItem.job_id == job_id).all()
    payload = [
        {
            "product_id": i.product_id,
            "status": i.status.value,
            "synced_at": i.synced_at.isoformat() if i.synced_at else "",
            "error_message": i.error_message or "",
        }
        for i in items
    ]

    try:
        await write_back_to_sheet(payload)
    except Exception as exc:
        raise HTTPException(502, f"Failed to write back to Nextcloud sheet: {exc}")

    return {"message": "Results written back to spreadsheet (columns E, F, G)"}
