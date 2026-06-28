# WooPrice Beta — Diagnostics Architecture

**Document:** DIAGNOSTICS_ARCHITECTURE.md
**Series:** CP1 Architecture Specification
**Status:** SPECIFICATION — awaiting CHAT2 review. No implementation has begun.

---

## 1. Overview

The Diagnostics subsystem is the operator's primary tool for understanding system
health, classifying failures, and determining repair actions. Unlike a simple health
check (pass/fail), diagnostics produce:

- Failure classification with exact failure class
- Severity rating
- Probable cause inference
- Suggested repair steps (ranked by likelihood)
- Machine-readable structured output (JSON)
- Audit history of all diagnostic runs

The Diagnostics subsystem lives in `app/beta/diagnostics/` and is exposed through:
- CLI: `wooprice diagnostics run`
- API: `POST /api/v2/diagnostics/run`
- UI: Diagnostics page (B8+)

---

## 2. Diagnostic Categories

The DiagnosticRunner runs checks organized into 10 categories. Categories run in
dependency order. Within a category, checks run sequentially (chain) or in parallel
(independent).

### Category 1: Local Environment

**Purpose:** Verify the basic runtime requirements before any integration check.
**Network required:** No. Fully offline-safe.

| Check | Description |
|---|---|
| Python version | Must be 3.12+ |
| Required modules | All imports in `cli/` and `app/beta/` must resolve |
| Config loaded | B3 `ConfigurationManager.load()` succeeds |
| Config valid | B3 `ConfigValidator.validate()` returns 0 errors |
| Secret fields set | All 6 secret fields in `.env` are present (not blank) |

### Category 2: Storage

**Purpose:** Verify that persistent storage is available and healthy.
**Network required:** No.

| Check | Description |
|---|---|
| Storage path exists | `BETA_STORAGE_PATH` exists on filesystem |
| Storage readable | Read test on `BETA_STORAGE_PATH` |
| Storage writable | Write test (creates and deletes a temp file) |
| Storage disk space | Available bytes; warns below 1GB; fails below 100MB |
| Backup path exists | `BETA_BACKUP_PATH` exists |
| Backup path writable | Write test |
| Log directory | `$BETA_STORAGE_PATH/logs` exists and writable |
| Config directory | `$BETA_STORAGE_PATH/config` exists and writable |

### Category 3: Database

**Purpose:** Verify PostgreSQL connectivity and schema state.
**Network required:** Docker internal network only (not external internet).
**B6 prerequisite:** Database container must be running. In CP1, this category
returns `SKIP` with message "Database not running in this phase."

| Check | Description |
|---|---|
| TCP connect | Can reach postgres:5432 |
| Authentication | Credentials accepted |
| Query | Simple SELECT 1 succeeds |
| Schema version | Current migration version matches expected |
| Pending migrations | No unapplied migrations |
| Table existence | Required Beta tables exist |

### Category 4: Nextcloud Integration

**Purpose:** Classify the Nextcloud failure chain.
**Network required:** Yes — external network to Nextcloud host.

Runs the full check chain: DNS → TCP → TLS → HTTP → Auth (see HEALTH_ENGINE.md §4.1).
Each check in the chain is shown individually in the report.

### Category 5: WooCommerce Integration

**Purpose:** Classify the WooCommerce failure chain.
**Network required:** Yes — external network to WooCommerce host.

Runs the full check chain: DNS → TCP → TLS → HTTP → Auth (see HEALTH_ENGINE.md §4.2).

### Category 6: Currency API Integration

**Purpose:** Verify the currency rate provider is reachable.
**Network required:** Yes.

Runs: DNS → TCP → TLS → HTTP (no auth required).

### Category 7: TLS and Certificate Health

**Purpose:** Report on TLS certificate expiry for all integration endpoints.
**Network required:** Yes — TLS handshake required per endpoint.

| Check | Description |
|---|---|
| Nextcloud cert expiry | Days until expiry; warn if < 30; fail if expired |
| WooCommerce cert expiry | Same |
| Currency API cert expiry | Same |
| Nextcloud cert chain | Full chain validation (not just leaf cert) |
| WooCommerce cert chain | Same |

### Category 8: Docker Runtime

**Purpose:** Verify Docker stack health.
**CP1 behavior:** All checks return `SKIP, message="Docker check not available in this phase"`.
**B6 behavior:** Implemented fully.

