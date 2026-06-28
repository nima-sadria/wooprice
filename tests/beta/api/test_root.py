"""Tests for the Beta root route GET /."""

from fastapi.testclient import TestClient

from app.beta.app import app

client = TestClient(app)


class TestRootRoute:
    def test_root_returns_200(self):
        response = client.get("/")
        assert response.status_code == 200

    def test_root_content_type_html(self):
        response = client.get("/")
        assert "text/html" in response.headers["content-type"]

    def test_root_contains_wooprice_beta(self):
        response = client.get("/")
        assert "WooPrice Beta" in response.text

    def test_root_contains_environment(self):
        response = client.get("/")
        assert "beta" in response.text

    def test_root_contains_version(self):
        response = client.get("/")
        assert "0.1.0-dev" in response.text

    def test_root_contains_health_path(self):
        response = client.get("/")
        assert "/api/health" in response.text

    def test_root_contains_ui_not_implemented_note(self):
        response = client.get("/")
        text = response.text.lower()
        assert "ui" in text or "not yet implemented" in text or "not implemented" in text

    def test_root_does_not_expose_secrets(self):
        response = client.get("/")
        text = response.text.upper()
        for secret_key in (
            "JWT_SECRET",
            "REST_API_SECRET",
            "POSTGRES_PASSWORD",
            "NEXTCLOUD_PASSWORD",
            "WOOCOMMERCE_SECRET",
        ):
            assert secret_key not in text

    def test_health_still_works(self):
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["env"] == "beta"
