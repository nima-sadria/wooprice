"""Phase 7B — Emergency Price Engine + Audit/Undo tests.

Covers Codex audit remediation Rounds 1 and 2:
  BLOCKER 1   — Emergency endpoints admin-gated (non-admin gets 401/403)
  HIGH 1 R1   — Per-item pre-write checkpoint ('applying' before WC write)
  HIGH 1 R2   — Atomic batch claim: UPDATE WHERE status='pending' + rowcount==1 → 409 on conflict
  HIGH 2 R1   — Stale detection (price-drifted items skipped)
  HIGH 2 R2   — wc_succeeded intermediate status; wc_success_at timestamp;
                 needs_reconcile if DB finalization fails after successful WC write
  MEDIUM 1 R1 — Batch final status reflects item outcomes (applied/partially_failed/failed)
  MEDIUM 1 R2 — Concurrency test uses real sequential double HTTP apply (not pre-set status)
                 WC success + DB failure → needs_reconcile; normal success → cache + history
  MEDIUM 2 R2 — Non-finite values (NaN, Infinity) rejected
  MEDIUM 3    — Percentage bounds validated (0 < pct ≤ 100; fixed > 0)
  MEDIUM 4    — Integration tests real (no unconditional skip)
  LOW 1       — Rounding matches Excel MROUND (round-half-away-from-zero)
  LOW R2      — Numeric price comparison; applying/needs_reconcile visible in pending list
"""

import os
import sys
from unittest.mock import AsyncMock, patch

# Must be set before any app imports so that get_settings() (lru_cache'd) sees correct values.
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ.setdefault("NEXTCLOUD_URL", "http://example.invalid")
os.environ.setdefault("NEXTCLOUD_USER", "x")
os.environ.setdefault("NEXTCLOUD_PASSWORD", "x")
os.environ.setdefault("NEXTCLOUD_FILE_PATH", "/x.xlsx")
os.environ.setdefault("WC_URL", "http://example.invalid")
os.environ.setdefault("WC_KEY", "x")
os.environ.setdefault("WC_SECRET", "x")
os.environ.setdefault("SUPER_ADMIN_USERS", "testadmin")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import update as sa_update_direct  # noqa: E402
from sqlalchemy.orm import Session as SASession  # noqa: E402

from app.main import app, _emergency_round  # noqa: E402
from app.services.auth import create_token  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import ChangeHistory, EmergencyBatch, EmergencyItem, ProductCache  # noqa: E402


# ── Unit: rounding formula ─────────────────────────────────────────────────────
# LOW 1: Backend uses math.floor(price/unit + 0.5) = round-half-away-from-zero,
# matching Excel MROUND and JS Math.round for positive prices.

class TestEmergencyRound:
    def test_exactly_20m_uses_10k_unit(self):
        assert _emergency_round(20_000_000) == 20_000_000

    def test_below_20m_rounds_up(self):
        assert _emergency_round(15_006_000) == 15_010_000

    def test_below_20m_rounds_down(self):
        assert _emergency_round(15_004_000) == 15_000_000

    def test_midpoint_below_20m_rounds_away_from_zero(self):
        # 15_005_000 / 10_000 = 1500.5 → Excel MROUND rounds up → 15_010_000
        assert _emergency_round(15_005_000) == 15_010_000

    def test_above_20m_uses_50k_unit(self):
        assert _emergency_round(25_026_000) == 25_050_000

    def test_above_20m_rounds_down(self):
        assert _emergency_round(25_024_000) == 25_000_000

    def test_midpoint_above_20m_rounds_away_from_zero(self):
        # 25_025_000 / 50_000 = 500.5 → rounds up → 25_050_000
        assert _emergency_round(25_025_000) == 25_050_000

    def test_zero_returns_zero(self):
        assert _emergency_round(0) == 0

    def test_small_price(self):
        assert _emergency_round(55_000) == 60_000

    def test_boundary_just_above_20m_uses_50k(self):
        assert _emergency_round(20_000_001) == 20_000_000

    def test_exact_50k_multiple_unchanged(self):
        assert _emergency_round(30_000_000) == 30_000_000

    def test_above_midpoint_50k(self):
        assert _emergency_round(20_026_000) == 20_050_000


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def _admin_headers() -> dict:
    """JWT for testadmin — super admin, bypasses all DB permission checks."""
    token = create_token("testadmin", permission_version=0, role="admin")
    return {"Authorization": f"Bearer {token}"}


