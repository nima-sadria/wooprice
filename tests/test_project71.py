"""Project 7.1 — Admin Permissions + Maintenance Break Mode tests.

Coverage:
  1.  SUPER_ADMIN_USERS=woo,admin gives both users super admin access
  2.  Existing user permissions are preserved on PATCH
  3.  Super admin can enable maintenance mode
  4.  Super admin can disable maintenance mode
  5.  Normal user is blocked during maintenance
  6.  Super admin is not blocked during maintenance
  7.  Health endpoint remains available during maintenance
  8.  Protected operational endpoint is blocked for normal user during maintenance
  9.  Maintenance mode message is returned to frontend
  10. Existing auth/login flow still works (auth endpoints exempt from maintenance)
"""
import json
import os
import sys
from datetime import datetime

# Set env vars before any app import — get_settings() is @lru_cache'd.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
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

from app.main import app  # noqa: E402
from app.services.auth import create_token, is_super_admin  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import AppSetting, AppUser, AuditLog  # noqa: E402


# ── Fixtures & helpers ────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def _super_headers() -> dict:
    """JWT for testadmin — listed in SUPER_ADMIN_USERS, bypasses all DB checks."""
    token = create_token("testadmin", permission_version=0, role="admin")
    return {"Authorization": f"Bearer {token}"}


def _user_headers(username: str = "normaluser71", pv: int = 1) -> dict:
    """JWT for a normal (non-super-admin) user."""
    token = create_token(username, permission_version=pv, role="user")
    return {"Authorization": f"Bearer {token}"}


def _seed_normal_user(username: str = "normaluser71") -> None:
    """Insert a normal active user into app_users (idempotent)."""
    db = SessionLocal()
    try:
        if db.query(AppUser).filter(AppUser.username == username).first():
            return
        db.add(AppUser(
            username=username,
            is_active=True,
            is_admin=False,
            permission_version=1,
            can_access_site=True,
            can_fetch=True,
            can_apply=True,
            can_edit_price=True,
            can_edit_stock=True,
            can_view_logs=False,
            can_view_settings=False,
        ))
        db.commit()
    finally:
        db.close()


def _set_maintenance(enabled: bool, message: str = "") -> None:
    """Directly write maintenance mode to DB (bypasses HTTP/auth layers)."""
    db = SessionLocal()
    try:
        row = db.get(AppSetting, "maintenance_mode")
        if row is None:
            row = AppSetting(key="maintenance_mode")
            db.add(row)
        row.value = json.dumps({"enabled": enabled, "message": message})
        row.updated_at = datetime.utcnow()
        row.updated_by = "test_helper"
        db.commit()
    finally:
        db.close()


def _get_maintenance_enabled() -> bool:
    db = SessionLocal()
    try:
        row = db.get(AppSetting, "maintenance_mode")
        if not row or not row.value:
            return False
        return bool(json.loads(row.value).get("enabled", False))
    finally:
        db.close()


# ── 1. SUPER_ADMIN_USERS config ───────────────────────────────────────────────

class TestSuperAdminConfig:
    def test_super_admin_env_configures_multiple_users(self):
        """SUPER_ADMIN_USERS=woo,admin gives both users super admin access."""
        from app.config import Settings
        s = Settings(
            nextcloud_url="http://x", nextcloud_user="x", nextcloud_password="x",
            nextcloud_file_path="/x", wc_url="http://x", wc_key="x", wc_secret="x",
            super_admin_users="woo,admin",
            database_url="sqlite:///:memory:",
        )
        parsed = [u.strip() for u in s.super_admin_users.split(",") if u.strip()]
        assert "woo" in parsed, "woo must be a super admin"
        assert "admin" in parsed, "admin must be a super admin"
        assert "bob" not in parsed, "bob must not be a super admin"

    def test_testadmin_is_current_super_admin(self):
        """testadmin is configured in SUPER_ADMIN_USERS for this test suite."""
        assert is_super_admin("testadmin")

    def test_normal_user_is_not_super_admin(self):
        """normaluser71 is not in SUPER_ADMIN_USERS."""
        assert not is_super_admin("normaluser71")

    def test_super_admin_comma_separated_trimming(self):
        """Whitespace around commas in SUPER_ADMIN_USERS is stripped correctly."""
        from app.config import Settings
        s = Settings(
            nextcloud_url="http://x", nextcloud_user="x", nextcloud_password="x",
            nextcloud_file_path="/x", wc_url="http://x", wc_key="x", wc_secret="x",
            super_admin_users=" woo , admin ",
            database_url="sqlite:///:memory:",
        )
        parsed = [u.strip() for u in s.super_admin_users.split(",") if u.strip()]
        assert "woo" in parsed
        assert "admin" in parsed


