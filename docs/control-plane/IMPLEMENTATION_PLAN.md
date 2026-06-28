# WooPrice Beta — CP1 Implementation Plan

**Document:** IMPLEMENTATION_PLAN.md
**Series:** CP1 Architecture Specification
**Status:** SPECIFICATION — awaiting CHAT2 review. No implementation has begun.

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

**Stub endpoints to implement:**

| Endpoint | Status | Notes |
|---|---|---|
| `GET /api/v2/health` | Stub | Returns hardcoded `ok` status in CP1 |
| `GET /api/v2/control-plane/status` | Stub | Returns `ControlPlaneStatus` computed from local state only |
| `GET /api/v2/config/` | Stub | Returns current TOML values |
| `PUT /api/v2/config/{key}` | Live in CP1 | RuntimeConfigService write path works without Docker |
| `POST /api/v2/config/validate` | Live in CP1 | Validation via B3 ConfigValidator |
| `POST /api/v2/diagnostics/run` | Stub | Returns `run_id`; full runner needs B6 DB |
| `GET /api/v2/diagnostics/{run_id}` | Stub | Returns placeholder DiagnosticReport |
| `GET /api/v2/diagnostics/history` | Stub | Returns empty list in CP1 |

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

## 6. Open Design Decisions

These decisions are unresolved and require CHAT2 input.

### OD1 — Connection Cache Storage

**Question:** In CP1 (before Redis/B6), should the connection cache be:
- (a) In-memory only (lost on restart)
- (b) File-backed (survives restart, adds I/O)

**Recommendation:** In-memory only for CP1. Redis in B6. The cache is for performance
(avoid repeated health checks) not for durability.

### OD2 — RuntimeConfigService Write Scope

**Question:** Should `configure set` allow updating `nextcloud.username` at runtime
(it is not a secret), or should identity fields also require `.env` editing?

**Recommendation:** Allow `nextcloud.url` and `nextcloud.file_path` (endpoint location).
Require `.env` for `nextcloud.username` because changing the username may invalidate
existing shared folders or API tokens. CHAT2 to confirm.

### OD3 — Health Check Endpoint Authentication

**Question:** Should `GET /api/v2/health` (the summary endpoint) require JWT or be
public?

**Arguments for public:** Monitoring tools, Docker health probes, and uptime services
need the endpoint without credentials.
**Arguments for authenticated:** The `feature_availability` and `integration_states`
fields contain potentially sensitive operational information.

**Recommendation:** Split into two endpoints:
- `GET /api/health` — public, minimal (overall_health only, for Docker probes)
- `GET /api/v2/health` — authenticated, full detail

CHAT2 to confirm.

### OD4 — Circuit Breaker Scope

**Question:** Should the circuit breaker apply to A2 Source Adapter calls in addition
to the Health Engine? (Currently specified for Health Engine only.)

**Recommendation:** Yes — the A2 Source Adapter shim should check circuit breaker
state before attempting a Nextcloud call. This prevents the A2 engine from hammering
a failed Nextcloud when many source tasks are queued. CHAT2 to confirm.

### OD5 — Diagnostic Run Storage Location

**Question:** Should completed diagnostic reports be stored in:
- (a) `$BETA_STORAGE_PATH/diagnostics/` as JSON files
- (b) The Beta database (when available in B6+)
- (c) Both

**Recommendation:** JSON files for CP1 and B6; replicate to DB in B13 for searchable
history in the Admin UI. CHAT2 to confirm.

### OD6 — RuntimeConfigService and B3 Overlap

**Question:** `RuntimeConfigService.set()` writes to the managed TOML. B3
`ConfigurationManager.load()` reads from the same file. Should CP1 introduce a
write path in `ConfigurationManager` itself, or keep it in a separate service?

**Recommendation:** Keep in a separate service (`RuntimeConfigService`). The B3
principle of being framework-independent means `ConfigurationManager` is read-only
at load time. The write path is an operational concern that belongs in the Beta
service layer. This avoids scope creep into B3.

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
7. All 6 open design decisions are resolved (by CHAT2 or Owner).
8. Phase Completion Report produced and CHAT2 review passed.
9. Owner approval received.