def _nonadmin_headers() -> dict:
    """JWT for a user that is neither super admin nor in the DB → 401/403 on protected routes."""
    token = create_token("noadmin_user", permission_version=0, role="user")
    return {"Authorization": f"Bearer {token}"}


def _seed_product(wc_id: int = 9001, price: str = "100000") -> None:
    """Insert or update a ProductCache row in the shared in-memory DB."""
    db = SessionLocal()
    try:
        existing = db.query(ProductCache).filter(ProductCache.wc_id == wc_id).first()
        if existing:
            existing.final_price = price
            existing.regular_price = price
        else:
            db.add(ProductCache(
                wc_id=wc_id, parent_id=0, product_type="simple",
                sku=f"TEST-{wc_id}", name=f"Test Product {wc_id}",
                status="publish", stock_status="instock",
                regular_price=price, final_price=price,
            ))
        db.commit()
    finally:
        db.close()


def _update_cached_price(wc_id: int, new_price: str) -> None:
    """Simulate a cache price change (e.g. from a sheet sync) after preview was created."""
    db = SessionLocal()
    try:
        p = db.query(ProductCache).filter(ProductCache.wc_id == wc_id).first()
        if p:
            p.final_price = new_price
            p.regular_price = new_price
            db.commit()
    finally:
        db.close()


def _get_batch_status(batch_id: int) -> str | None:
    db = SessionLocal()
    try:
        b = db.get(EmergencyBatch, batch_id)
        return b.status if b else None
    finally:
        db.close()


def _force_batch_status(batch_id: int, status: str) -> None:
    """Set batch to an arbitrary status directly in DB — for testing edge cases."""
    db = SessionLocal()
    try:
        b = db.get(EmergencyBatch, batch_id)
        if b:
            b.status = status
            db.commit()
    finally:
        db.close()


# ── BLOCKER 1: Admin gate ──────────────────────────────────────────────────────

class TestEmergencyAdminGate:
    """Non-admin tokens must be rejected (401/403) for all emergency endpoints."""

    def test_preview_requires_admin(self, client: TestClient):
        r = client.post("/api/emergency/preview",
                        json={"operation": "pct_increase", "value": 10.0},
                        headers=_nonadmin_headers())
        assert r.status_code in (401, 403)

    def test_apply_requires_admin(self, client: TestClient):
        r = client.post("/api/emergency/999/apply",
                        json={"confirm": True},
                        headers=_nonadmin_headers())
        assert r.status_code in (401, 403)

    def test_cancel_requires_admin(self, client: TestClient):
        r = client.delete("/api/emergency/999", headers=_nonadmin_headers())
        assert r.status_code in (401, 403)

    def test_pending_list_requires_admin(self, client: TestClient):
        r = client.get("/api/emergency/pending", headers=_nonadmin_headers())
        assert r.status_code in (401, 403)


# ── MEDIUM 3 + MEDIUM 2 R2: Input bounds + non-finite rejection ───────────────

class TestEmergencyInputBounds:
    def test_pct_above_100_rejected(self, client: TestClient):
        r = client.post("/api/emergency/preview",
                        json={"operation": "pct_increase", "value": 101.0},
                        headers=_admin_headers())
        assert r.status_code == 400

    def test_pct_zero_rejected(self, client: TestClient):
        r = client.post("/api/emergency/preview",
                        json={"operation": "pct_decrease", "value": 0.0},
                        headers=_admin_headers())
        assert r.status_code == 400

    def test_pct_negative_rejected(self, client: TestClient):
        r = client.post("/api/emergency/preview",
                        json={"operation": "pct_increase", "value": -10.0},
                        headers=_admin_headers())
        assert r.status_code == 400

    def test_fixed_zero_rejected(self, client: TestClient):
        r = client.post("/api/emergency/preview",
                        json={"operation": "fixed_increase", "value": 0.0},
                        headers=_admin_headers())
        assert r.status_code == 400

    def test_pct_exactly_100_accepted(self, client: TestClient):
        _seed_product(9001, "100000")
        r = client.post("/api/emergency/preview",
                        json={"operation": "pct_increase", "value": 100.0},
                        headers=_admin_headers())
        assert r.status_code == 200
        client.delete(f"/api/emergency/{r.json()['batch_id']}", headers=_admin_headers())

    def test_invalid_operation_rejected(self, client: TestClient):
        r = client.post("/api/emergency/preview",
                        json={"operation": "nuke_prices", "value": 10.0},
                        headers=_admin_headers())
        assert r.status_code in (400, 422)

    def test_nonfinite_value_nan_rejected(self, client: TestClient):
        """MEDIUM 2 R2: NaN is not valid JSON — parser rejects with 422; math.isfinite check gives 400."""
        r = client.post(
            "/api/emergency/preview",
            content=b'{"operation":"pct_increase","value":NaN}',
            headers={**_admin_headers(), "Content-Type": "application/json"},
        )
        assert r.status_code in (400, 422)

    def test_nonfinite_value_infinity_rejected(self, client: TestClient):
        """MEDIUM 2 R2: Infinity is not valid JSON — parser rejects with 422; math.isfinite check gives 400."""
        r = client.post(
            "/api/emergency/preview",
            content=b'{"operation":"pct_increase","value":Infinity}',
            headers={**_admin_headers(), "Content-Type": "application/json"},
        )
        assert r.status_code in (400, 422)


