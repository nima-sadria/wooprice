# WooPrice Beta — Control Plane Architecture

**Document:** CONTROL_PLANE_ARCHITECTURE.md
**Series:** CP1 Architecture Specification
**Status:** CP1.1 CLOSED — Owner approved 2026-06-28. CP1.2 NOT STARTED.
**Owner decision date:** 2026-06-27
**CHAT2 review date:** 2026-06-28
**CP1.1 commit:** 59f49c5 (285 tests, 0 failed)

---

## 1. Background and Motivation

### 1.1 Production Incident

In WooPrice 7.5A, a DNS or TLS failure on the Nextcloud server caused the following
observable behavior:

1. Nextcloud became unreachable at the network level.
2. The application caught all exceptions from `httpx` uniformly.
3. Login returned: **"Invalid Nextcloud credentials."**
4. Administrators could not log in because the only login path verified credentials
   against Nextcloud.
5. The Control Plane (settings, diagnostics, configuration editing, logs) was
   effectively inaccessible even though the application server was running normally
   and only one external dependency had failed.

This is an **architectural failure**, not a bug. The authentication path had an
undeclared dependency on an external integration service, and the application
had no mechanism to distinguish failure classes (DNS, TLS, timeout, 401, 403, etc.).

### 1.2 Architectural Decision

**Owner decision — 2026-06-27:**

WooPrice Beta must separate the system into two operational planes:

- **Control Plane** — administrative surface; must remain accessible at all times
  regardless of integration health.
- **Integration Plane** — external service connections; may be unavailable without
  affecting administrative access.

No Control Plane function may have an undeclared dependency on any Integration Plane
service. Every integration failure must surface the exact failure class, never a
collapsed generic message.

---

## 2. Plane Definitions

### 2.1 Control Plane

The Control Plane is the set of application surfaces that an administrator must
always be able to reach, regardless of whether external services are available.

**Control Plane surfaces:**

| Surface | Description |
|---|---|
| Login | Local credential authentication against the Beta user database |
| Settings | View and edit application configuration |
| Runtime Configuration | Edit integration endpoints, timeouts, retry policy |
| Diagnostics | Run health checks and view failure reports |
| Health Dashboard | View per-service health status and failure classes |
| Logs Viewer | View application and audit logs |
| Admin Panel | User management, role management |
| Feature Flags | Enable/disable feature flags |
| Plugin Manager | View, install, enable/disable plugins |
| Backup / Restore | Create and restore backups |
| Update Controls | Apply application updates |

**Invariant:** No item in the Control Plane may fail because Nextcloud, WooCommerce,
any external DNS, or any external API is unavailable.

### 2.2 Integration Plane

The Integration Plane is the set of application surfaces that depend on live
connections to external services.

**Integration Plane surfaces:**

| Surface | External dependency |
|---|---|
| Product Explorer | A2 Source Adapter → Nextcloud |
| Source Explorer | A2 Source Adapter → Nextcloud |
| Change Set Viewer | A2 Execution Engine → WooCommerce |
| Dry Run Viewer | A2 Rule Engine → product catalog |
| Execution Viewer | A2 Execution Engine → WooCommerce |
| Scheduler Viewer | A2 Scheduling Engine |
| AI Insights Viewer | A2 AI Foundation |

**Rule:** Integration Plane surfaces may be disabled, degraded, or show stale data
when external services are unavailable. They must display the failure class and a
repair path, not a generic "connection failed" message.

---

## 3. Core Design Principles

### P1 — Control Plane Never Depends on Integration Plane

No Control Plane function may issue a network request to an Integration Plane service.
Login is always local. Settings reads the local config. Diagnostics runs local checks first.

### P2 — Failure Classes Are Always Typed

No failure is reported as a generic message. Every integration check returns one of the
following typed failure classes:

| Class | Trigger condition |
|---|---|
| `dns_failure` | DNS resolution fails for the integration hostname |
| `tls_failure` | TLS handshake fails or certificate is invalid/expired |
| `timeout` | Connection or read exceeds configured timeout |
| `unauthorized` | HTTP 401 — credentials were presented and rejected |
| `forbidden` | HTTP 403 — credentials valid but access denied |
| `unreachable` | Connection refused or no route to host |
| `invalid_response` | Server responded with unexpected content |
| `ok` | Check passed |