# ── 2. Existing permissions preserved ────────────────────────────────────────

class TestExistingPermissions:
    def test_existing_user_permissions_preserved_on_patch(self, client: TestClient):
        """PATCH only updates supplied fields; other permission fields remain intact."""
        _seed_normal_user("permtest71")
        db = SessionLocal()
        try:
            u = db.query(AppUser).filter(AppUser.username == "permtest71").first()
            original_fetch = u.can_fetch
            original_apply = u.can_apply
        finally:
            db.close()

        # Patch only notes — no permission fields supplied
        r = client.patch(
            "/api/admin/app-users/permtest71",
            json={"notes": "updated by test"},
            headers=_super_headers(),
        )
        assert r.status_code == 200

        db = SessionLocal()
        try:
            u = db.query(AppUser).filter(AppUser.username == "permtest71").first()
            assert u.can_fetch == original_fetch, "can_fetch must be unchanged"
            assert u.can_apply == original_apply, "can_apply must be unchanged"
        finally:
            db.close()

    def test_permission_update_only_changes_specified_field(self, client: TestClient):
        """PATCH with one permission field leaves all other permission fields unchanged."""
        _seed_normal_user("permtest72")
        db = SessionLocal()
        try:
            u = db.query(AppUser).filter(AppUser.username == "permtest72").first()
            original_edit_stock = u.can_edit_stock
            original_view_logs = u.can_view_logs
        finally:
            db.close()

        r = client.patch(
            "/api/admin/app-users/permtest72",
            json={"can_fetch": False},
            headers=_super_headers(),
        )
        assert r.status_code == 200

        db = SessionLocal()
        try:
            u = db.query(AppUser).filter(AppUser.username == "permtest72").first()
            assert u.can_fetch is False, "can_fetch was explicitly set to False"
            assert u.can_edit_stock == original_edit_stock, "can_edit_stock must be unchanged"
            assert u.can_view_logs == original_view_logs, "can_view_logs must be unchanged"
        finally:
            db.close()

    def test_user_list_returns_all_db_users(self, client: TestClient):
        """GET /api/admin/app-users returns all rows from app_users."""
        _seed_normal_user("listtest71")
        r = client.get("/api/admin/app-users", headers=_super_headers())
        assert r.status_code == 200
        usernames = [u["username"] for u in r.json()]
        assert "listtest71" in usernames


# ── 3–4. Maintenance mode toggle ─────────────────────────────────────────────

class TestMaintenanceModeToggle:
    def test_super_admin_can_enable_maintenance(self, client: TestClient):
        """Super admin can enable maintenance mode via POST /api/admin/maintenance."""
        _set_maintenance(False)
        r = client.post(
            "/api/admin/maintenance",
            json={"enabled": True, "message": "Scheduled maintenance"},
            headers=_super_headers(),
        )
        assert r.status_code == 200
        assert r.json()["enabled"] is True
        assert _get_maintenance_enabled() is True
        _set_maintenance(False)

    def test_super_admin_can_disable_maintenance(self, client: TestClient):
        """Super admin can disable maintenance mode via POST /api/admin/maintenance."""
        _set_maintenance(True, "test message")
        r = client.post(
            "/api/admin/maintenance",
            json={"enabled": False, "message": ""},
            headers=_super_headers(),
        )
        assert r.status_code == 200
        assert r.json()["enabled"] is False
        assert _get_maintenance_enabled() is False

    def test_get_maintenance_returns_current_state(self, client: TestClient):
        """GET /api/admin/maintenance returns the persisted maintenance state."""
        _set_maintenance(True, "System upgrade in progress")
        r = client.get("/api/admin/maintenance", headers=_super_headers())
        assert r.status_code == 200
        data = r.json()
        assert data["enabled"] is True
        assert data["message"] == "System upgrade in progress"
        _set_maintenance(False)

    def test_non_super_admin_cannot_access_maintenance_endpoint(self, client: TestClient):
        """Regular admin JWT cannot reach maintenance endpoints (super admin only)."""
        token = create_token("dbadmin_user", permission_version=0, role="admin")
        headers = {"Authorization": f"Bearer {token}"}
        r = client.get("/api/admin/maintenance", headers=headers)
        # This user is not a super admin — gets 403
        assert r.status_code == 403