# ── Preview safety ─────────────────────────────────────────────────────────────

class TestEmergencyPreviewSafety:
    def test_preview_creates_batch_no_wc_write(self, client: TestClient):
        """POST /api/emergency/preview returns batch_id + items; no WooCommerce write."""
        _seed_product(9001, "100000")
        r = client.post("/api/emergency/preview",
                        json={"operation": "pct_increase", "value": 10.0},
                        headers=_admin_headers())
        assert r.status_code == 200
        data = r.json()
        assert "batch_id" in data
        assert isinstance(data["batch_id"], int)
        assert "items" in data
        assert isinstance(data["items"], list)
        assert _get_batch_status(data["batch_id"]) == "pending"
        client.delete(f"/api/emergency/{data['batch_id']}", headers=_admin_headers())


# ── Apply safety ───────────────────────────────────────────────────────────────

class TestEmergencyApplySafety:
    def test_apply_requires_confirm_true(self, client: TestClient):
        """confirm=False must return HTTP 400."""
        _seed_product(9001, "100000")
        preview = client.post("/api/emergency/preview",
                              json={"operation": "pct_increase", "value": 5.0},
                              headers=_admin_headers())
        assert preview.status_code == 200
        batch_id = preview.json()["batch_id"]
        try:
            r = client.post(f"/api/emergency/{batch_id}/apply",
                            json={"confirm": False}, headers=_admin_headers())
            assert r.status_code == 400
            assert "confirm" in r.json().get("detail", "").lower()
        finally:
            client.delete(f"/api/emergency/{batch_id}", headers=_admin_headers())

    def test_cancel_removes_pending_batch(self, client: TestClient):
        """DELETE cancels a pending batch; it no longer appears in the pending list."""
        _seed_product(9001, "100000")
        preview = client.post("/api/emergency/preview",
                              json={"operation": "fixed_increase", "value": 50000.0},
                              headers=_admin_headers())
        assert preview.status_code == 200
        batch_id = preview.json()["batch_id"]
        r = client.delete(f"/api/emergency/{batch_id}", headers=_admin_headers())
        assert r.status_code == 200
        pending = client.get("/api/emergency/pending", headers=_admin_headers())
        assert pending.status_code == 200
        ids = [b["id"] for b in pending.json().get("batches", [])]
        assert batch_id not in ids

    def test_atomic_claim_sequential_double_apply(self, client: TestClient):
        """HIGH 1 R2: Atomic batch claim via UPDATE WHERE status='pending'.
        First apply claims the batch (WC unreachable → items fail → batch ends as 'failed').
        Second apply finds status != 'pending' → UPDATE WHERE rowcount == 0 → HTTP 409."""
        _seed_product(9004, "100000")
        preview = client.post(
            "/api/emergency/preview",
            json={"operation": "pct_increase", "value": 5.0},
            headers=_admin_headers(),
        )
        assert preview.status_code == 200
        batch_id = preview.json()["batch_id"]

        # First apply: WC is unreachable; items fail; endpoint returns 200 with failed > 0.
        r1 = client.post(f"/api/emergency/{batch_id}/apply",
                         json={"confirm": True}, headers=_admin_headers())
        assert r1.status_code == 200

        # Second apply: batch is no longer 'pending' → atomic UPDATE → rowcount 0 → 409.
        r2 = client.post(f"/api/emergency/{batch_id}/apply",
                         json={"confirm": True}, headers=_admin_headers())
        assert r2.status_code == 409

    def test_stale_item_not_applied(self, client: TestClient):
        """HIGH 2: Item whose cached price changed since preview is marked stale, not written."""
        _seed_product(9002, "100000")
        preview = client.post("/api/emergency/preview",
                              json={"operation": "pct_increase", "value": 10.0},
                              headers=_admin_headers())
        assert preview.status_code == 200
        batch_id = preview.json()["batch_id"]
        # Mutate the cached price after preview was taken
        _update_cached_price(9002, "999999")
        r = client.post(f"/api/emergency/{batch_id}/apply",
                        json={"confirm": True}, headers=_admin_headers())
        assert r.status_code == 200
        data = r.json()
        assert data["stale"] >= 1, "Expected at least one stale item"
        assert data["applied"] == 0, "Stale items must not be written to WooCommerce"
        status = _get_batch_status(batch_id)
        assert status != "applied", f"Batch must not be 'applied' when nothing succeeded; got '{status}'"

    def test_batch_status_not_applied_when_all_fail(self, client: TestClient):
        """MEDIUM 1 R1: Batch is marked 'failed' when all items fail (WC unreachable in tests)."""
        _seed_product(9003, "100000")
        preview = client.post("/api/emergency/preview",
                              json={"operation": "pct_increase", "value": 5.0},
                              headers=_admin_headers())
        assert preview.status_code == 200
        batch_id = preview.json()["batch_id"]
        r = client.post(f"/api/emergency/{batch_id}/apply",
                        json={"confirm": True}, headers=_admin_headers())
        assert r.status_code == 200
        status = _get_batch_status(batch_id)
        assert status != "applied", f"Batch must not be 'applied' when WC writes fail; got '{status}'"
        assert status in ("failed", "partially_failed"), f"Unexpected batch status: '{status}'"

    def test_needs_reconcile_visible_in_pending_list(self, client: TestClient):
        """LOW R2: needs_reconcile batches must appear in /api/emergency/pending for operator review."""
        _seed_product(9020, "100000")
        preview = client.post(
            "/api/emergency/preview",
            json={"operation": "pct_increase", "value": 5.0},
            headers=_admin_headers(),
        )
        assert preview.status_code == 200
        batch_id = preview.json()["batch_id"]
        _force_batch_status(batch_id, "needs_reconcile")

        pending = client.get("/api/emergency/pending", headers=_admin_headers())
        assert pending.status_code == 200
        ids = [b["id"] for b in pending.json().get("batches", [])]
        assert batch_id in ids, f"needs_reconcile batch {batch_id} not in pending list; got {ids}"

        _force_batch_status(batch_id, "cancelled")

    def test_partially_failed_visible_in_pending_list(self, client: TestClient):
        """Final Cleanup: partially_failed batches must appear in /api/emergency/pending for operator attention."""
        _seed_product(9021, "100000")
        preview = client.post(
            "/api/emergency/preview",
            json={"operation": "pct_increase", "value": 5.0, "product_ids": [9021]},
            headers=_admin_headers(),
        )
        assert preview.status_code == 200
        batch_id = preview.json()["batch_id"]
        _force_batch_status(batch_id, "partially_failed")

        pending = client.get("/api/emergency/pending", headers=_admin_headers())
        assert pending.status_code == 200
        ids = [b["id"] for b in pending.json().get("batches", [])]
        assert batch_id in ids, f"partially_failed batch {batch_id} not in pending list; got {ids}"

        _force_batch_status(batch_id, "cancelled")

    def test_concurrent_claim_two_sessions(self, client: TestClient):
        """HIGH 1 R2: Two independent DB sessions racing to claim — exactly one wins.
        Directly verifies the atomic UPDATE WHERE status='pending' mechanism at the DB layer."""
        _seed_product(9030, "100000")
        preview = client.post(
            "/api/emergency/preview",
            json={"operation": "pct_increase", "value": 5.0, "product_ids": [9030]},
            headers=_admin_headers(),
        )
        assert preview.status_code == 200
        batch_id = preview.json()["batch_id"]

        db1 = SessionLocal()
        db2 = SessionLocal()
        try:
            # Session 1 wins the claim
            r1 = db1.execute(
                sa_update_direct(EmergencyBatch)
                .where(EmergencyBatch.id == batch_id, EmergencyBatch.status == "pending")
                .values(status="applying")
            )
            db1.commit()
            assert r1.rowcount == 1, "First session must win the atomic claim"

            # Session 2 attempts to claim the same batch — it is now 'applying'
            r2 = db2.execute(
                sa_update_direct(EmergencyBatch)
                .where(EmergencyBatch.id == batch_id, EmergencyBatch.status == "pending")
                .values(status="applying")
            )
            db2.commit()
            assert r2.rowcount == 0, "Second session must lose the race (batch no longer 'pending')"
        finally:
            db1.close()
            db2.close()

    def test_stale_check_price_normalized_equal(self, client: TestClient):
        """LOW R2 / MEDIUM 1 R2: '100000' and '100000.00' are numerically equal — must not be stale."""
        _seed_product(9031, "100000")
        preview = client.post(
            "/api/emergency/preview",
            json={"operation": "pct_increase", "value": 10.0, "product_ids": [9031]},
            headers=_admin_headers(),
        )
        assert preview.status_code == 200
        batch_id = preview.json()["batch_id"]
        # item.old_price = "100000"; update cache to "100000.00" — numerically same, different string
        _update_cached_price(9031, "100000.00")
        r = client.post(f"/api/emergency/{batch_id}/apply",
                        json={"confirm": True}, headers=_admin_headers())
        assert r.status_code == 200
        data = r.json()
        assert data["stale"] == 0, f"'100000' and '100000.00' must not be stale; got {data}"