Collapsing `dns_failure` or `tls_failure` into "Invalid credentials" is prohibited at
every layer: service, API response, and UI display.

### P3 — Local Authentication is Mandatory and Independent

JWT authentication is validated against the Beta user database, not against any
external service. The `BETA_JWT_SECRET` is local. The user table is local. The
permission model is local. No network call occurs during token validation.

### P4 — Runtime Configurability

Integration endpoints must be editable through the CLI and (in B8+) the UI without
SSH access and without editing `.env` manually. This is critical because the most
likely reason to need the Control Plane is precisely when an integration endpoint has
changed and needs to be corrected.

### P5 — Failure Transparency Drives Recovery

The UI must guide the administrator from failure detection to resolution:

1. **Detect** — Health Engine classifies the failure.
2. **Explain** — Diagnostics surfaces the failure class, probable cause, and severity.
3. **Repair** — UI shows actionable repair steps; Runtime Configuration allows immediate
   endpoint or credential correction.
4. **Verify** — Re-run health check after repair to confirm recovery.

---

## 4. System Model

```
┌───────────────────────────────────────────────────────────────────┐
│                          UI Layer (B8+)                            │
│                                                                    │
│   Offline Banner · Health Dashboard · Service Cards               │
│   Repair Workflow · Runtime Config Editor · Diagnostics View      │
├───────────────────────────────────────────────────────────────────┤
│                    API Layer (FastAPI /api/v2/)                    │
│                                                                    │
│   /api/v2/health         /api/v2/diagnostics                      │
│   /api/v2/config/        /api/v2/control-plane/status             │
├─────────────────────────────┬─────────────────────────────────────┤
│     Control Plane Services  │   Cross-Cutting Concerns             │
│                             │                                      │
│   ControlPlaneService       │   AuditLogger                        │
│   RuntimeConfigService      │   SecretManager                      │
│   DiagnosticRunner          │   FeatureFlagEvaluator               │
│   FeatureAvailability       │                                      │
├─────────────────────────────┼─────────────────────────────────────┤
│     Health Engine           │   Connection Manager                  │
│                             │                                      │
│   DNSCheck                  │   RetryPolicy                         │
│   TCPCheck                  │   CircuitBreaker                      │
│   TLSCheck                  │   BackoffStrategy                     │
│   HTTPCheck                 │   ConnectionCache                     │
│   AuthCheck                 │   TimeoutPolicy                       │
│   DatabaseCheck             │                                       │
│   StorageCheck              │                                       │
│   DockerCheck (B6+)         │                                       │
│   SchedulerCheck (B11+)     │                                       │
│   PluginCheck (B14+)        │                                       │
├─────────────────────────────┴─────────────────────────────────────┤
│                    Integration Plane (external)                    │
│                                                                    │
│   Nextcloud · WooCommerce · Currency API · DNS · TLS              │
└───────────────────────────────────────────────────────────────────┘
```

---

## 5. Module Layout

CP1 introduces the following new packages under `app/beta/`:

```
app/beta/
├── control_plane/               ← CP1 (new)
│   ├── __init__.py
│   ├── service.py               — ControlPlaneService
│   ├── status.py                — ControlPlaneStatus, IntegrationState, HealthLevel
│   └── availability.py          — FeatureAvailability (per-feature gate based on health)
│
├── connections/                 ← CP1 (new)
│   ├── __init__.py
│   ├── manager.py               — ConnectionManager
│   ├── result.py                — ConnectionResult, FailureClass
│   ├── retry.py                 — RetryPolicy, ExponentialBackoff
│   ├── circuit_breaker.py       — CircuitBreaker, BreakerState
│   └── timeout.py               — TimeoutPolicy
│
├── diagnostics/                 ← CP1 (new)
│   ├── __init__.py
│   ├── runner.py                — DiagnosticRunner
│   ├── report.py                — DiagnosticReport, DiagnosticCategory
│   ├── checks/
│   │   ├── __init__.py
│   │   ├── dns.py               — DNSCheck
│   │   ├── tcp.py               — TCPCheck
│   │   ├── tls.py               — TLSCheck
│   │   ├── http.py              — HTTPCheck
│   │   ├── auth.py              — AuthCheck
│   │   ├── database.py          — DatabaseCheck
│   │   ├── storage.py           — StorageCheck
│   │   ├── docker.py            — DockerCheck (stub in CP1; implemented in B6)
│   │   ├── scheduler.py         — SchedulerCheck (stub in CP1; implemented in B11)
│   │   └── plugins.py           — PluginCheck (stub in CP1; implemented in B14)
│   └── repair.py                — RepairSuggestion, RepairPlaybook
│
└── runtime_config/              ← CP1 (new)
    ├── __init__.py
    ├── service.py               — RuntimeConfigService
    ├── record.py                — ConfigRecord, ConfigChangeEvent
    └── api.py                   — B5 Runtime Config REST API (moved from B3 placeholder)
```

