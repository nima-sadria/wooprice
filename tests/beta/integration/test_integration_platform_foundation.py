"""Integration Platform Foundation tests."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.beta.app import app
from app.beta.database import BetaBase, get_db
from app.beta.integrations.contracts import ConnectorHealthStatus
from app.beta.integrations.registry import registry


@contextmanager
def _client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    BetaBase.metadata.create_all(bind=engine)

    def override_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_canonical_capability_schema_advertises_capability_not_permission():
    woo = registry.get_definition("woocommerce")
    assert woo is not None
    assert woo.connector.capabilities.write_prices is True
    assert woo.connector.capabilities.write_inventory is True
    assert woo.connector.runtime_write_blocked is True
    assert woo.connector.capability_authorizes_write is False


def test_registry_contains_current_connectors():
    definitions = {d.connector.identity.type: d for d in registry.list_definitions()}
    assert {"woocommerce", "nextcloud"}.issubset(definitions)
    assert definitions["nextcloud"].connector.capabilities.polling is True
    assert definitions["woocommerce"].connector.capabilities.api_key is True


def test_health_status_model_uses_owner_status_values():
    assert {item.value for item in ConnectorHealthStatus} == {
        "healthy",
        "warning",
        "error",
        "disabled",
        "degraded",
        "authentication_failed",
        "rate_limited",
        "timeout",
    }


def test_api_registry_response_shape():
    with _client() as client:
        response = client.get("/api/v2/integrations/registry")
    assert response.status_code == 200
    data = response.json()
    assert data["runtime_write_blocked"] is True
    assert len(data["items"]) >= 2
    assert "diagnostics_contract" in data["items"][0]


def test_connector_instance_settings_mask_secrets():
    with _client() as client:
        created = client.post(
            "/api/v2/integrations/connectors",
            json={"connector_type": "woocommerce", "id": "wc-main", "name": "Main store"},
        )
        assert created.status_code == 201

        updated = client.patch(
            "/api/v2/integrations/connectors/wc-main/settings",
            json={
                "settings": [
                    {"key": "base_url", "value": "https://shop.example.test", "secret": False},
                    {"key": "consumer_secret", "value": "cs_secret", "secret": True},
                ]
            },
        )
        assert updated.status_code == 200
        settings = {item["key"]: item for item in updated.json()["settings"]}
        assert settings["base_url"]["value"] == "https://shop.example.test"
        assert settings["consumer_secret"]["value"] is None
        assert settings["consumer_secret"]["configured"] is True


def test_connector_creation_populates_source_and_telemetry():
    with _client() as client:
        created = client.post(
            "/api/v2/integrations/connectors",
            json={"connector_type": "nextcloud", "id": "nc-main", "name": "Price sheet"},
        )
        assert created.status_code == 201

        sources = client.get("/api/v2/sources")
        assert sources.status_code == 200
        source_items = sources.json()["items"]
        assert len(source_items) == 1
        assert source_items[0]["connector_id"] == "nc-main"
        assert source_items[0]["type"] == "nextcloud"

        telemetry = client.get("/api/v2/integrations/telemetry")
        assert telemetry.status_code == 200
        assert telemetry.json()["items"][0]["event_name"] == "connector_created"


def test_products_are_read_from_integration_data_layer_only():
    with _client() as client:
        response = client.get("/api/v2/products")
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["runtime_write_blocked"] is True


def test_workspace_summary_is_read_only():
    with _client() as client:
        client.post(
            "/api/v2/integrations/connectors",
            json={"connector_type": "woocommerce", "id": "wc-main", "name": "Main store"},
        )
        response = client.get("/api/v2/workspace")
    assert response.status_code == 200
    data = response.json()
    assert data["connector_count"] == 1
    assert data["runtime_write_blocked"] is True
    assert data["apply_available"] is False
    assert data["scheduler_available"] is False
    assert data["pricing_automation_available"] is False


def test_diagnostics_do_not_perform_external_calls():
    with _client() as client:
        response = client.post("/api/v2/diagnostics/run", json={"target": "woocommerce"})
    assert response.status_code == 200
    data = response.json()
    assert data["summary"].endswith("without direct external connector calls.")
    assert all(check["details"]["external_call_performed"] is False for check in data["checks"])


def test_settings_are_read_only_and_secret_safe():
    with _client() as client:
        client.post(
            "/api/v2/integrations/connectors",
            json={"connector_type": "woocommerce", "id": "wc-main", "name": "Main store"},
        )
        client.patch(
            "/api/v2/integrations/connectors/wc-main/settings",
            json={"settings": [{"key": "consumer_secret", "value": "cs_secret", "secret": True}]},
        )
        listed = client.get("/api/v2/config")
        blocked = client.put("/api/v2/config/connector.wc-main.consumer_secret", json={"value": "new"})
    assert listed.status_code == 200
    assert listed.json()[0]["current_value"] == "configured"
    assert "cs_secret" not in str(listed.json())
    assert blocked.status_code == 403


def test_no_write_execution_routes_are_exposed():
    paths = [route.path.lower() for route in app.routes if hasattr(route, "path")]
    integration_paths = [p for p in paths if "/api/v2/integrations" in p]
    joined = " ".join(integration_paths)
    assert "apply" not in joined
    assert "execute" not in joined
    assert "scheduler" not in joined


def test_beta_v2_routers_do_not_import_direct_external_clients():
    root = Path("app/beta/api/v2")
    forbidden = (
        "app.services.woocommerce",
        "app.services.nextcloud",
        "httpx",
        "download_xlsx",
        "fetch_all_products",
    )
    offenders: list[str] = []
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                offenders.append(f"{path}:{token}")
    assert offenders == []