| Check | Description (B6+) |
|---|---|
| Docker socket | Socket accessible at `/var/run/docker.sock` |
| Container: app | Running + healthy |
| Container: worker | Running + healthy |
| Container: postgres | Running + healthy |
| Container: redis | Running + healthy |
| Container: nginx | Running + healthy |
| Resource usage | CPU/RAM per container within configured limits |

### Category 9: Scheduler

**CP1 behavior:** Returns `SKIP`.
**B11 behavior:** Checks worker process PID, queue depth, last-run timestamp, stuck schedule detection.

### Category 10: Plugins

**CP1 behavior:** Returns `SKIP`.
**B14 behavior:** Checks manifest validity for all installed plugins, quarantine status,
version compatibility, declared permission consistency.

---

## 3. DiagnosticReport Schema

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


class DiagnosticStatus(str, Enum):
    OK      = "ok"
    WARN    = "warn"
    FAIL    = "fail"
    SKIP    = "skip"


class Severity(str, Enum):
    INFO     = "info"
    WARNING  = "warning"
    ERROR    = "error"
    CRITICAL = "critical"


@dataclass
class RepairStep:
    step: int
    action: str              # what to do
    command: Optional[str]   # CLI command if applicable (never a destructive command)
    url: Optional[str]       # UI route if applicable


@dataclass
class DiagnosticCheckResult:
    """Wraps HealthCheckResult with diagnostics-specific fields."""
    check_name: str
    status: DiagnosticStatus
    failure_class: Optional[FailureClass]
    message: str
    detail: dict
    duration_ms: float
    skipped_because: Optional[str]


@dataclass
class DiagnosticCategory:
    category_name: str
    status: DiagnosticStatus
    severity: Severity
    checks: list[DiagnosticCheckResult]
    summary: str                        # one-line human summary
    probable_cause: Optional[str]       # inferred cause
    suggested_repairs: list[RepairStep] # ranked by likelihood
    skipped: bool = False
    skip_reason: Optional[str] = None


@dataclass
class DiagnosticReport:
    run_id: str                         # UUID
    triggered_by: str                   # "cli" or "api:<user_email>" or "scheduler"
    triggered_at: datetime
    completed_at: datetime
    duration_ms: float
    overall_status: DiagnosticStatus
    overall_severity: Severity
    categories: list[DiagnosticCategory]
    failure_summary: list[str]          # list of one-line failure descriptions
    repair_priority: list[str]          # category names in repair priority order
    machine_readable: dict              # full JSON-serializable structure