CLI extensions (in `cli/`):

```
cli/
├── diagnostics.py               ← EXTENDED: full diagnostic runner (was stub in B5)
├── health.py                    ← EXTENDED: adds per-service health checks
├── integrations.py              ← NEW: wooprice integrations list/test/status
├── control_plane.py             ← NEW: wooprice control-plane status
└── configure.py                 ← EXTENDED: set/get integration endpoints and timeouts
```

New architecture documents (in `docs/control-plane/`):

```
docs/control-plane/
├── CONTROL_PLANE_ARCHITECTURE.md   ← this document
├── OFFLINE_MODE.md
├── HEALTH_ENGINE.md
├── CONNECTION_MANAGER.md
├── RUNTIME_CONFIGURATION.md
├── DIAGNOSTICS_ARCHITECTURE.md
├── CONTROL_PLANE_SECURITY.md
└── IMPLEMENTATION_PLAN.md
```

---

## 6. ControlPlaneStatus Model

```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class HealthLevel(str, Enum):
    OK        = "ok"        # all services reachable
    DEGRADED  = "degraded"  # some integration services down; Control Plane intact
    CRITICAL  = "critical"  # Control Plane itself impaired (DB down, storage failure)


class ServiceStatus(str, Enum):
    OK       = "ok"
    DEGRADED = "degraded"
    DOWN     = "down"
    UNKNOWN  = "unknown"
    SKIP     = "skip"  # check not applicable in this phase


class FailureClass(str, Enum):
    OK               = "ok"
    DNS_FAILURE      = "dns_failure"
    TLS_FAILURE      = "tls_failure"
    TIMEOUT          = "timeout"
    UNAUTHORIZED     = "unauthorized"
    FORBIDDEN        = "forbidden"
    UNREACHABLE      = "unreachable"
    INVALID_RESPONSE = "invalid_response"


@dataclass
class IntegrationState:
    service_name: str
    status: ServiceStatus
    failure_class: Optional[FailureClass]
    failure_message: Optional[str]      # human-readable, never collapsed
    last_check_at: datetime
    last_ok_at: Optional[datetime]
    latency_ms: Optional[float]
    endpoint_url: Optional[str]         # redacted in API responses


@dataclass
class ControlPlaneStatus:
    timestamp: datetime
    overall_health: HealthLevel
    local_auth_available: bool          # always True when DB is reachable
    config_readable: bool
    config_writable: bool
    database_available: bool
    storage_available: bool
    integration_states: dict[str, IntegrationState] = field(default_factory=dict)
    # integration_states keys: "nextcloud", "woocommerce", "currency_api", etc.
```

---

## 7. FeatureAvailability

`FeatureAvailability` is a derived structure that maps each UI feature to its
availability state based on `ControlPlaneStatus`. It is computed by
`ControlPlaneService` and returned with every health API response.

```python
class AvailabilityState(str, Enum):
    AVAILABLE    = "available"    # fully operational
    DEGRADED     = "degraded"     # operational with limitations
    DISABLED     = "disabled"     # integration dependency unavailable
    NEVER        = "never"        # feature not implemented in this phase


@dataclass
class FeatureAvailability:
    # Control Plane — always AVAILABLE unless database/storage is down
    login:             AvailabilityState
    settings:          AvailabilityState
    runtime_config:    AvailabilityState
    diagnostics:       AvailabilityState
    health_dashboard:  AvailabilityState
    logs_viewer:       AvailabilityState
    admin_panel:       AvailabilityState
    feature_flags:     AvailabilityState
    plugin_manager:    AvailabilityState
    backup_restore:    AvailabilityState

    # Integration Plane — DISABLED when relevant integration is down
    product_explorer:  AvailabilityState  # needs nextcloud + woocommerce
    source_explorer:   AvailabilityState  # needs nextcloud
    change_sets:       AvailabilityState  # needs woocommerce
    dry_run:           AvailabilityState  # needs woocommerce + nextcloud
    execution:         AvailabilityState  # needs woocommerce
    scheduler:         AvailabilityState  # needs woocommerce (future)
    ai_insights:       AvailabilityState  # needs database only
```

