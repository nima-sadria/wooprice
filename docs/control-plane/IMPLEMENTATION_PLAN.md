# WooPrice Beta — CP1 Implementation Plan

**Document:** IMPLEMENTATION_PLAN.md
**Series:** CP1 Architecture Specification
**Status:** CHAT2 APPROVED with modifications — 2026-06-28. Specification complete. READY FOR OWNER REVIEW. No implementation has begun.

---

## 1. Overview

CP1 (Control Plane Foundation Pack) is a focused phase that builds the service-layer
infrastructure for Control Plane resilience. It operates entirely in the pre-Docker
phase (like B3–B5) and produces:

- Core services (`app/beta/control_plane/`, `app/beta/connections/`, `app/beta/diagnostics/`)
- Extended CLI commands
- REST API contracts (implemented as stubs in CP1; live in B6+)
- Architecture documentation (this document set)

CP1 does not implement the UI, the database (B6+), Docker (B6), or authentication (B7).
It does not modify any existing B3–B5 code.

---

## 2. Part Breakdown

### Part 1 — Core Service Layer (`app/beta/control_plane/`)

**Deliverables:**

| File | Contents |
|---|---|
| `app/beta/control_plane/__init__.py` | Package marker |
| `app/beta/control_plane/status.py` | `HealthLevel`, `ServiceStatus`, `FailureClass`, `IntegrationState`, `ControlPlaneStatus` |
| `app/beta/control_plane/availability.py` | `AvailabilityState`, `FeatureAvailability`, computation logic |
| `app/beta/control_plane/service.py` | `ControlPlaneService.get_status()`, `ControlPlaneService.get_feature_availability()` |

**Key invariants to test:**
- `ControlPlaneStatus.overall_health == DEGRADED` when any integration is down but DB is up
- `ControlPlaneStatus.overall_health == CRITICAL` when DB or storage is down
- `FeatureAvailability.login == AVAILABLE` regardless of any integration state
- `FeatureAvailability.settings == AVAILABLE` regardless of any integration state
- `FeatureAvailability.product_explorer == DISABLED` when nextcloud OR woocommerce is down

---

### Part 2 — Connection Manager (`app/beta/connections/`)

**Deliverables:**

| File | Contents |
|---|---|
| `app/beta/connections/__init__.py` | Package marker |
| `app/beta/connections/result.py` | `FailureClass`, `ConnectionResult` |
| `app/beta/connections/timeout.py` | `TimeoutPolicy` |
| `app/beta/connections/retry.py` | `RetryPolicy`, `ExponentialBackoff` |
| `app/beta/connections/circuit_breaker.py` | `BreakerState`, `CircuitBreaker` |
| `app/beta/connections/manager.py` | `ServiceName`, `ServiceDefinition`, `ConnectionManager` |

**Key invariants to test:**
- Exception → `FailureClass` mapping is exhaustive (no exceptions escape unclassified)
- `socket.gaierror` always maps to `dns_failure`
- `ssl.SSLError` always maps to `tls_failure`
- HTTP 401 maps to `unauthorized`; HTTP 403 maps to `forbidden`
- Circuit breaker transitions: CLOSED → OPEN after `failure_threshold` failures
- Circuit breaker: OPEN → HALF_OPEN after `recovery_window_s`
- Circuit breaker bypass on explicit health check calls
- `dns_failure` and `tls_failure` are not retried
- `timeout` and `unreachable` are retried up to `max_attempts`
- Cache TTL is respected; stale cache returns `unknown` status (not cached `ok`)

---

### Part 3 — Health Engine (`app/beta/diagnostics/checks/`)

**Deliverables:**

| File | Contents |
|---|---|
| `app/beta/diagnostics/__init__.py` | Package marker |
| `app/beta/diagnostics/checks/__init__.py` | Package marker |
| `app/beta/diagnostics/checks/dns.py` | `DNSCheck` |
| `app/beta/diagnostics/checks/tcp.py` | `TCPCheck` |
| `app/beta/diagnostics/checks/tls.py` | `TLSCheck` |
| `app/beta/diagnostics/checks/http.py` | `HTTPCheck` |
| `app/beta/diagnostics/checks/auth.py` | `AuthCheck` |
| `app/beta/diagnostics/checks/database.py` | `DatabaseCheck` (stub — SKIP in CP1) |
| `app/beta/diagnostics/checks/storage.py` | `StorageCheck` |
| `app/beta/diagnostics/checks/docker.py` | `DockerCheck` (stub — SKIP in CP1) |
| `app/beta/diagnostics/checks/scheduler.py` | `SchedulerCheck` (stub — SKIP in CP1) |
| `app/beta/diagnostics/checks/plugins.py` | `PluginCheck` (stub — SKIP in CP1) |