```

---

## 4. Failure Classification Table

The following table defines the canonical mapping from failure class to probable
cause and suggested repair.

| FailureClass | Probable cause | Suggested repair |
|---|---|---|
| `dns_failure` | Hostname does not resolve — either the URL is wrong or DNS is misconfigured on the server | 1. Verify URL is correct in configuration. 2. Run `nslookup <hostname>` on the server. 3. Check `/etc/resolv.conf` or DNS server reachability. |
| `tls_failure` | TLS certificate is invalid, expired, or the server has a misconfigured certificate | 1. Check certificate expiry on the server. 2. Verify the correct CA bundle is installed. 3. If using self-signed cert, verify it is in the trusted store. |
| `timeout` | The server is reachable at the TCP level but not responding — may be overloaded, firewall-filtered, or in a restart | 1. Try the request manually with curl. 2. Increase timeout value in configuration. 3. Check server load and logs. |
| `unauthorized` | Credentials are incorrect or the account is locked/expired | 1. Verify credentials in `.env`. 2. Test login manually in a browser. 3. Check if the account is active and unlocked. |
| `forbidden` | Credentials are correct but the account lacks required permissions | 1. Check account permissions on the external service. 2. Verify the account has admin or API access. |
| `unreachable` | TCP connection refused — server may be down, firewall may be blocking, or wrong port | 1. Verify the server is running. 2. Check firewall rules between the app server and the external service. 3. Verify the port in the URL is correct. |
| `invalid_response` | The server responded but with an unexpected format or status code | 1. Test the URL manually with curl. 2. Check if the service has been updated and the API path has changed. 3. Check the service's own error logs. |

---

## 5. Severity Model

Severity determines how urgently the administrator should act.

| Severity | Meaning | Visual |
|---|---|---|
| `info` | Informational; no action required | Blue ℹ |
| `warning` | Something is suboptimal but the system is functional | Orange ⚠ |
| `error` | A feature or integration is not working | Red ✗ |
| `critical` | The Control Plane or core infrastructure is impaired | Red ✗ (pulsing) |

### Severity Assignment Rules

| Condition | Severity |
|---|---|
| All categories OK | `info` |
| Certificate expiry < 30 days | `warning` |
| Disk space < 1GB | `warning` |
| Pending DB migrations | `warning` |
| Any integration `down` (nextcloud, woocommerce) | `error` |
| Database unavailable | `critical` |
| Storage unavailable | `critical` |
| Config invalid (missing required variables) | `critical` |
| Local auth unavailable | `critical` |

---

## 6. Probable Cause Inference

The DiagnosticRunner infers the probable cause by examining the failure chain
and applying a priority ruleset.

```python
class ProbableCauseInferrer:
    def infer(self, category: str, checks: list[DiagnosticCheckResult]) -> Optional[str]:
        # Rule 1: If DNS fails, root cause is DNS — not TLS, not auth.
        if any_failed_with(checks, "dns", FailureClass.DNS_FAILURE):
            return f'Hostname "{hostname}" does not resolve. ' \
                   f'The URL may be incorrect or the server\'s DNS is misconfigured.'

        # Rule 2: If TCP succeeds but TLS fails, root cause is TLS.
        if all_passed(checks, ["dns", "tcp"]) and any_failed_with(checks, "tls", FailureClass.TLS_FAILURE):
            return 'TCP connection succeeded but TLS handshake failed. ' \
                   'The server\'s certificate may be expired, self-signed without trust, or misconfigured.'

        # Rule 3: If TLS succeeds but HTTP fails, root cause is HTTP.
        if all_passed(checks, ["dns", "tcp", "tls"]) and any_failed(checks, "http"):
            return 'TLS succeeded but the HTTP probe returned an unexpected response. ' \
                   'The service may be running but responding with errors.'

        # Rule 4: If HTTP succeeds but Auth fails with unauthorized, root cause is credentials.
        if all_passed(checks, ["dns", "tcp", "tls", "http"]) and \
                any_failed_with(checks, "auth", FailureClass.UNAUTHORIZED):
            return 'The connection succeeded but credentials were rejected (HTTP 401). ' \
                   'The username or password in .env may be incorrect or the account is locked.'

        return None  # No specific cause inferred
```

---

## 7. Machine-Readable Output

CLI output includes a JSON dump when `--json` flag is used. This enables integration
with monitoring systems and automated repair scripts.

```bash
$ python -m cli.main diagnostics run --json
```

```json
{
  "run_id": "d4a2e1f0-...",
  "triggered_by": "cli",
  "triggered_at": "2026-06-28T10:30:00Z",
  "completed_at": "2026-06-28T10:30:05Z",
  "duration_ms": 5123,
  "overall_status": "fail",
  "overall_severity": "error",
  "failure_summary": [
    "nextcloud: dns_failure — Could not resolve nextcloud.example.com"
  ],
  "repair_priority": ["nextcloud"],
  "categories": [
    {
      "category_name": "local_environment",
      "status": "ok",
      "severity": "info",
      "summary": "All local environment checks passed",
      "probable_cause": null,
      "suggested_repairs": []
    },
    {
      "category_name": "nextcloud",
      "status": "fail",
      "severity": "error",
      "summary": "Nextcloud unreachable — dns_failure",
      "probable_cause": "Hostname 'nextcloud.example.com' does not resolve.",
      "suggested_repairs": [
        {"step": 1, "action": "Verify the Nextcloud URL is correct",
         "command": "wooprice configure get nextcloud.url"},
        {"step": 2, "action": "Update the URL if incorrect",
         "command": "wooprice configure set nextcloud.url https://correct-url.example.com"},
        {"step": 3, "action": "Check DNS on the server",
         "command": null}
      ]
    }
  ]
}
```

---

## 8. Audit History

Every diagnostic run is written to the audit log.

```json
{
  "event": "diagnostics_run",
  "run_id": "d4a2e1f0-...",
  "triggered_by": "cli",
  "triggered_at": "2026-06-28T10:30:00Z",
  "duration_ms": 5123,
  "overall_status": "fail",
  "failure_classes": ["dns_failure"],
  "categories_failed": ["nextcloud"]
}
```

Diagnostic run results are stored in `$BETA_STORAGE_PATH/diagnostics/` as
timestamped JSON files. Retention: 30 days (configured by `BETA_BACKUP_RETAIN_DAYS`).
The CLI can list previous runs:

```bash
$ python -m cli.main diagnostics history
  2026-06-28 10:30:05  FAIL    nextcloud:dns_failure
  2026-06-28 09:15:12  OK      all checks passed
  2026-06-27 22:00:00  WARN    nextcloud:tls (cert expiry in 28 days)
