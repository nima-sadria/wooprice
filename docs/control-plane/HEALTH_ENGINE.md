# WooPrice Beta — Health Engine

**Document:** HEALTH_ENGINE.md
**Series:** CP1 Architecture Specification
**Status:** CLOSED — CP1.2 implementation complete. Owner approved 2026-06-28. Commit 7694c04.

---

## 1. Overview

The Health Engine is the subsystem responsible for independently evaluating the
operational status of every service and resource that WooPrice Beta depends on.
It produces structured, typed results for every check — never generic strings.

The Health Engine is consumed by:
- `ControlPlaneService` — to compute `ControlPlaneStatus`
- `DiagnosticRunner` — to build full diagnostic reports
- CLI commands (`wooprice health`, `wooprice integrations test`, `wooprice diagnostics run`)
- API endpoint `GET /api/v2/health` — for the UI Health Dashboard

---

## 2. HealthCheckResult Schema

Every health check — regardless of type — returns a `HealthCheckResult`.

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from app.beta.connections.result import FailureClass


class CheckStatus(str, Enum):
    OK   = "ok"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"  # not attempted (prerequisite check failed)


@dataclass
class HealthCheckResult:
    check_name: str             # e.g. "dns", "tls", "http_auth"
    target: str                 # URL, hostname, or path being checked
    status: CheckStatus
    failure_class: Optional[FailureClass]
    message: str                # concise human-readable status line
    detail: dict                # structured — safe to log; no secrets
    timestamp: datetime
    duration_ms: float
    skipped_because: Optional[str] = None  # name of prerequisite check that failed
```

### 2.1 The `detail` Field

`detail` is a typed dict with check-specific fields. It must never contain secret values.
Examples:

```python
# DNS check detail
{"hostname": "nextcloud.example.com", "resolved_ips": ["203.0.113.1"], "resolver": "192.168.100.1"}

# TLS check detail
{"hostname": "nextcloud.example.com", "port": 443, "cert_subject": "...",
 "cert_expiry": "2027-01-01", "days_until_expiry": 187, "chain_valid": true}

# HTTP check detail
{"url": "https://nextcloud.example.com/status.php", "status_code": 200,
 "content_type": "application/json", "response_time_ms": 142.3}

# Auth check detail
{"service": "nextcloud", "auth_method": "basic", "status_code": 200,
 "ocs_statuscode": 200}  # username/password never in detail

# Database check detail
{"driver": "postgresql", "host": "postgres", "port": 5432,
 "database": "wooprice_beta", "latency_ms": 3.2}

# Storage check detail
{"path": "/data/wooprice", "readable": true, "writable": true,
 "free_gb": 42.1, "total_gb": 100.0}