**Key invariants to test (using fakes, no real network):**
- Check chain: if DNS fails, all subsequent checks return SKIP
- `AuthCheck.detail` contains no credentials
- `TLSCheck` returns WARN (not FAIL) when cert expires in < 30 days
- `TLSCheck` returns FAIL when cert is expired
- `StorageCheck` returns WARN at < 1GB, FAIL at < 100MB
- Stub checks return SKIP with correct message
- All checks complete within their configured timeout

**Test strategy — fake network:**
All Health Engine tests use fake/mock network backends. No real Nextcloud, WooCommerce,
or DNS is contacted. Fakes simulate:
- DNS failure (`socket.gaierror`)
- TLS failure (`ssl.SSLError`)
- TCP timeout (`socket.timeout`)
- Connection refused (`ConnectionRefusedError`)
- HTTP 401, 403, 200 responses
- Expired certificates (via mock datetime)

---

### Part 4 — Diagnostic Runner and Report (`app/beta/diagnostics/`)

**Deliverables:**

| File | Contents |
|---|---|
| `app/beta/diagnostics/runner.py` | `DiagnosticRunner.run(target)` |
| `app/beta/diagnostics/report.py` | `DiagnosticReport`, `DiagnosticCategory`, `DiagnosticCheckResult`, `RepairStep` |
| `app/beta/diagnostics/repair.py` | `ProbableCauseInferrer`, `RepairPlaybook` |

**Key invariants to test:**
- `dns_failure` in Nextcloud chain → correct probable cause text
- `tls_failure` in Nextcloud chain → correct probable cause text
- `unauthorized` in Nextcloud chain → correct probable cause text (not conflated with DNS)
- `repair_priority` is ordered: first category with FAIL comes first
- Full report JSON is serializable and contains no secrets
- Audit entry is written to the mock audit logger on every run

---

### Part 5 — Runtime Configuration Service (`app/beta/runtime_config/`)

**Deliverables:**

| File | Contents |
|---|---|
| `app/beta/runtime_config/__init__.py` | Package marker |
| `app/beta/runtime_config/record.py` | `ConfigRecord`, `ConfigChangeEvent` |
| `app/beta/runtime_config/service.py` | `RuntimeConfigService` |

**Key invariants to test:**
- `set(secret_key, value)` raises `ProtectedKeyError` and never writes
- `set(invalid_url, "not-a-url")` raises `ConfigurationError` and never writes
- `set(valid_key, value)` writes to TOML atomically
- If TOML write fails (disk full simulation), original TOML is unchanged
- Audit log entry is written before TOML write is considered complete
- `ConnectionManager` is notified after successful URL change

---

### Part 6 — CLI Extensions

**Extended commands (modify existing B5 modules — additive only, no behavior changes):**

| Command | Change |
|---|---|
| `wooprice health` | Add per-integration health chain display; was local-only in B5 |
| `wooprice configure show` | Add integration-specific fields from RuntimeConfigService |
| `wooprice configure set` | Implement full write path via RuntimeConfigService |
| `wooprice configure get` | Implement single-key lookup via RuntimeConfigService |
| `wooprice diagnostics run` | Replace B5 stub with full DiagnosticRunner |

**New commands:**

| Command | File | Description |
|---|---|---|
| `wooprice control-plane status` | `cli/control_plane.py` | Show ControlPlaneStatus |
| `wooprice integrations list` | `cli/integrations.py` | List all configured integrations |
| `wooprice integrations test <service>` | `cli/integrations.py` | Run check chain for one service |
| `wooprice integrations status` | `cli/integrations.py` | Show IntegrationState for all services |
| `wooprice diagnostics history` | `cli/diagnostics.py` | List past runs |

