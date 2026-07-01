"""Integration Platform canonical contracts.

The capability schema in this module is the Owner-approved baseline.  It
describes what a connector can technically do; it does not grant runtime
authorization.  FlowHub Beta keeps all write operations blocked independently
through the Safety Layer and Write Guard.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ConnectorHealthStatus(str, Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    ERROR = "error"
    DISABLED = "disabled"
    DEGRADED = "degraded"
    AUTHENTICATION_FAILED = "authentication_failed"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"


class ConnectorIdentity(BaseModel):
    id: str
    name: str
    type: str
    version: str
    enabled: bool = False
    read_only: bool = True


class ConnectorCapabilities(BaseModel):
    read_products: bool = False
    read_categories: bool = False
    read_inventory: bool = False
    read_orders: bool = False
    write_prices: bool = False
    write_inventory: bool = False
    webhook: bool = False
    polling: bool = False
    oauth: bool = False
    api_key: bool = False


class ConnectorCapabilityDocument(BaseModel):
    identity: ConnectorIdentity
    capabilities: ConnectorCapabilities
    status: ConnectorHealthStatus = ConnectorHealthStatus.DISABLED
    runtime_write_blocked: bool = True
    capability_authorizes_write: Literal[False] = False


class ConnectorSettingDefinition(BaseModel):
    key: str
    label: str
    required: bool = False
    secret: bool = False
    default: Any = None
    help_text: str | None = None


class ConnectorDefinition(BaseModel):
    connector: ConnectorCapabilityDocument
    settings_schema: list[ConnectorSettingDefinition] = Field(default_factory=list)
    diagnostics_contract: "ConnectorDiagnosticsContract"


class ConnectorSettingValue(BaseModel):
    key: str
    value: Any = None
    secret: bool = False
    configured: bool = False


class ConnectorInstanceShape(BaseModel):
    connector: ConnectorCapabilityDocument
    settings: list[ConnectorSettingValue] = Field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None


class ConnectorProductShape(BaseModel):
    id: str
    connector_id: str
    external_id: str
    name: str
    sku: str | None = None
    current_price: float | None = None
    inventory_quantity: int | None = None
    category_names: list[str] = Field(default_factory=list)
    updated_at: str | None = None


class ConnectorProductListResponse(BaseModel):
    items: list[ConnectorProductShape]
    total: int
    page: int
    page_size: int
    runtime_write_blocked: bool = True


class ConnectorSourceShape(BaseModel):
    id: str
    connector_id: str
    name: str
    type: str
    status: ConnectorHealthStatus
    last_synced_at: str | None = None
    product_count: int = 0


class ConnectorSourceListResponse(BaseModel):
    items: list[ConnectorSourceShape]
    runtime_write_blocked: bool = True


class WorkspaceIntegrationSummary(BaseModel):
    source_count: int
    product_count: int
    connector_count: int
    runtime_write_blocked: bool = True
    apply_available: bool = False
    scheduler_available: bool = False
    pricing_automation_available: bool = False


class IntegrationSettingsSummary(BaseModel):
    connector_id: str
    connector_type: str
    name: str
    settings: list[ConnectorSettingValue]
    runtime_write_blocked: bool = True


class ConnectorTelemetryShape(BaseModel):
    id: int
    connector_id: str
    event_name: str
    severity: str
    message: str
    created_at: str
    metadata: dict = Field(default_factory=dict)


class ConnectorTelemetryResponse(BaseModel):
    items: list[ConnectorTelemetryShape]
    total: int


class DiagnosticCheckContract(BaseModel):
    name: str
    category: str
    required: bool = True
    description: str


class ConnectorDiagnosticsContract(BaseModel):
    connector_type: str
    checks: list[DiagnosticCheckContract]


class ConnectorCreateRequest(BaseModel):
    connector_type: str
    id: str | None = None
    name: str | None = None
    enabled: bool = False
    read_only: bool = True


class ConnectorSettingsUpdateRequest(BaseModel):
    settings: list[ConnectorSettingValue]


class ConnectorRegistryResponse(BaseModel):
    items: list[ConnectorDefinition]
    runtime_write_blocked: bool = True


class ConnectorListResponse(BaseModel):
    items: list[ConnectorInstanceShape]
    runtime_write_blocked: bool = True


ConnectorDefinition.model_rebuild()