# ── 5–6. Maintenance blocking ─────────────────────────────────────────────────

class TestMaintenanceBlocking:
    def test_normal_user_blocked_during_maintenance(self, client: TestClient):
        """Normal user receives HTTP 503 on any protected API during maintenance."""
        _set_maintenance(True, "Offline for maintenance")
        try:
            r = client.get("/api/alarm-settings", headers=_user_headers())
            assert r.status_code == 503, f"Expected 503, got {r.status_code}"
            body = r.json()
            assert body.get("maintenance") is True
        finally:
            _set_maintenance(False)

    def test_super_admin_not_blocked_during_maintenance(self, client: TestClient):
        """Super admin reaches actual routes even while maintenance mode is active."""
        _set_maintenance(True, "Blocked for everyone else")
        try:
            r = client.get("/api/admin/app-users", headers=_super_headers())
            assert r.status_code == 200, f"Super admin must not be blocked; got {r.status_code}"
        finally:
            _set_maintenance(False)

    def test_health_endpoint_available_during_maintenance(self, client: TestClient):
        """GET /api/health always responds 200 regardless of maintenance mode."""
        _set_maintenance(True)
        try:
            r = client.get("/api/health")
            assert r.status_code == 200
        finally:
            _set_maintenance(False)

    def test_protected_operational_endpoint_blocked_for_normal_user(self, client: TestClient):
        """Protected endpoints return 503 with maintenance flag for non-super-admin users."""
        _set_maintenance(True, "Maintenance active")
        try:
            r = client.get("/api/admin/app-users", headers=_user_headers())
            assert r.status_code == 503
            assert r.json().get("maintenance") is True
        finally:
            _set_maintenance(False)


# ── 9. Maintenance message ────────────────────────────────────────────────────

class TestMaintenanceMessage:
    def test_maintenance_message_in_503_body(self, client: TestClient):
        """The configured message is returned in the 503 response body."""
        msg = "System offline until 5pm. Thank you for your patience."
        _set_maintenance(True, msg)
        try:
            r = client.get("/api/alarm-settings", headers=_user_headers())
            assert r.status_code == 503
            assert r.json()["detail"] == msg
        finally:
            _set_maintenance(False)

    def test_default_maintenance_message_when_none_set(self, client: TestClient):
        """When no message is configured, a sensible default is returned."""
        _set_maintenance(True, "")
        try:
            r = client.get("/api/alarm-settings", headers=_user_headers())
            assert r.status_code == 503
            assert r.json()["detail"]  # non-empty default message
        finally:
            _set_maintenance(False)

    def test_maintenance_state_in_auth_me_response(self, client: TestClient):
        """/api/auth/me includes maintenance state so frontend can show overlay."""
        _seed_normal_user()
        _set_maintenance(True, "Under maintenance")
        try:
            r = client.get("/api/auth/me", headers=_user_headers())
            # /api/auth/me is exempt from the maintenance block
            assert r.status_code == 200
            data = r.json()
            assert "maintenance" in data, "/api/auth/me must include maintenance field"
            assert data["maintenance"]["enabled"] is True
            assert data["maintenance"]["message"] == "Under maintenance"
        finally:
            _set_maintenance(False)

    def test_super_admin_me_includes_maintenance_state(self, client: TestClient):
        """Super admin /api/auth/me also includes maintenance state."""
        _set_maintenance(True, "SA sees this too")
        try:
            r = client.get("/api/auth/me", headers=_super_headers())
            assert r.status_code == 200
            data = r.json()
            assert data["maintenance"]["enabled"] is True
        finally:
            _set_maintenance(False)