**No B5 commands may change behavior. Extensions are additive only.**

---

### Part 7 — REST API Stubs

CP1 defines the API contracts (see individual architecture documents). The actual
FastAPI endpoints are implemented as stubs that return the correct response schema
with placeholder data. Live behavior comes in B6 (when the database is available)
and B8 (when the UI is ready).

**OD3 update:** The health API is now split. `GET /api/health` is public (minimal).
`GET /api/v2/health` is authenticated (full detail). See HEALTH_ENGINE.md §7.

**Stub endpoints to implement:**

| Endpoint | Auth | Status in CP1 | Notes |
|---|---|---|---|
| `GET /api/health` | Public | Live | Returns `{"status": "ok\|degraded\|critical", "timestamp": "..."}` only |
| `GET /api/v2/health` | JWT | Stub | Returns full `ControlPlaneStatus` from in-memory state |
| `GET /api/v2/control-plane/status` | JWT | Stub | Returns `ControlPlaneStatus` + `FeatureAvailability` |
| `GET /api/v2/config/` | JWT admin | Live | Returns current TOML values (no secrets) |
| `PUT /api/v2/config/{key}` | JWT admin | Live | RuntimeConfigService write path; works without Docker |
| `POST /api/v2/config/validate` | JWT admin | Live | Validation via B3 ConfigValidator |
| `POST /api/v2/diagnostics/run` | JWT admin | Stub | Returns `run_id`; DiagnosticRunner works in CP1 |
| `GET /api/v2/diagnostics/{run_id}` | JWT admin | Live | Returns DiagnosticReport from JSON file |
| `GET /api/v2/diagnostics/history` | JWT admin | Live | Returns list from `$BETA_STORAGE_PATH/diagnostics/` |

---

## 3. Test Strategy

### 3.1 Test Location

All CP1 tests live in `tests/beta/cp1/`:

```
tests/beta/cp1/
├── conftest.py                  — shared fixtures (fake ConnectionManager, mock audit logger)
├── test_control_plane_status.py — ControlPlaneStatus + FeatureAvailability computation
├── test_connection_manager.py   — retry, circuit breaker, backoff, failure classification
├── test_health_engine.py        — all check types with fake network backends
├── test_diagnostic_runner.py    — full diagnostic run with fake checks
├── test_diagnostic_report.py    — report serialization, no secrets in output
├── test_runtime_config.py       — set/get/validate, protected key rejection, atomic write
├── test_cli_integrations.py     — CLI integration commands
├── test_cli_control_plane.py    — wooprice control-plane status
└── test_cli_diagnostics.py      — wooprice diagnostics run (full output)
```

### 3.2 No Real Network in Tests

All tests that exercise the Health Engine, Connection Manager, or AuthCheck use
injected fake network backends. The fake backends simulate:

- DNS resolution success and failure
- TCP connect success, refusal, and timeout
- TLS handshake success and failure (including cert expiry scenarios)
- HTTP 200, 401, 403, 500 responses
- Certificate with configurable expiry date

No test ever contacts Nextcloud, WooCommerce, or any external DNS.

### 3.3 Coverage Targets

| Module | Target coverage |
|---|---|
| `FailureClass` mapping (classify_exception) | 100% — all exception types covered |
| `CircuitBreaker` state transitions | 100% — all transitions tested |
| `DiagnosticRunner` category coverage | 10 categories tested (6 live + 4 stubs) |
| `RuntimeConfigService.set` | 100% — valid, invalid, protected key, disk-full |
| CLI command output | All commands produce correct output format |

### 3.4 Regression

CP1 tests must not break B3, B4, or B5 tests. The full test suite runs:

```
pytest tests/beta/config/   # B3 — 146 tests
pytest tests/beta/installer/ # B4 — 169 tests + 1 skip
pytest tests/beta/cli/       # B5 — 185 tests
pytest tests/beta/cp1/       # CP1 — target: 150+ tests
```

All four suites must pass with 0 failures before the Phase Completion Report.

---

## 4. Dependency Graph

