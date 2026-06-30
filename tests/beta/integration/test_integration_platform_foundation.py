"""Integration Platform Foundation tests."""

from __future__ import annotations

from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.beta.app import app
from app.beta.database import BetaBase, get_db
from app.beta.integrations.contracts import ConnectorHealthStatus
from app.beta.integrations.models import ConnectorHealthSnapshot, ConnectorInstance, ConnectorSetting
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


def test_no_write_execution_routes_are_exposed():
    paths = [route.path.lower() for route in app.routes if hasattr(route, "path")]
    integration_paths = [p for p in paths if "/api/v2/integrations" in p]
    joined = " ".join(integration_paths)
    assert "apply" not in joined
    assert "execute" not in joined
    assert "scheduler" not in joined