# ── HIGH 2 R2 + MEDIUM 1 R2: WC success durability ───────────────────────────

class TestEmergencyDurability:
    """Verifies the three-checkpoint durability contract for emergency_apply.

    Checkpoint A (item=applying)     — committed BEFORE WC write
    Checkpoint B (item=wc_succeeded) — committed immediately AFTER WC write
    Checkpoint C (item=applied)      — committed after cache + ChangeHistory finalized
    If B exists but C fails: item → needs_reconcile (WC updated; DB needs manual reconciliation)
    """

    def test_normal_success_creates_history_and_updates_cache(self, client: TestClient):
        """MEDIUM 1 R2: Successful WC write → ProductCache updated + ChangeHistory record created."""
        wc_id = 9011
        _seed_product(wc_id, "100000")
        preview = client.post(
            "/api/emergency/preview",
            json={"operation": "pct_increase", "value": 10.0, "product_ids": [wc_id]},
            headers=_admin_headers(),
        )
        assert preview.status_code == 200
        batch_id = preview.json()["batch_id"]

        with patch("app.main.update_single_product", new=AsyncMock(return_value=None)):
            r = client.post(f"/api/emergency/{batch_id}/apply",
                            json={"confirm": True}, headers=_admin_headers())

        assert r.status_code == 200
        data = r.json()
        assert data["applied"] == 1, f"Expected applied=1; got {data}"
        assert data["failed"] == 0
        assert data.get("reconcile", 0) == 0

        db = SessionLocal()
        try:
            # Cache must reflect the new price (100000 * 1.10 = 110000, exact 10k multiple)
            cache = db.query(ProductCache).filter(ProductCache.wc_id == wc_id).first()
            assert cache is not None
            assert cache.regular_price == "110000", f"Cache not updated: got '{cache.regular_price}'"

            # ChangeHistory must have a record for this emergency batch
            history = db.query(ChangeHistory).filter(
                ChangeHistory.product_id == wc_id,
                ChangeHistory.source == "emergency",
            ).first()
            assert history is not None, "ChangeHistory record missing after successful apply"
            assert history.new_price == "110000"
        finally:
            db.close()

    def test_checkpoint_b_commit_fail_marks_needs_reconcile_not_failed(self, client: TestClient):
        """HIGH R3: wc_write_succeeded flag prevents misclassifying a successful WC write as 'failed'.
        Checkpoint B is the commit of item.status='wc_succeeded' after WC returns OK.
        If that specific commit raises, the outer handler must use needs_reconcile, never failed."""
        wc_id = 9012
        _seed_product(wc_id, "100000")
        preview = client.post(
            "/api/emergency/preview",
            json={"operation": "pct_increase", "value": 10.0, "product_ids": [wc_id]},
            headers=_admin_headers(),
        )
        assert preview.status_code == 200
        batch_id = preview.json()["batch_id"]

        call_count = {"n": 0}
        original_commit = SASession.commit

        def flaky_commit(self_session: SASession):
            call_count["n"] += 1
            # For one item, no stale items:
            #   commit #1 = atomic claim
            #   commit #2 = _audit("emergency_apply_started") — own session, still patched
            #   commit #3 = checkpoint A
            #   commit #4 = checkpoint B ← fail this
            #   commit #5 = recovery (needs_reconcile) — must succeed
            if call_count["n"] == 4:
                raise Exception("simulated checkpoint B commit failure")
            return original_commit(self_session)

        with (
            patch("app.main.update_single_product", new=AsyncMock(return_value=None)),
            patch.object(SASession, "commit", flaky_commit),
        ):
            r = client.post(f"/api/emergency/{batch_id}/apply",
                            json={"confirm": True}, headers=_admin_headers())

        assert r.status_code == 200
        data = r.json()
        assert data.get("reconcile", 0) >= 1, f"Expected reconcile>=1 (not failed); got {data}"
        assert data["failed"] == 0, f"WC write succeeded — must not be 'failed'; got {data}"

        db = SessionLocal()
        try:
            item = db.query(EmergencyItem).filter(EmergencyItem.batch_id == batch_id).first()
            assert item is not None
            assert item.status == "needs_reconcile", f"Item must be 'needs_reconcile'; got '{item.status}'"
        finally:
            db.close()

    def test_wc_success_db_fail_marks_needs_reconcile(self, client: TestClient):
        """HIGH 2 R2 + MEDIUM 1 R2: WC write succeeded but cache/history commit failed.
        Item must be needs_reconcile with wc_success_at set; batch must be needs_reconcile."""
        wc_id = 9010
        _seed_product(wc_id, "100000")
        preview = client.post(
            "/api/emergency/preview",
            json={"operation": "pct_increase", "value": 10.0, "product_ids": [wc_id]},
            headers=_admin_headers(),
        )
        assert preview.status_code == 200
        batch_id = preview.json()["batch_id"]

        with (
            patch("app.main.update_single_product", new=AsyncMock(return_value=None)),
            patch("app.main.patch_cached_product", side_effect=Exception("simulated DB failure")),
        ):
            r = client.post(f"/api/emergency/{batch_id}/apply",
                            json={"confirm": True}, headers=_admin_headers())

        assert r.status_code == 200
        data = r.json()
        assert data.get("reconcile", 0) == 1, f"Expected reconcile=1; got {data}"
        assert data["applied"] == 0

        db = SessionLocal()
        try:
            batch = db.get(EmergencyBatch, batch_id)
            assert batch.status == "needs_reconcile", f"Batch status '{batch.status}', expected 'needs_reconcile'"

            item = db.query(EmergencyItem).filter(EmergencyItem.batch_id == batch_id).first()
            assert item is not None
            assert item.status == "needs_reconcile", f"Item status '{item.status}', expected 'needs_reconcile'"
            assert item.wc_success_at is not None, "wc_success_at must be non-null when WC write succeeded"
        finally:
            db.close()


# ── Audit history ──────────────────────────────────────────────────────────────

class TestAuditHistory:
    def test_audit_history_returns_changes_key(self, client: TestClient):
        """MEDIUM 4: Response uses 'changes' key (not 'items')."""
        r = client.get("/api/audit/history?limit=10", headers=_admin_headers())
        assert r.status_code == 200
        data = r.json()
        assert "changes" in data, f"Expected 'changes' key; got keys: {list(data.keys())}"
        assert "total" in data
        assert isinstance(data["changes"], list)

    def test_undo_requires_confirm_true(self, client: TestClient):
        """confirm=False must be rejected."""
        r = client.post("/api/audit/undo",
                        json={"change_id": 1, "confirm": False},
                        headers=_admin_headers())
        assert r.status_code in (400, 422)
        if r.status_code == 400:
            assert "confirm" in r.json().get("detail", "").lower()

    def test_undo_nonexistent_change(self, client: TestClient):
        """confirm=True but nonexistent change_id returns 400 or 404."""
        r = client.post("/api/audit/undo",
                        json={"change_id": 999999, "confirm": True},
                        headers=_admin_headers())
        assert r.status_code in (400, 404)