---

## 8. Integration With B-Series Phases

| Phase | CP1 touchpoint |
|---|---|
| B3 | CP1 uses `ConfigurationManager`, `ConfigValidator`, `BetaConfig` — no modification |
| B4 | CP1 uses `installer_core` prerequisite data — no modification |
| B5 | CP1 extends `cli/diagnostics.py`, `cli/health.py`, `cli/configure.py` |
| B6 | B6 implements `DockerCheck` stub; CP1 `ControlPlaneStatus` adds container health fields |
| B7 | B7 auth system is built on the local-auth invariant established by CP1 security spec |
| B8 | B8 UI consumes `FeatureAvailability`; implements Offline Banner and Health Dashboard |
| B13 | B13 Admin panel is a Control Plane surface; must pass CP1 availability invariant |
| B14 | B14 Plugin Manager implements `PluginCheck` stub left by CP1 |

CP1 must not modify any B3–B5 implementation files. It may extend CLI modules by
adding new command groups; it must not change existing B5 command behavior.

---

## 9. Out of Scope for CP1

The following are explicitly deferred to later phases:

| Item | Deferred to |
|---|---|
| Docker health checks (`DockerCheck`) | B6 |
| Database migrations | B6 (when PostgreSQL container is live) |
| Bootstrap admin account creation | B7 |
| Login page (React) | B7 |
| Health Dashboard UI | B8 |
| Runtime Config Editor UI | B8 |
| Diagnostics page UI | B8 |
| Scheduler health check | B11 |
| Plugin health check | B14 |
| Secret rotation via UI | B15 |
| Automated remediation | Future |

CP1 delivers the **service layer and CLI interface** for all of the above. The UI
layer is documented here as a contract for B8 to implement.

---

## 10. CHAT2 Decisions Summary — 2026-06-28

All open design decisions resolved. No remaining open decisions.

| Decision | Resolution |
|---|---|
| OD1 — Cache storage | In-memory only in CP1. Redis deferred to B6/B13. |
| OD2 — Runtime config scope | Identity fields (username) are `.env`-only. URL/timeout/TLS/retry are runtime-editable. |
| OD3 — Health endpoint auth | Split: `GET /api/health` public minimal; `GET /api/v2/health` authenticated full detail. |
| OD4 — Circuit breaker scope | CP1 only: Connection Manager, Health Engine, Diagnostics. A2 Source Adapter excluded. |
| OD5 — Diagnostic storage | JSON files only in CP1. DB-backed history deferred to B13+. |
| OD6 — RuntimeConfigService placement | Separate service in `app/beta/runtime_config/`. B3 unchanged. |

**CP1 implementation split (CHAT2 rule):** If scope exceeds a single reviewable PR, split into:
- **CP1.1** — Core Models + Failure Taxonomy
- **CP1.2** — Connection Manager + Health Engine
- **CP1.3** — Diagnostics + Runtime Config + CLI/API Contracts

---

## 11. Document Index

| Document | Contents |
|---|---|
| CONTROL_PLANE_ARCHITECTURE.md | This document — overview, principles, module layout, models |
| OFFLINE_MODE.md | Degraded mode definition, surface matrix, banner spec, menu rules, recovery workflow |
| HEALTH_ENGINE.md | Health check taxonomy, result schema, check chains, aggregation, polling |
| CONNECTION_MANAGER.md | ConnectionResult, retry, circuit breaker, backoff, caching, timeout |
| RUNTIME_CONFIGURATION.md | Configurable items, ConfigRecord, API contract, CLI contract, secret handling |
| DIAGNOSTICS_ARCHITECTURE.md | 10 categories, DiagnosticReport schema, probable cause, repair playbooks |
| CONTROL_PLANE_SECURITY.md | Auth boundaries, external auth separation, secret handling, audit |
| IMPLEMENTATION_PLAN.md | Phase breakdown, test strategy, dependency graph, open decisions |
