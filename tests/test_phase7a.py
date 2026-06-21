"""Phase 7A regression tests.

Covers remediation of:
  HIGH 1   — Sheet coverage formula (numerator/denominator mismatch → >100%)
  HIGH 2   — Daily chart counts failed Apply attempts (pre-write ChangeHistory rows)
  MEDIUM 1 — Stock transition filter semantics, including NULL old-status/quantity
  MEDIUM 2 — Tests call the actual functions used by the endpoints, not duplicate predicates

Run directly (no pytest dependency):
    python tests/test_phase7a.py
"""
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("NEXTCLOUD_URL", "http://example.invalid")
os.environ.setdefault("NEXTCLOUD_USER", "x")
os.environ.setdefault("NEXTCLOUD_PASSWORD", "x")
os.environ.setdefault("NEXTCLOUD_FILE_PATH", "/x.xlsx")
os.environ.setdefault("WC_URL", "http://example.invalid")
os.environ.setdefault("WC_KEY", "x")
os.environ.setdefault("WC_SECRET", "x")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.database import Base  # noqa: E402
from app.main import (  # noqa: E402
    _apply_change_type_filter,
    _compute_sheet_coverage,
    _query_confirmed_apply_rows,
)
from app.models import (  # noqa: E402
    ChangeHistory, ItemStatus, JobStatus, ProductCache, SyncItem, SyncJob,
)


# ── Test-local DB (fresh in-memory instance per test) ─────────────────────────

def _make_db():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


# ── Test-data helpers ─────────────────────────────────────────────────────────

def _pc(db, wc_id: int, parent_id: int = 0) -> ProductCache:
    p = ProductCache(wc_id=wc_id, parent_id=parent_id, name=f"P{wc_id}", sku=f"SKU{wc_id}", product_type="simple")
    db.add(p)
    db.flush()
    return p


def _job(db) -> SyncJob:
    j = SyncJob(status=JobStatus.completed)
    db.add(j)
    db.flush()
    return j


def _item(db, job: SyncJob, product_id: int, status: ItemStatus = ItemStatus.updated) -> SyncItem:
    i = SyncItem(job_id=job.id, product_id=product_id, new_price="100", status=status)
    db.add(i)
    db.flush()
    return i


def _ch(db, job, product_id: int, old_s=None, new_s: str = "instock",
        old_q=None, new_q=None) -> ChangeHistory:
    row = ChangeHistory(
        product_id=product_id,
        job_id=job.id if job else None,
        source="apply",
        old_stock_status=old_s,
        new_stock_status=new_s,
        old_stock_quantity=old_q,
        new_stock_quantity=new_q,
        changed_at=datetime.utcnow(),
    )
    db.add(row)
    db.flush()
    return row


# ── HIGH 1: Sheet coverage formula — uses _compute_sheet_coverage ─────────────

def test_coverage_normal_partial():
    """3 of 5 top-level products covered → 60%."""
    db = _make_db()
    for wc_id in range(1, 6):
        _pc(db, wc_id)
    job = _job(db)
    for wc_id in [1, 2, 3]:
        _item(db, job, wc_id)
    r = _compute_sheet_coverage(db, job)
    assert r["total_cache"] == 5
    assert r["sheet_products"] == 3
    assert r["not_covered"] == 2
    assert r["coverage_pct"] == 60.0
    print("test_coverage_normal_partial: PASS")


def test_coverage_duplicate_sheet_ids_counted_once():
    """Same product_id twice in SyncItems → counted once (DISTINCT)."""
    db = _make_db()
    _pc(db, 10)
    _pc(db, 11)
    job = _job(db)
    _item(db, job, 10)
    _item(db, job, 10)  # duplicate
    r = _compute_sheet_coverage(db, job)
    assert r["sheet_products"] == 1, f"expected 1, got {r['sheet_products']}"
    assert r["coverage_pct"] == 50.0
    print("test_coverage_duplicate_sheet_ids_counted_once: PASS")