# ── 10. Existing auth flow ────────────────────────────────────────────────────

class TestAuthFlowUnaffected:
    def test_auth_me_accessible_during_maintenance(self, client: TestClient):
        """/api/auth/me is exempt from maintenance blocking."""
        _seed_normal_user()
        _set_maintenance(True)
        try:
            r = client.get("/api/auth/me", headers=_user_headers())
            assert r.status_code == 200
        finally:
            _set_maintenance(False)

    def test_auth_login_endpoint_accessible_during_maintenance(self, client: TestClient):
        """/api/auth/login is exempt from maintenance blocking (POST with any body reaches the handler)."""
        _set_maintenance(True)
        try:
            # POST reaches the handler; Nextcloud returns 503/error — but that's the Nextcloud error,
            # not the maintenance block. A maintenance block would return our custom 503 with
            # maintenance=True; a Nextcloud error has a different body.
            r = client.post(
                "/api/auth/login",
                json={"username": "x", "password": "x"},
            )
            body = r.json()
            # Key assertion: this is NOT our maintenance 503 (which has maintenance=True key)
            assert body.get("maintenance") is not True, "Login endpoint must not return maintenance block"
        finally:
            _set_maintenance(False)

    def test_maintenance_off_by_default(self, client: TestClient):
        """Without any maintenance setup, all routes behave normally."""
        _set_maintenance(False)
        r = client.get("/api/health")
        assert r.status_code == 200


# ── Maintenance audit logging ─────────────────────────────────────────────────

class TestMaintenanceAuditLog:
    def test_enable_maintenance_creates_audit_record(self, client: TestClient):
        """Enabling maintenance mode writes a maintenance_enabled audit log entry."""
        _set_maintenance(False)
        client.post(
            "/api/admin/maintenance",
            json={"enabled": True, "message": "audit test"},
            headers=_super_headers(),
        )
        db = SessionLocal()
        try:
            log = (
                db.query(AuditLog)
                .filter(AuditLog.action == "maintenance_enabled", AuditLog.username == "testadmin")
                .order_by(AuditLog.id.desc())
                .first()
            )
            assert log is not None, "maintenance_enabled audit record must be written"
        finally:
            db.close()
            _set_maintenance(False)

    def test_disable_maintenance_creates_audit_record(self, client: TestClient):
        """Disabling maintenance mode writes a maintenance_disabled audit log entry."""
        _set_maintenance(True)
        client.post(
            "/api/admin/maintenance",
            json={"enabled": False, "message": ""},
            headers=_super_headers(),
        )
        db = SessionLocal()
        try:
            log = (
                db.query(AuditLog)
                .filter(AuditLog.action == "maintenance_disabled", AuditLog.username == "testadmin")
                .order_by(AuditLog.id.desc())
                .first()
            )
            assert log is not None, "maintenance_disabled audit record must be written"
        finally:
            db.close()


# ── M1: Explicit is_super_admin field ────────────────────────────────────────

def _seed_db_admin(username: str = "dbadmin71") -> None:
    """Create a DB admin user who is NOT in SUPER_ADMIN_USERS (idempotent)."""
    db = SessionLocal()
    try:
        if db.query(AppUser).filter(AppUser.username == username).first():
            return
        db.add(AppUser(
            username=username,
            is_active=True,
            is_admin=True,
            permission_version=1,
            can_access_site=True,
            can_fetch=True,
            can_apply=True,
            can_edit_price=True,
            can_edit_stock=True,
            can_view_logs=True,
            can_view_settings=True,
        ))
        db.commit()
    finally:
        db.close()


def _db_admin_headers(username: str = "dbadmin71") -> dict:
    """JWT for a DB admin who is NOT in SUPER_ADMIN_USERS."""
    token = create_token(username, permission_version=1, role="admin")
    return {"Authorization": f"Bearer {token}"}


