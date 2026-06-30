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