def test_coverage_variation_ids_excluded():
    """SyncItem referencing a variation (parent_id != 0) must NOT count toward coverage."""
    db = _make_db()
    _pc(db, 20, parent_id=0)
    _pc(db, 21, parent_id=20)  # variation
    job = _job(db)
    _item(db, job, 21)  # sheet references the variation ID
    r = _compute_sheet_coverage(db, job)
    assert r["total_cache"] == 1
    assert r["sheet_products"] == 0, "variation ID must not count as covered"
    assert r["coverage_pct"] == 0.0
    print("test_coverage_variation_ids_excluded: PASS")


def test_coverage_ids_absent_from_cache_not_counted():
    """SyncItem product_ids not in ProductCache must not inflate the numerator."""
    db = _make_db()
    _pc(db, 30)
    job = _job(db)
    _item(db, job, 30)
    _item(db, job, 99)   # not in cache
    _item(db, job, 100)  # not in cache
    r = _compute_sheet_coverage(db, job)
    assert r["total_cache"] == 1
    assert r["sheet_products"] == 1
    assert r["coverage_pct"] == 100.0
    print("test_coverage_ids_absent_from_cache_not_counted: PASS")


def test_coverage_never_exceeds_100():
    """Even with more SyncItems than cached products, coverage_pct <= 100."""
    db = _make_db()
    _pc(db, 40)
    job = _job(db)
    _item(db, job, 40)
    _item(db, job, 41)  # not in cache — would push > 100 if counted
    _item(db, job, 42)  # not in cache
    r = _compute_sheet_coverage(db, job)
    assert r["coverage_pct"] <= 100.0
    assert r["sheet_products"] == 1
    print("test_coverage_never_exceeds_100: PASS")


def test_coverage_no_job_is_zero():
    """When no job exists, sheet_products = 0 and coverage_pct = 0."""
    db = _make_db()
    _pc(db, 50)
    r = _compute_sheet_coverage(db, latest_job=None)
    assert r["total_cache"] == 1
    assert r["sheet_products"] == 0
    assert r["coverage_pct"] == 0.0
    print("test_coverage_no_job_is_zero: PASS")


# ── HIGH 2: Daily chart success filtering — uses _query_confirmed_apply_rows ──

_EPOCH = datetime(2000, 1, 1)   # start_dt older than any test row


def test_successful_apply_included_in_chart():
    """ChangeHistory + SyncItem(status=updated) → included by _query_confirmed_apply_rows."""
    db = _make_db()
    job = _job(db)
    _ch(db, job, 100)
    _item(db, job, 100, status=ItemStatus.updated)
    rows = _query_confirmed_apply_rows(db, _EPOCH)
    assert len(rows) == 1
    print("test_successful_apply_included_in_chart: PASS")


def test_failed_apply_excluded_from_chart():
    """Pre-write ChangeHistory row + SyncItem(status=failed) → excluded."""
    db = _make_db()
    job = _job(db)
    _ch(db, job, 101)
    _item(db, job, 101, status=ItemStatus.failed)
    rows = _query_confirmed_apply_rows(db, _EPOCH)
    assert len(rows) == 0
    print("test_failed_apply_excluded_from_chart: PASS")


def test_no_syncitem_excluded_from_chart():
    """ChangeHistory with no matching SyncItem at all → excluded."""
    db = _make_db()
    job = _job(db)
    _ch(db, job, 102)
    # No SyncItem created
    rows = _query_confirmed_apply_rows(db, _EPOCH)
    assert len(rows) == 0
    print("test_no_syncitem_excluded_from_chart: PASS")


# ── MEDIUM 1: Stock transition filters — use _apply_change_type_filter ─────────
# Tests call the actual filter function used by /api/analytics/change-log.

def _count(db, change_type: str) -> int:
    q = db.query(ChangeHistory)
    q = _apply_change_type_filter(q, change_type)
    return q.count()


# stock_in tests