```

---

## 3. Check Types

### 3.1 DNSCheck

Resolves the hostname extracted from an integration URL.

**Input:** URL string (hostname extracted internally)
**Implementation:** `socket.getaddrinfo()` with timeout — pure stdlib, no external deps.

| Outcome | FailureClass | message example |
|---|---|---|
| Resolution succeeds | `ok` | "nextcloud.example.com → 203.0.113.1" |
| Resolution fails (NXDOMAIN / timeout) | `dns_failure` | "Could not resolve nextcloud.example.com" |
| Empty URL / no hostname | `invalid_response` | "No hostname in configured URL" |

### 3.2 TCPCheck

Attempts a TCP connection to host:port without sending any data.

**Input:** hostname, port, timeout (seconds)
**Prerequisite:** DNSCheck must pass. If DNS failed, TCPCheck is skipped with
`status=SKIP, skipped_because="dns"`.

| Outcome | FailureClass | message example |
|---|---|---|
| Connection succeeds | `ok` | "TCP connect to nextcloud.example.com:443 ok (12ms)" |
| Connection refused | `unreachable` | "Connection refused: nextcloud.example.com:443" |
| No route to host | `unreachable` | "No route to host: nextcloud.example.com:443" |
| Timeout | `timeout` | "TCP connect timeout after 5s: nextcloud.example.com:443" |

### 3.3 TLSCheck

Establishes a TLS handshake and validates the server certificate chain.

**Input:** hostname, port
**Prerequisite:** TCPCheck must pass.

| Outcome | FailureClass | message example |
|---|---|---|
| TLS handshake ok, cert valid | `ok` | "TLS ok · cert expires 2027-01-01 (187 days)" |
| TLS handshake fails | `tls_failure` | "TLS handshake failed: SSL: CERTIFICATE_VERIFY_FAILED" |
| Certificate expired | `tls_failure` | "Certificate expired 3 days ago (2026-06-25)" |
| Certificate chain invalid | `tls_failure` | "Certificate chain validation failed" |
| Hostname mismatch | `tls_failure` | "Certificate CN mismatch: expected nextcloud.example.com" |

**Certificate expiry warning:** If `days_until_expiry < 30`, status is `WARN`, not `FAIL`.
The check still passes TLS but flags the upcoming expiry.

### 3.4 HTTPCheck

Sends an HTTP request to a known endpoint and validates the response.

**Input:** URL, expected status code, optional response validator
**Prerequisite:** TLSCheck must pass (or TCPCheck if not HTTPS).

| Outcome | FailureClass | message example |
|---|---|---|
| Status matches expected | `ok` | "GET /status.php → 200 (142ms)" |
| Unexpected status code | `invalid_response` | "GET /status.php → 503 (expected 200)" |
| Body validation fails | `invalid_response` | "Response body missing expected field 'status'" |
| Timeout | `timeout` | "HTTP request timeout after 10s" |
| Redirect loop | `invalid_response` | "Too many redirects (>10)" |

### 3.5 AuthCheck

Sends an authenticated request and validates the authentication result.

**Input:** URL, auth credentials (loaded from config — never passed as strings)
**Prerequisite:** HTTPCheck must pass (unauthenticated probe).

**Security:** Credentials are loaded from `SecretManager`. They are never included in
`HealthCheckResult.detail`. The `detail` field contains only the response metadata.

| Outcome | FailureClass | message example |
|---|---|---|
| Auth succeeds | `ok` | "Nextcloud OCS auth ok (user: admin)" |
| Wrong credentials | `unauthorized` | "HTTP 401: credentials rejected" |
| Access denied | `forbidden` | "HTTP 403: account exists but access denied" |
| Auth endpoint missing | `invalid_response` | "OCS API returned unexpected response" |

**Invariant:** `unauthorized` means the credentials were presented and rejected.
`dns_failure`, `tls_failure`, `timeout`, and `unreachable` are **never** returned by
`AuthCheck` — those are returned by the earlier checks in the chain. This ensures
that DNS or TLS failures cannot be misreported as credential failures.

### 3.6 DatabaseCheck

Verifies connectivity to the Beta PostgreSQL database.

**Input:** `BETA_DATABASE_URL` from config
**No prerequisite check** — DB connectivity uses a separate code path from the
integration services.

| Outcome | FailureClass | message example |
|---|---|---|
| Connection + query ok | `ok` | "PostgreSQL: connected (3ms)" |
| Connection refused | `unreachable` | "PostgreSQL: connection refused (postgres:5432)" |
| Auth failure | `unauthorized` | "PostgreSQL: authentication failed" |
| Timeout | `timeout` | "PostgreSQL: connect timeout after 5s" |
| Schema version check | `warn` | "PostgreSQL: pending migrations detected" |

### 3.7 StorageCheck

Validates the Beta storage path.

**Input:** `BETA_STORAGE_PATH`, `BETA_BACKUP_PATH` from config

| Outcome | status | message example |
|---|---|---|
| Path exists, readable, writable | `ok` | "/data/wooprice: readable, writable, 42.1GB free" |
| Path exists but not writable | `warn` | "/data/wooprice: not writable (permission denied)" |
| Path does not exist | `fail` | "/data/wooprice: path does not exist" |
| Disk space < 1GB | `warn` | "/data/wooprice: low disk space (0.8GB free)" |
| Disk space < 100MB | `fail` | "/data/wooprice: critically low disk space (50MB free)" |

### 3.8 DockerCheck (stub in CP1 — implemented in B6)

Verifies Docker socket availability and container status.

**CP1 behavior:** Returns `status=SKIP, message="Docker check not available in this phase"`.
**B6 behavior:** Checks socket, running containers, resource usage.

### 3.9 SchedulerCheck (stub in CP1 — implemented in B11)

Verifies that the scheduler worker process is alive and processing.

**CP1 behavior:** Returns `status=SKIP`.
**B11 behavior:** Checks worker process PID, queue depth, last-run timestamp.

### 3.10 PluginCheck (stub in CP1 — implemented in B14)

Verifies that installed plugins are valid and not quarantined.

**CP1 behavior:** Returns `status=SKIP`.
**B14 behavior:** Checks manifest validity, quarantine status, version compatibility.

---

## 4. Check Chains

For integration services, checks form a dependent chain. If a check in the chain fails,
all subsequent checks are skipped (status=SKIP) rather than run. This prevents a DNS
failure from being obscured by misleading downstream results.

### 4.1 Nextcloud Chain

```
DNSCheck("nextcloud.example.com")
  └── PASS → TCPCheck("nextcloud.example.com", 443)
                └── PASS → TLSCheck("nextcloud.example.com", 443)
                              └── PASS → HTTPCheck("https://nextcloud.example.com/status.php", 200)
                                            └── PASS → AuthCheck(nextcloud_credentials)