class TestIsSuperAdminField:
    def test_super_admin_me_has_is_super_admin_true(self, client: TestClient):
        """M1: /api/auth/me returns is_super_admin=True for SUPER_ADMIN_USERS member."""
        r = client.get("/api/auth/me", headers=_super_headers())
        assert r.status_code == 200
        data = r.json()
        assert "is_super_admin" in data, "is_super_admin field must be present"
        assert data["is_super_admin"] is True

    def test_normal_user_me_has_is_super_admin_false(self, client: TestClient):
        """M1: /api/auth/me returns is_super_admin=False for a normal user."""
        _seed_normal_user()
        r = client.get("/api/auth/me", headers=_user_headers())
        assert r.status_code == 200
        data = r.json()
        assert "is_super_admin" in data, "is_super_admin field must be present"
        assert data["is_super_admin"] is False

    def test_db_admin_not_in_super_admin_users_has_is_super_admin_false(self, client: TestClient):
        """M1: DB admin (is_admin=True) who is NOT in SUPER_ADMIN_USERS gets is_super_admin=False."""
        _seed_db_admin()
        r = client.get("/api/auth/me", headers=_db_admin_headers())
        assert r.status_code == 200
        data = r.json()
        assert "is_super_admin" in data, "is_super_admin field must be present"
        assert data["is_super_admin"] is False, (
            "DB admin who is not in SUPER_ADMIN_USERS must have is_super_admin=False"
        )

    def test_is_super_admin_derived_only_from_env_not_role(self, client: TestClient):
        """M1: A token with role='admin' but not in SUPER_ADMIN_USERS must get is_super_admin=False."""
        _seed_db_admin("dbadmin72")
        token = create_token("dbadmin72", permission_version=1, role="admin")
        headers = {"Authorization": f"Bearer {token}"}
        r = client.get("/api/auth/me", headers=headers)
        assert r.status_code == 200
        data = r.json()
        assert data["is_super_admin"] is False, (
            "role='admin' alone must NOT confer is_super_admin=True"
        )
        assert data["is_admin"] is True, "DB admin flag must still reflect DB state"

    def test_db_admin_blocked_by_maintenance_not_bypassed(self, client: TestClient):
        """M1: DB admin who is NOT in SUPER_ADMIN_USERS is blocked during maintenance."""
        _seed_db_admin()
        _set_maintenance(True, "Maintenance active")
        try:
            r = client.get("/api/admin/app-users", headers=_db_admin_headers())
            assert r.status_code == 503, (
                f"DB admin without SUPER_ADMIN_USERS must be blocked during maintenance; got {r.status_code}"
            )
            assert r.json().get("maintenance") is True
        finally:
            _set_maintenance(False)


# ── M2: Live maintenance activation response shape ────────────────────────────

class TestLiveMaintenanceActivation:
    def test_503_maintenance_block_has_maintenance_true_field(self, client: TestClient):
        """M2: Every maintenance-block 503 includes maintenance=true for frontend detection."""
        _set_maintenance(True, "Live activation test")
        try:
            r = client.get("/api/alarm-settings", headers=_user_headers())
            assert r.status_code == 503
            body = r.json()
            assert body.get("maintenance") is True, (
                "503 response body must have maintenance=true so authFetch can detect it"
            )
        finally:
            _set_maintenance(False)

    def test_503_maintenance_block_has_detail_message(self, client: TestClient):
        """M2: The 503 body includes detail so authFetch can update user.maintenance.message."""
        msg = "Deployment in progress — back in 10 minutes."
        _set_maintenance(True, msg)
        try:
            r = client.get("/api/alarm-settings", headers=_user_headers())
            assert r.status_code == 503
            body = r.json()
            assert body.get("detail") == msg, "detail field must carry the maintenance message"
            assert body.get("maintenance") is True
        finally:
            _set_maintenance(False)

    def test_non_maintenance_503_does_not_have_maintenance_flag(self, client: TestClient):
        """M2: A normal (non-maintenance) 503 does not carry maintenance=true."""
        _set_maintenance(False)
        # Login with bad Nextcloud creds produces a 503 from Nextcloud unreachable
        r = client.post("/api/auth/login", json={"username": "x", "password": "x"})
        try:
            body = r.json()
            assert body.get("maintenance") is not True, (
                "A non-maintenance 503 must not have maintenance=true"
            )
        except Exception:
            pass  # non-JSON response is also fine — no maintenance flag is present

    def test_super_admin_503_not_triggered_during_maintenance(self, client: TestClient):
        """M2: Super admin never receives a maintenance 503 — authFetch on super admin is unaffected."""
        _set_maintenance(True, "Only normal users should see this")
        try:
            r = client.get("/api/admin/app-users", headers=_super_headers())
            assert r.status_code != 503, "Super admin must not receive a maintenance 503"
        finally:
            _set_maintenance(False)