```
B3 Configuration Foundation (CLOSED)
  └── B4 Installer Foundation (CLOSED)
        └── B5 CLI Foundation (CLOSED)
              └── CP1 Control Plane Foundation Pack ← current
                    ├── consumes: B3 ConfigurationManager, ConfigValidator, BetaConfig
                    ├── consumes: B4 prerequisite check infrastructure
                    ├── extends: B5 CLI (additive — no changes to existing commands)
                    └── establishes contracts for:
                          ├── B6 Docker Runtime (DockerCheck, background polling)
                          ├── B7 Auth (local-auth-only invariant, security boundaries)
                          ├── B8 UI (FeatureAvailability, Offline Banner, Health Dashboard)
                          └── B13 Admin (always-available Control Plane surfaces)
```

---

## 5. Integration Points With Future Phases

### B6 — Docker Runtime Foundation

CP1 leaves the following stubs for B6 to implement:

- `DockerCheck` — currently returns SKIP; B6 implements container health checks
- `DatabaseCheck` — currently returns SKIP; B6 activates when PostgreSQL container is running
- Background health check polling (B6 introduces the scheduler worker)
- Redis connection cache (B6 introduces Redis; CP1 uses in-memory cache)
- Service restart after `configure set` with `requires_restart=True`

### B7 — Authentication Foundation

CP1 defines the contract that B7 must fulfill:

- `POST /api/auth/login` must use local bcrypt verification only
- No external service may be contacted in the primary login path
- Rate limiting on login endpoint
- JWT lifecycle is independent of integration health

B7 may not implement any auth flow that contradicts CP1 Security Invariants I1–I5
without Owner approval.

### B8 — Read-only A2 Inspector UI

B8 consumes `FeatureAvailability` from `GET /api/v2/control-plane/status` to:
- Show/hide the Offline Banner
- Enable/disable sidebar items
- Show degraded-mode panels on Integration Plane pages

B8 implements the UI components specified in `OFFLINE_MODE.md`.

### B13 — Feature Flag Manager + Admin UI

All B13 Admin Panel surfaces are Control Plane surfaces. B13 must verify that:
- User management, feature flags, and audit log are accessible when integration services are down
- The `FeatureAvailability` returned by CP1 marks these as `AVAILABLE`

### B14 — Plugin System

B14 implements `PluginCheck` (currently a stub). The `DiagnosticRunner` plug-in
pattern in CP1 allows B14 to register its checks without modifying the DiagnosticRunner.

---

## 6. CHAT2 Decisions (Resolved — 2026-06-28)

All open design decisions have been resolved by CHAT2 review.

### OD1 — Connection Cache Storage  ✓ RESOLVED

**Decision:** CP1 uses in-memory cache only. Persistent cache (Redis) deferred to B6/B13.
**Impact:** `ConnectionManager` holds cache as a `dict[ServiceName, CacheEntry]` in
instance memory. No Redis or file dependency introduced in CP1.

### OD2 — RuntimeConfigService Write Scope  ✓ RESOLVED

**Decision:** Identity fields (`nextcloud.username`) remain `.env`-only in CP1.
Runtime configuration covers: URL, timeout, TLS option, retry policy, connection metadata.
**Impact:** `RUNTIME_CONFIGURABLE_KEYS` excludes `nextcloud.username`. Any attempt to
set it via `configure set` raises `ProtectedKeyError`.

### OD3 — Health Endpoint Authentication  ✓ RESOLVED

**Decision:** Split into two endpoints:
- `GET /api/health` — public, returns `{"status": "ok|degraded|critical", "timestamp": "..."}` only
- `GET /api/v2/health` — authenticated (JWT), returns full `ControlPlaneStatus`

**Impact:** Public endpoint must not expose integration names, failure classes, topology,
credentials, or internal detail. All such information is on the authenticated endpoint.

### OD4 — Circuit Breaker Scope  ✓ RESOLVED

**Decision:** CP1 circuit breaker applies to Connection Manager, Health Engine, and
Diagnostics only. NOT applied to A2 Source Adapter calls. A2 remains frozen.
Any A2 adapter integration requires a later audited phase.
**Impact:** No `adapter_shim.py`. No modification of any A2 module.

### OD5 — Diagnostic Storage  ✓ RESOLVED