```

### 4.2 WooCommerce Chain

```
DNSCheck("shop.example.com")
  └── PASS → TCPCheck("shop.example.com", 443)
                └── PASS → TLSCheck("shop.example.com", 443)
                              └── PASS → HTTPCheck("https://shop.example.com/wp-json/wc/v3/", 200)
                                            └── PASS → AuthCheck(woocommerce_key_secret)
```

### 4.3 Currency API Chain

```
DNSCheck("alanchand.com")
  └── PASS → TCPCheck("alanchand.com", 443)
                └── PASS → TLSCheck("alanchand.com", 443)
                              └── PASS → HTTPCheck("https://alanchand.com/api/....", 200)
```
No `AuthCheck` for Currency API — it does not require authentication.

### 4.4 Local Checks (No Chain — Independent)

```
DatabaseCheck  (independent)
StorageCheck   (independent)
DockerCheck    (independent — stub in CP1)
SchedulerCheck (independent — stub in CP1)
```

---

## 5. Aggregation Rules

### 5.1 Per-Integration Status

The status of an integration is derived from its check chain result:

| Chain result | IntegrationState.status |
|---|---|
| All checks ok | `ok` |
| Any check returns WARN | `degraded` |
| Any check returns FAIL | `down` |
| No check has been run yet | `unknown` |

### 5.2 System-Level HealthLevel

`ControlPlaneStatus.overall_health` is derived from all integration states and local checks:

| Condition | HealthLevel |
|---|---|
| All checks ok | `ok` |
| Any integration is `down` but DB, storage, and local auth are `ok` | `degraded` |
| Database or storage is `fail` | `critical` |
| Local auth cannot be verified (JWT secret missing) | `critical` |

The `critical` level is reserved for failures that impair the Control Plane itself.
Integration failures never raise to `critical` — they stop at `degraded`.

---

## 6. Health Check Scheduling and Polling

### 6.1 Background Polling (B6+)

From B6 onward, the scheduler worker runs health checks on a configurable interval:

| Check group | Default interval | Configurable |
|---|---|---|
| Integration checks (Nextcloud, WooCommerce) | 60 seconds | Yes |
| Local checks (DB, storage) | 30 seconds | Yes |
| Docker check | 30 seconds | Yes (B6+) |

The latest `ControlPlaneStatus` is stored in-memory (CP1) and later in Redis (B6+).
Cache TTL is the polling interval × 2. Stale cache returns `unknown` status rather
than the last `ok` — it does not falsely report `ok` when data is stale.

**OD1 (CHAT2 decision — 2026-06-28):** In CP1, status cache is in-memory only.
Persistent cache (Redis) is introduced in B6 when the full Docker stack is available.

### 6.2 On-Demand Checks (CP1 and beyond)

Any check can be triggered on-demand from:
- CLI: `wooprice diagnostics run --target <service>`
- CLI: `wooprice integrations test <service>`
- API: `POST /api/v2/diagnostics/run`
- UI: "Test Connection" button (B8+)

On-demand checks bypass the cache and run immediately. Their results are written to
the cache but do not reset the polling timer.

### 6.3 CP1 Polling (before B6)

In CP1, there is no running Docker stack and no scheduler worker. Health checks are
**only triggered on-demand** via the CLI. Background polling begins in B6.

---

## 7. Health API Contract

**OD3 (CHAT2 decision — 2026-06-28):** The health API is split into two endpoints:
a public minimal endpoint (for Docker probes and monitoring tools) and an authenticated
full-detail endpoint. The public endpoint must never expose secrets, internal network
topology, credentials, or detailed failure traces.

### GET /api/health  (PUBLIC — no authentication required)

Returns only the minimum information needed for Docker health probes and external
uptime monitors. Must not expose any operational detail.

```json
{
  "status": "ok",
  "timestamp": "2026-06-28T10:30:00Z"
}
```

`status` is one of: `"ok"` | `"degraded"` | `"critical"`. No other fields.
No integration names, failure classes, topology, or credential information is included.

### GET /api/v2/health  (AUTHENTICATED — JWT required, any valid user)

Returns the full `ControlPlaneStatus` including per-service integration states and
feature availability. Available only to authenticated users.

```json
{
  "timestamp": "2026-06-28T10:30:00Z",
  "overall_health": "ok",
  "local_auth_available": true,
  "config_readable": true,
  "config_writable": true,
  "database_available": true,
  "storage_available": true,
  "integration_states": { "..." },
  "feature_availability": { "..." }
}
```

### POST /api/v2/health/check  (AUTHENTICATED — admin permission required)

Triggers an on-demand health check for a specific target or all targets.

```json
// Request
{"target": "nextcloud"}  // or "all" to run all checks