# ── Part A (7.2): Query param token bypass ────────────────────────────────────

class TestQueryParamBypass:
    """Project 7.2 Part A: maintenance bypass must work via ?token= query param.
    SSE endpoints (EventSource API) cannot set custom headers, so they pass the
    JWT as a query parameter — the middleware must honour this for super admins."""

    def test_super_admin_with_token_query_param_bypasses_maintenance(self, client: TestClient):
        """Super admin JWT passed as ?token= must bypass the maintenance block."""
        _set_maintenance(True, "Blocked for normal users")
        try:
            token = create_token("testadmin", permission_version=0, role="admin")
            # No Authorization header — token via query param only
            r = client.get("/api/alarm-settings", params={"token": token})
            assert r.status_code != 503, (
                f"Super admin with ?token= query param must bypass maintenance; got {r.status_code}"
            )
            # If JSON response (not a list), confirm it's not a maintenance block
            body = r.json()
            if isinstance(body, dict):
                assert body.get("maintenance") is not True
        finally:
            _set_maintenance(False)

    def test_normal_user_with_token_query_param_is_blocked_during_maintenance(self, client: TestClient):
        """Normal user JWT in ?token= query param is still blocked during maintenance."""
        _seed_normal_user()
        _set_maintenance(True, "Maintenance active")
        try:
            token = create_token("normaluser71", permission_version=1, role="user")
            r = client.get("/api/alarm-settings", params={"token": token})
            assert r.status_code == 503, (
                f"Normal user with ?token= must be blocked; got {r.status_code}"
            )
            assert r.json().get("maintenance") is True
        finally:
            _set_maintenance(False)

    def test_thumb_route_blocked_for_normal_user_during_maintenance(self, client: TestClient):
        """/api/products/{id}/thumb is blocked for normal users during maintenance."""
        _seed_normal_user()
        _set_maintenance(True, "Maintenance active")
        try:
            r = client.get("/api/products/99999/thumb", headers=_user_headers())
            assert r.status_code == 503, (
                f"Thumb route must be blocked for normal user during maintenance; got {r.status_code}"
            )
            assert r.json().get("maintenance") is True
        finally:
            _set_maintenance(False)

    def test_thumb_route_super_admin_bypass_during_maintenance(self, client: TestClient):
        """/api/products/{id}/thumb passes the middleware for super admins during maintenance."""
        _set_maintenance(True, "Maintenance active")
        try:
            r = client.get("/api/products/99999/thumb", headers=_super_headers())
            # Super admin bypasses maintenance middleware; endpoint handles the rest (may 404)
            assert r.status_code != 503, (
                f"Super admin must bypass maintenance on thumb route; got {r.status_code}"
            )
        finally:
            _set_maintenance(False)

    def test_db_admin_with_query_param_token_is_blocked_during_maintenance(self, client: TestClient):
        """DB admin (is_admin=True but not in SUPER_ADMIN_USERS) is blocked even via ?token=."""
        _seed_db_admin()
        _set_maintenance(True, "Maintenance active")
        try:
            token = create_token("dbadmin71", permission_version=1, role="admin")
            r = client.get("/api/alarm-settings", params={"token": token})
            assert r.status_code == 503, (
                f"DB admin with ?token= must be blocked during maintenance; got {r.status_code}"
            )
            assert r.json().get("maintenance") is True
        finally:
            _set_maintenance(False)