**Decision:** CP1 stores diagnostic reports as JSON files in
`$BETA_STORAGE_PATH/diagnostics/`. Database-backed history deferred to B13+.
**Impact:** `DiagnosticRunner` writes JSON to filesystem only. No DB write in CP1.

### OD6 — RuntimeConfigService Placement  ✓ RESOLVED

**Decision:** RuntimeConfigService is a separate service in `app/beta/runtime_config/`.
B3 `ConfigurationManager` remains read-only. No B3 files modified.
**Impact:** Write path entirely in CP1; B3 is consumed, not modified.

---

## 6a. CP1 Implementation Split

**CHAT2 additional rule (2026-06-28):** CP1 must be implementation-sized. If the
implementation would exceed a reasonable single-PR review size, split into at most
3 subparts:

### CP1.1 — Core Models + Failure Taxonomy

**Scope:**
- `app/beta/control_plane/status.py` — `HealthLevel`, `ServiceStatus`, `FailureClass`, `IntegrationState`, `ControlPlaneStatus`
- `app/beta/control_plane/availability.py` — `AvailabilityState`, `FeatureAvailability`
- `app/beta/control_plane/service.py` — `ControlPlaneService`
- `app/beta/connections/result.py` — `ConnectionResult`, `FailureClass` (canonical taxonomy)
- `tests/beta/cp1/test_control_plane_status.py`
- `tests/beta/cp1/test_feature_availability.py`
- `tests/beta/cp1/test_failure_class.py`

**Gate:** CP1.1 is CLOSED before CP1.2 begins. `FailureClass` is the
foundational type consumed by all subsequent parts.

### CP1.2 — Connection Manager + Health Engine

**Scope:**
- `app/beta/connections/` — full Connection Manager (timeout, retry, backoff, circuit breaker, cache)
- `app/beta/diagnostics/checks/` — all 10 check types (6 live + 4 stubs)
- `tests/beta/cp1/test_connection_manager.py`
- `tests/beta/cp1/test_health_engine.py`

**Gate:** CP1.2 is CLOSED before CP1.3 begins. Connection Manager must pass
full circuit breaker transition tests and failure classification coverage.

### CP1.3 — Diagnostics + Runtime Config + CLI/API Contracts

**Scope:**
- `app/beta/diagnostics/runner.py`, `report.py`, `repair.py`
- `app/beta/runtime_config/` — full RuntimeConfigService
- CLI extensions: `cli/control_plane.py`, `cli/integrations.py`, updated `cli/diagnostics.py`, `cli/health.py`, `cli/configure.py`
- REST API stubs (updated for OD3 split endpoints)
- `tests/beta/cp1/test_diagnostic_runner.py`, `test_runtime_config.py`, `test_cli_*`

**Gate:** CP1.3 is CLOSED when all tests pass and the Phase Completion Report is produced.

---

## 7. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Exception classification is incomplete | HIGH | Exhaustive test suite against all exception types; fallback to `invalid_response` |
| CircuitBreaker has a race condition in async context | HIGH | Asyncio locks on all state transitions; test with concurrent tasks |
| RuntimeConfigService write corrupts TOML | HIGH | Atomic write (temp file + os.replace); test disk-full scenario |
| AuthCheck credential handling leaks secrets | HIGH | Explicit `del credentials` after use; scrubbing in test assertions |
| B5 CLI extensions inadvertently change existing behavior | MEDIUM | Additive-only policy; regression test suite must pass unchanged |
| CP1 service layer duplicates B3 validation | LOW | RuntimeConfigService delegates all validation to B3 ConfigValidator |

---

## 8. Phase Exit Criteria

CP1 is complete when:

1. All 6 service modules pass their test suites with 0 failures.
2. B3 regression (146 tests), B4 regression (169+1), B5 regression (185) all pass.
3. CP1 test suite achieves target coverage.
4. CLI commands `wooprice control-plane status`, `wooprice integrations list/test/status`,
   `wooprice diagnostics run` all produce correct output.
5. `RuntimeConfigService.set()` correctly rejects protected keys and validates URLs.
6. `DiagnosticReport` JSON contains no secrets (verified by explicit test assertion).
7. All open design decisions confirmed resolved by CHAT2 review (2026-06-28).
8. Phase Completion Report produced and CHAT2 review passed.
9. Owner approval received.