// Response
{
  "target": "nextcloud",
  "results": [
    {"check_name": "dns", "status": "fail", "failure_class": "dns_failure",
     "message": "Could not resolve nextcloud.example.com", "duration_ms": 5001},
    {"check_name": "tcp", "status": "skip", "skipped_because": "dns", "duration_ms": 0},
    {"check_name": "tls", "status": "skip", "skipped_because": "dns", "duration_ms": 0},
    {"check_name": "http", "status": "skip", "skipped_because": "dns", "duration_ms": 0},
    {"check_name": "auth", "status": "skip", "skipped_because": "dns", "duration_ms": 0}
  ],
  "overall": "down",
  "failure_class": "dns_failure",
  "checked_at": "2026-06-28T10:30:05Z"
}
```

---

## 8. CLI Integration

### wooprice health

```
$ python -m cli.main health

[BETA ENVIRONMENT]  WooPrice Beta — Health Check

Local checks:
  ✓  Config loaded and valid
  ✓  Storage path readable and writable (42.1GB free)
  ✓  Python 3.12.4 — required modules available
  ✗  Database: connection refused (postgres:5432) — docker not running

Integration checks (live — may take up to 30s):
  ✗  Nextcloud: dns_failure — Could not resolve nextcloud.example.com
  ✓  WooCommerce: ok (142ms)
  ✓  Currency API: ok (89ms)

Overall: DEGRADED
Run 'wooprice diagnostics run' for detailed repair suggestions.
```

### wooprice integrations test nextcloud

```
$ python -m cli.main integrations test nextcloud

[BETA ENVIRONMENT]  Integration Test — Nextcloud

  DNS    FAIL   dns_failure · Could not resolve nextcloud.example.com (5001ms)
  TCP    SKIP   (DNS failed)
  TLS    SKIP   (DNS failed)
  HTTP   SKIP   (DNS failed)
  Auth   SKIP   (DNS failed)

Result: DOWN · dns_failure

Probable cause:  The hostname "nextcloud.example.com" does not resolve.
                 Either the hostname is incorrect or DNS is misconfigured.

Suggested steps:
  1. Verify the Nextcloud URL: wooprice configure show | grep nextcloud
  2. Update if incorrect:      wooprice configure set nextcloud.url https://new-url.example.com
  3. Check server DNS:         Run 'nslookup nextcloud.example.com' on the server
  4. Retest after changes:     wooprice integrations test nextcloud
```
