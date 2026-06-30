"""Built-in Connector Registry for the Integration Platform foundation."""

from __future__ import annotations

from app.beta.integrations.contracts import (
    ConnectorCapabilities,
    ConnectorCapabilityDocument,
    ConnectorDefinition,
    ConnectorDiagnosticsContract,
    ConnectorHealthStatus,
    ConnectorIdentity,
    ConnectorSettingDefinition,
    DiagnosticCheckContract,
)


def _diagnostics(connector_type: str, auth_name: str) -> ConnectorDiagnosticsContract:
    return ConnectorDiagnosticsContract(
        connector_type=connector_type,
        checks=[
            DiagnosticCheckContract(
                name="settings",
                category="configuration",
                description="Required connector settings are present and valid.",
            ),
            DiagnosticCheckContract(
                name="dns",
                category="transport",
                description="Connector hostname resolves through the Connection Manager.",
            ),
            DiagnosticCheckContract(
                name="tls",
                category="transport",
                description="TLS handshake and certificate validation pass when HTTPS is used.",
            ),
            DiagnosticCheckContract(
                name=auth_name,
                category="authentication",
                description="Connector credentials are accepted by the external service.",
            ),
            DiagnosticCheckContract(
                name="capabilities",
                category="capability_detection",
                description="Connector capabilities are detected separately from authorization.",
            ),
        ],
    )


_BUILT_INS: dict[str, ConnectorDefinition] = {
    "woocommerce": ConnectorDefinition(
        connector=ConnectorCapabilityDocument(
            identity=ConnectorIdentity(
                id="woocommerce",
                name="WooCommerce",
                type="woocommerce",
                version="1.0.0",
                enabled=False,
                read_only=True,
            ),
            capabilities=ConnectorCapabilities(
                read_products=True,
                read_categories=True,
                read_inventory=True,
                read_orders=True,
                write_prices=True,
                write_inventory=True,
                webhook=True,
                polling=True,
                oauth=False,
                api_key=True,
            ),
            status=ConnectorHealthStatus.DISABLED,
        ),
        settings_schema=[
            ConnectorSettingDefinition(key="base_url", label="Store URL", required=True),
            ConnectorSettingDefinition(key="consumer_key", label="Consumer key", required=True, secret=True),
            ConnectorSettingDefinition(key="consumer_secret", label="Consumer secret", required=True, secret=True),
            ConnectorSettingDefinition(key="poll_interval_seconds", label="Polling interval", default=300),
        ],
        diagnostics_contract=_diagnostics("woocommerce", "api_key_auth"),
    ),
    "nextcloud": ConnectorDefinition(
        connector=ConnectorCapabilityDocument(
            identity=ConnectorIdentity(
                id="nextcloud",
                name="Nextcloud",
                type="nextcloud",
                version="1.0.0",
                enabled=False,
                read_only=True,
            ),
            capabilities=ConnectorCapabilities(
                read_products=True,
                read_categories=False,
                read_inventory=False,
                read_orders=False,
                write_prices=False,
                write_inventory=False,
                webhook=False,
                polling=True,
                oauth=False,
                api_key=False,
            ),
            status=ConnectorHealthStatus.DISABLED,
        ),
        settings_schema=[
            ConnectorSettingDefinition(key="base_url", label="Nextcloud URL", required=True),
            ConnectorSettingDefinition(key="file_path", label="Spreadsheet path", required=True),
            ConnectorSettingDefinition(key="username", label="Username", required=True),
            ConnectorSettingDefinition(key="password", label="Password", required=True, secret=True),
            ConnectorSettingDefinition(key="poll_interval_seconds", label="Polling interval", default=300),
        ],
        diagnostics_contract=_diagnostics("nextcloud", "basic_auth"),
    ),
}


class ConnectorRegistry:
    """Registry of available connector definitions."""

    def list_definitions(self) -> list[ConnectorDefinition]:
        return list(_BUILT_INS.values())

    def get_definition(self, connector_type: str) -> ConnectorDefinition | None:
        return _BUILT_INS.get(connector_type)


registry = ConnectorRegistry()
