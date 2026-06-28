"""Integration tests for /api/auth/* endpoints (BU2)."""

from __future__ import annotations

import pytest
from app.beta.auth.rate_limiter import clear_all


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    clear_all()
    yield
    clear_all()


# ── Login ─────────────────────────────────────────────────────────────────────

class TestLogin:
    def test_success_returns_tokens(self, client, admin_user):
        r = client.post("/api/auth/login", json={"username": "testadmin", "password": "correct-horse-battery"})
        assert r.status_code == 200
        data = r.json()
        assert "token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    def test_wrong_password_returns_401(self, client, admin_user):
        r = client.post("/api/auth/login", json={"username": "testadmin", "password": "wrong"})
        assert r.status_code == 401

    def test_unknown_user_returns_401(self, client):
        r = client.post("/api/auth/login", json={"username": "ghost", "password": "anything"})
        assert r.status_code == 401

    def test_401_does_not_leak_user_existence(self, client, admin_user):
        r_existing = client.post("/api/auth/login", json={"username": "testadmin", "password": "wrong"})
        r_missing = client.post("/api/auth/login", json={"username": "nobody", "password": "wrong"})
        assert r_existing.json()["detail"] == r_missing.json()["detail"]

    def test_rate_limiting_after_five_attempts(self, client, admin_user):
        for _ in range(5):
            client.post("/api/auth/login", json={"username": "testadmin", "password": "wrong"})
        r = client.post("/api/auth/login", json={"username": "testadmin", "password": "wrong"})
        assert r.status_code == 429

    def test_audit_event_on_success(self, client, admin_user, db):
        client.post("/api/auth/login", json={"username": "testadmin", "password": "correct-horse-battery"})
        from app.beta.auth.models import BetaLoginAudit
        events = db.query(BetaLoginAudit).filter(BetaLoginAudit.event == "login_success").all()
        assert len(events) == 1
        assert events[0].username == "testadmin"

    def test_audit_event_on_failure(self, client, admin_user, db):
        client.post("/api/auth/login", json={"username": "testadmin", "password": "wrong"})
        from app.beta.auth.models import BetaLoginAudit
        events = db.query(BetaLoginAudit).filter(BetaLoginAudit.event == "login_failed").all()
        assert len(events) == 1


# ── /me ───────────────────────────────────────────────────────────────────────

class TestMe:
    def _login(self, client, admin_user):
        r = client.post("/api/auth/login", json={"username": "testadmin", "password": "correct-horse-battery"})
        return r.json()["token"]

    def test_me_returns_user_info(self, client, admin_user):
        token = self._login(client, admin_user)
        r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        data = r.json()
        assert data["username"] == "testadmin"
        assert data["role"] == "admin"
        assert data["is_admin"] is True
        assert data["is_super_admin"] is False

    def test_me_admin_has_full_permissions(self, client, admin_user):
        token = self._login(client, admin_user)
        r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        perms = r.json()["permissions"]
        assert perms["can_access_site"] is True
        assert perms["can_fetch"] is True
        assert perms["can_view_logs"] is True
        assert perms["can_view_settings"] is True

    def test_me_unauthenticated_returns_401(self, client):
        r = client.get("/api/auth/me")
        assert r.status_code == 401

    def test_me_invalid_token_returns_401(self, client):
        r = client.get("/api/auth/me", headers={"Authorization": "Bearer not.a.token"})
        assert r.status_code == 401

    def test_me_does_not_expose_password(self, client, admin_user):
        token = self._login(client, admin_user)
        r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        body = r.text
        assert "hashed_password" not in body
        assert "password" not in body


# ── Refresh ───────────────────────────────────────────────────────────────────

class TestRefresh:
    def _login_tokens(self, client, admin_user):
        r = client.post("/api/auth/login", json={"username": "testadmin", "password": "correct-horse-battery"})
        d = r.json()
        return d["token"], d["refresh_token"]

    def test_refresh_returns_new_tokens(self, client, admin_user):
        _, rt = self._login_tokens(client, admin_user)
        r = client.post("/api/auth/refresh", json={"refresh_token": rt})
        assert r.status_code == 200
        data = r.json()
        assert "token" in data
        assert "refresh_token" in data

    def test_new_access_token_works(self, client, admin_user):
        _, rt = self._login_tokens(client, admin_user)
        new_tokens = client.post("/api/auth/refresh", json={"refresh_token": rt}).json()
        r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {new_tokens['token']}"})
        assert r.status_code == 200

    def test_old_refresh_token_is_revoked_after_rotation(self, client, admin_user):
        _, rt = self._login_tokens(client, admin_user)
        client.post("/api/auth/refresh", json={"refresh_token": rt})
        # Old token must no longer work
        r = client.post("/api/auth/refresh", json={"refresh_token": rt})
        assert r.status_code == 401

    def test_invalid_refresh_token_returns_401(self, client, admin_user):
        r = client.post("/api/auth/refresh", json={"refresh_token": "garbage"})
        assert r.status_code == 401

    def test_audit_event_on_refresh(self, client, admin_user, db):
        _, rt = self._login_tokens(client, admin_user)
        client.post("/api/auth/refresh", json={"refresh_token": rt})
        from app.beta.auth.models import BetaLoginAudit
        events = db.query(BetaLoginAudit).filter(BetaLoginAudit.event == "token_refresh").all()
        assert len(events) == 1


# ── Logout ────────────────────────────────────────────────────────────────────

class TestLogout:
    def _login_tokens(self, client, admin_user):
        r = client.post("/api/auth/login", json={"username": "testadmin", "password": "correct-horse-battery"})
        d = r.json()
        return d["token"], d["refresh_token"]

    def test_logout_returns_204(self, client, admin_user):
        at, rt = self._login_tokens(client, admin_user)
        r = client.post(
            "/api/auth/logout",
            json={"refresh_token": rt},
            headers={"Authorization": f"Bearer {at}"},
        )
        assert r.status_code == 204

    def test_refresh_fails_after_logout(self, client, admin_user):
        at, rt = self._login_tokens(client, admin_user)
        client.post(
            "/api/auth/logout",
            json={"refresh_token": rt},
            headers={"Authorization": f"Bearer {at}"},
        )
        r = client.post("/api/auth/refresh", json={"refresh_token": rt})
        assert r.status_code == 401

    def test_logout_without_token_returns_401(self, client, admin_user):
        _, rt = self._login_tokens(client, admin_user)
        r = client.post("/api/auth/logout", json={"refresh_token": rt})
        assert r.status_code == 401

    def test_audit_event_on_logout(self, client, admin_user, db):
        at, rt = self._login_tokens(client, admin_user)
        client.post(
            "/api/auth/logout",
            json={"refresh_token": rt},
            headers={"Authorization": f"Bearer {at}"},
        )
        from app.beta.auth.models import BetaLoginAudit
        events = db.query(BetaLoginAudit).filter(BetaLoginAudit.event == "logout").all()
        assert len(events) == 1


# ── Viewer role ───────────────────────────────────────────────────────────────

class TestViewerRole:
    def test_viewer_permissions_are_limited(self, client, db):
        from app.beta.auth.password import hash_password
        from app.beta.auth.repository import create_user

        create_user(db, username="viewer1", hashed_password=hash_password("viewpass"), role="viewer")
        r = client.post("/api/auth/login", json={"username": "viewer1", "password": "viewpass"})
        token = r.json()["token"]
        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
        assert me["is_admin"] is False
        assert me["permissions"].get("can_access_site") is True
        assert me["permissions"].get("can_fetch") is not True