def test_null_to_instock_is_stock_in():
    """NULL → instock must appear in stock_in (previously missed by != filter)."""
    db = _make_db()
    job = _job(db)
    _ch(db, job, 200, old_s=None, new_s="instock")
    assert _count(db, "stock_in") == 1
    print("test_null_to_instock_is_stock_in: PASS")


def test_outofstock_to_instock_is_stock_in():
    """outofstock → instock must match stock_in."""
    db = _make_db()
    job = _job(db)
    _ch(db, job, 201, old_s="outofstock", new_s="instock")
    assert _count(db, "stock_in") == 1
    print("test_outofstock_to_instock_is_stock_in: PASS")


def test_instock_price_update_not_stock_in():
    """Already-instock product with price change must NOT match stock_in."""
    db = _make_db()
    job = _job(db)
    _ch(db, job, 202, old_s="instock", new_s="instock")
    assert _count(db, "stock_in") == 0
    print("test_instock_price_update_not_stock_in: PASS")


# stock_out tests

def test_null_to_outofstock_is_stock_out():
    """NULL → outofstock must appear in stock_out (previously missed by != filter)."""
    db = _make_db()
    job = _job(db)
    _ch(db, job, 210, old_s=None, new_s="outofstock")
    assert _count(db, "stock_out") == 1
    print("test_null_to_outofstock_is_stock_out: PASS")


def test_instock_to_outofstock_is_stock_out():
    """instock → outofstock must match stock_out."""
    db = _make_db()
    job = _job(db)
    _ch(db, job, 211, old_s="instock", new_s="outofstock")
    assert _count(db, "stock_out") == 1
    print("test_instock_to_outofstock_is_stock_out: PASS")


def test_outofstock_price_update_not_stock_out():
    """Already-outofstock product must NOT match stock_out."""
    db = _make_db()
    job = _job(db)
    _ch(db, job, 212, old_s="outofstock", new_s="outofstock")
    assert _count(db, "stock_out") == 0
    print("test_outofstock_price_update_not_stock_out: PASS")


def test_became_outofstock_not_counted_as_stock_in():
    """instock → outofstock matches stock_out but NOT stock_in."""
    db = _make_db()
    job = _job(db)
    _ch(db, job, 213, old_s="instock", new_s="outofstock")
    assert _count(db, "stock_in") == 0
    assert _count(db, "stock_out") == 1
    print("test_became_outofstock_not_counted_as_stock_in: PASS")


# stock_updated tests

def test_null_qty_to_value_is_stock_updated():
    """NULL quantity → 5 must appear in stock_updated (previously missed by != filter)."""
    db = _make_db()
    job = _job(db)
    _ch(db, job, 220, old_s="instock", new_s="instock", old_q=None, new_q=5)
    assert _count(db, "stock_updated") == 1
    print("test_null_qty_to_value_is_stock_updated: PASS")


def test_quantity_only_change_is_stock_updated():
    """Same status, different quantity → must match stock_updated."""
    db = _make_db()
    job = _job(db)
    _ch(db, job, 221, old_s="instock", new_s="instock", old_q=10, new_q=5)
    assert _count(db, "stock_updated") == 1
    print("test_quantity_only_change_is_stock_updated: PASS")


def test_price_only_change_not_stock_updated():
    """Same status, same quantity → must NOT match stock_updated."""
    db = _make_db()
    job = _job(db)
    _ch(db, job, 222, old_s="instock", new_s="instock", old_q=10, new_q=10)
    assert _count(db, "stock_updated") == 0
    print("test_price_only_change_not_stock_updated: PASS")


def test_status_change_is_stock_updated():
    """Status transition also counts as stock_updated."""
    db = _make_db()
    job = _job(db)
    _ch(db, job, 223, old_s="outofstock", new_s="instock")
    assert _count(db, "stock_updated") == 1
    print("test_status_change_is_stock_updated: PASS")


# ── Entry point for direct execution ─────────────────────────────────────────

if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        try:
            fn()
            passed += 1
        except Exception as exc:
            print(f"{fn.__name__}: FAIL — {exc}")
    print(f"\n{passed}/{len(fns)} passed")