```

---

## 9. CLI Output (Human-Readable)

```
$ python -m cli.main diagnostics run

[BETA ENVIRONMENT]  WooPrice Beta — Diagnostics

─────────────────────────────────────────────────────────────
Category 1: Local Environment                          ✓  OK
─────────────────────────────────────────────────────────────
  ✓  Python 3.12.4 — OK
  ✓  Required modules — all present
  ✓  Configuration loaded — 22 required variables present
  ✓  Configuration valid — 0 errors
  ✓  Secrets — all 6 secret fields set

─────────────────────────────────────────────────────────────
Category 2: Storage                                    ✓  OK
─────────────────────────────────────────────────────────────
  ✓  /data/wooprice — readable, writable (42.1 GB free)
  ✓  /data/wooprice/backup — readable, writable
  ✓  /data/wooprice/logs — readable, writable
  ✓  /data/wooprice/config — readable, writable

─────────────────────────────────────────────────────────────
Category 3: Database                                   —  SKIP
─────────────────────────────────────────────────────────────
  —  Database check not available in this phase (B6+)

─────────────────────────────────────────────────────────────
Category 4: Nextcloud Integration                      ✗  FAIL
─────────────────────────────────────────────────────────────
  ✗  DNS   dns_failure  Could not resolve nextcloud.example.com (5001ms)
  —  TCP   SKIP  (DNS failed — not attempted)
  —  TLS   SKIP  (DNS failed — not attempted)
  —  HTTP  SKIP  (DNS failed — not attempted)
  —  Auth  SKIP  (DNS failed — not attempted)

  Probable cause: Hostname "nextcloud.example.com" does not resolve.
                  The URL may be incorrect or DNS is misconfigured on this server.

  Suggested repair:
    1. Verify the URL:    wooprice configure get nextcloud.url
    2. Update if wrong:   wooprice configure set nextcloud.url https://correct-url.example.com
    3. Check DNS manually on the server

─────────────────────────────────────────────────────────────
Category 5: WooCommerce Integration                    ✓  OK
─────────────────────────────────────────────────────────────
  ✓  DNS    nextcloud.example.com → 203.0.113.1 (12ms)
  ✓  TCP    shop.example.com:443 connected (8ms)
  ✓  TLS    valid · expires 2027-06-01 (338 days) (31ms)
  ✓  HTTP   GET /wp-json/wc/v3/ → 200 (142ms)
  ✓  Auth   WooCommerce API authenticated (156ms)

─────────────────────────────────────────────────────────────
Overall: FAIL (severity: error)
─────────────────────────────────────────────────────────────
  ✗ 1 integration unreachable: Nextcloud (dns_failure)

  Repair priority:
    1. Repair Nextcloud connection (dns_failure)

Run 'wooprice diagnostics run --json' for machine-readable output.
Report saved: /data/wooprice/diagnostics/2026-06-28T10-30-05Z.json
```

---

## 10. API Contract (B8 UI)

### POST /api/v2/diagnostics/run

Triggers a full diagnostic run. Admin permission required. Returns immediately with
a `run_id`; results are available via SSE stream or polling.

```json
// Request
{"target": "all"}  // or specific category: "nextcloud", "storage", etc.

// Immediate response
{"run_id": "d4a2e1f0-...", "status": "running", "stream_url": "/api/v2/diagnostics/d4a2e1f0-.../stream"}
```

### GET /api/v2/diagnostics/{run_id}

Returns the completed `DiagnosticReport`.

### GET /api/v2/diagnostics/history

Returns the last N diagnostic runs (default 20).

```json
{
  "runs": [
    {"run_id": "d4a2e1f0", "triggered_at": "...", "overall_status": "fail",
     "failure_summary": ["nextcloud: dns_failure"]},
    {"run_id": "c3b1d0e9", "triggered_at": "...", "overall_status": "ok",
     "failure_summary": []}
  ]
}
```
