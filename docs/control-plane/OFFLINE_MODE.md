# WooPrice Beta — Offline Mode (Degraded Mode)

**Document:** OFFLINE_MODE.md
**Series:** CP1 Architecture Specification
**Status:** CHAT2 APPROVED with modifications — 2026-06-28. Specification complete. READY FOR OWNER REVIEW. No implementation has begun.

---

## 1. Overview

Offline Mode (also called Degraded Mode) is the operational state in which one or more
Integration Plane services are unavailable. During Offline Mode:

- The Control Plane remains **fully operational**.
- Integration Plane features are **disabled with visible failure information**.
- The administrator is **guided toward recovery** through the UI, CLI, and diagnostics.

Offline Mode is not an error state — it is an expected and designed operational mode
that must be handled gracefully rather than propagating as a system-wide failure.

---

## 2. Degraded Mode Triggers

The system enters Degraded Mode when `ControlPlaneService.get_status()` returns
`overall_health = HealthLevel.DEGRADED`. This occurs when:

| Trigger | Classification |
|---|---|
| Integration service DNS resolution fails | `dns_failure` |
| Integration service TLS handshake fails | `tls_failure` |
| Integration service connection times out | `timeout` |
| Integration service rejects credentials | `unauthorized` |
| Integration service denies access | `forbidden` |
| Integration service connection refused | `unreachable` |
| Integration service returns unexpected content | `invalid_response` |

Degraded Mode does **not** trigger when:
- The Control Plane database is temporarily unavailable → this is `HealthLevel.CRITICAL`
  (different handling; see Section 7)
- A health check is simply not yet run → status is `unknown` (not degraded)

---

## 3. Surface Availability Matrix

### 3.1 Always Available (Control Plane)

These surfaces must never become unavailable due to integration failures.

| Surface | Phase | Availability guarantee |
|---|---|---|
| Login (local) | B7 | Always. JWT verified against local DB. |
| Settings viewer | B8 | Always. Reads local config. |
| Runtime Config editor | B8 | Always. Reads/writes local TOML. |
| Diagnostics runner | CP1 (CLI), B8 (UI) | Always. Runs local + network checks. |
| Health Dashboard | B8 | Always. Displays status from last check run. |
| Logs viewer | B8 | Always. Reads local log files. |
| Admin panel | B13 | Always. Reads local DB. |
| Feature flags manager | B13 | Always. Reads local DB. |
| Plugin manager | B14 | Always. Reads local plugin registry. |
| Backup / Restore | B15 | Always. Reads/writes local storage. |
| Update controls | B15 | Always. Reads/writes local storage. |
| Audit log | B13 | Always. Reads local log files. |

### 3.2 Disabled During Integration Outage (Integration Plane)

These surfaces are disabled (not hidden) when their required integrations are down.

| Surface | Required integration | Failure behavior |
|---|---|---|
| Product Explorer | Nextcloud + WooCommerce | Disabled; shows failure class; shows repair link |
| Source Explorer | Nextcloud | Disabled; shows failure class; shows repair link |
| Change Sets | WooCommerce | Disabled; shows failure class |
| Dry Run Viewer | Nextcloud + WooCommerce | Disabled; shows failure class |
| Execution Viewer | WooCommerce | Disabled; shows failure class |
| Scheduler Viewer | WooCommerce (for apply) | Read-only view of schedule list available; run trigger disabled |
| AI Insights Viewer | Database only | Available (no external dependency) |

### 3.3 Partially Available During Integration Outage

| Surface | Behavior |
|---|---|
| Scheduler Viewer | Schedule list and history are readable. "Run Now" button disabled. |
| Product list (cached) | Cached product data is readable. Refresh from WooCommerce disabled. |

---

## 4. Banner Specification

The Offline Banner is displayed at the top of every page when
`ControlPlaneStatus.overall_health == HealthLevel.DEGRADED`.

### 4.1 Banner Layout

```
┌──────────────────────────────────────────────────────────────────────────┐
│ [⚠ DEGRADED]  1 service unavailable: Nextcloud  ·  dns_failure          │
│               Admin features remain fully available.                      │
│               [Run Diagnostics]  [Edit Configuration]  [Dismiss ▾]      │
└──────────────────────────────────────────────────────────────────────────┘
```

For multiple failures:
```
┌──────────────────────────────────────────────────────────────────────────┐
│ [⚠ DEGRADED]  2 services unavailable: Nextcloud (dns_failure),          │
│               WooCommerce (tls_failure)                                   │
│               Admin features remain fully available.                      │
│               [Run Diagnostics]  [Edit Configuration]  [Dismiss ▾]      │
└──────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Banner Rules

- The banner is shown on **every page** when any integration service is down.
- It is **not** dismissable permanently — it returns on the next page navigation if
  the outage is still active.
- The Dismiss button hides it for the current page view only.
- The banner never obscures or replaces Control Plane surfaces.
- The banner color is orange (warning) for `DEGRADED`, red for `CRITICAL`.
- The failure class label is always shown verbatim (`dns_failure`, `tls_failure`, etc.),
  never replaced with a user-friendly synonym.

### 4.3 Banner in CRITICAL State

When `overall_health == HealthLevel.CRITICAL` (Control Plane database or storage down):

```
┌──────────────────────────────────────────────────────────────────────────┐
│ [✗ CRITICAL]  Control Plane database unavailable. Application is         │
│               non-functional until the database is restored.              │
│               [Run Diagnostics]                                           │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Menu Visibility Rules

### 5.1 Control Plane Items (Sidebar)

Control Plane sidebar items are **always visible and always clickable**, regardless of
integration health. They are not greyed out, not hidden, and not disabled.

Items: Dashboard, Settings, Diagnostics, Logs, Admin, Feature Flags, Plugins, Backup.

### 5.2 Integration Plane Items (Sidebar)

Integration Plane sidebar items follow these rules:

| Integration health | Display |
|---|---|
| `ok` | Visible, clickable |
| `degraded` or `down` | Visible, **disabled** (greyed out), with ⚠ icon |
| `unknown` (not yet checked) | Visible, clickable with a "loading" indicator |

Clicking a **disabled** Integration Plane item shows a tooltip:

```
Nextcloud is currently unreachable (dns_failure).
Go to Diagnostics → Run Check → Edit Configuration to repair.
```

Items are **never hidden** when disabled. Hiding disabled items is confusing because
the administrator needs to know that those features exist and are temporarily unavailable.

---

## 6. Page-Level Degraded Indicators

### 6.1 Disabled Feature Page

When an administrator navigates to a disabled Integration Plane page (e.g., typing
the URL directly), the page renders a degraded-mode panel instead of the normal content:

```
┌──────────────────────────────────────────────────────────────────────────┐
│                     Product Explorer — UNAVAILABLE                        │
│                                                                           │
│  Nextcloud cannot be reached.                                             │
│  Failure class: dns_failure                                               │
│                                                                           │
│  This feature requires Nextcloud to be reachable.                        │
│  Other administrative features remain fully available.                    │
│                                                                           │
│  Suggested steps:                                                         │
│  1. Check Nextcloud hostname resolves correctly                           │
│  2. Verify network connectivity from the server                           │
│  3. Update the Nextcloud URL if it has changed                            │
│                                                                           │
│  [Run Diagnostics]   [Edit Nextcloud Configuration]                      │
└──────────────────────────────────────────────────────────────────────────┘
```

### 6.2 Stale Data Indicator

When cached data is displayed but the integration is unavailable:

```
[⚠ Data from cache · Nextcloud unreachable (dns_failure) · Last updated: 3 hours ago]
```

---

## 7. Session Continuity

Existing logged-in sessions are **not interrupted** by integration failures. Specifically:

- JWT token validation is local. An integration outage does not invalidate existing tokens.
- The access token and refresh token lifecycle continues normally during outages.
- Administrators who are already logged in retain full Control Plane access.
- New logins during an outage succeed because local auth is independent of integrations.

---

## 8. Recovery Workflow

The recovery workflow guides the administrator from failure detection to confirmed recovery.

### 8.1 Recovery Steps (UI)

```
Step 1: Detect
  Banner shows: "Nextcloud unreachable — dns_failure"
  Sidebar item: Products shows ⚠ disabled

Step 2: Diagnose
  [Run Diagnostics] button opens Diagnostics page
  DiagnosticRunner runs the Nextcloud check chain:
    DNS → FAIL (dns_failure · "Could not resolve nextcloud.example.com")
    TCP → SKIP (DNS failed; TCP not attempted)
    TLS → SKIP (DNS failed; TLS not attempted)
    HTTP → SKIP (DNS failed; HTTP not attempted)
    Auth → SKIP (DNS failed; Auth not attempted)

  Report shows:
    Probable cause: "Hostname nextcloud.example.com does not resolve."
    Suggested repair: "Verify the Nextcloud URL is correct and that DNS
                       is configured on this server. If the URL has changed,
                       update it using 'Edit Configuration'."

Step 3: Repair
  [Edit Nextcloud Configuration] opens Runtime Config editor
  Administrator updates BETA_NEXTCLOUD_URL or reviews DNS config
  Administrator saves the change (writes to managed TOML; triggers
  ConfigurationManager reload; secrets in .env unchanged)

Step 4: Verify
  [Re-run Check] button on Diagnostics page
  DiagnosticRunner reruns the Nextcloud chain
  If all checks pass: green ✓ for Nextcloud
  Banner disappears (on next health poll or manual refresh)
  Sidebar item becomes clickable again

Step 5: Confirmed
  ControlPlaneStatus.overall_health returns to HealthLevel.OK
```

### 8.2 Recovery via CLI

```bash
# View current status
wooprice control-plane status

# Run full diagnostics
wooprice diagnostics run

# Run diagnostics for a specific integration
wooprice diagnostics run --target nextcloud

# Edit the Nextcloud URL
wooprice configure set nextcloud.url https://new-nextcloud.example.com

# Re-test after repair
wooprice integrations test nextcloud
```

### 8.3 Recovery Timing

The health check polling interval (defined in `HEALTH_ENGINE.md`) determines how
quickly the UI reflects recovery without manual intervention. Recovery detection does
not require the administrator to refresh the page — the health status is pushed via
the existing SSE infrastructure once the check passes.

---

## 9. CLI Offline Behavior

### 9.1 Commands That Must Work Offline (Zero Network)

These CLI commands must succeed even when no network is available and no Docker
containers are running:

| Command | Why offline-safe |
|---|---|
| `wooprice configure show` | Reads local TOML + env |
| `wooprice configure verify` | B3 ConfigValidator; local only |
| `wooprice configure set <key> <value>` | Writes local TOML |
| `wooprice status` | Reads local config state |
| `wooprice health local` | Python + config + storage; no network |
| `wooprice diagnostics run --local-only` | B4 prerequisites + config validity |
| `wooprice control-plane status` | Reads last cached ControlPlaneStatus from local store |

### 9.2 Commands That Require Network

These commands attempt network connections and must report failure classes on failure:

| Command | Network dependency | Failure behavior |
|---|---|---|
| `wooprice health sources` | Nextcloud | Reports `dns_failure`, `tls_failure`, etc. |
| `wooprice health channels` | WooCommerce | Reports failure class |
| `wooprice integrations test nextcloud` | Nextcloud | Reports full chain result |
| `wooprice integrations test woocommerce` | WooCommerce | Reports full chain result |
| `wooprice diagnostics run` | All integrations | Reports per-integration results |

Network-dependent commands must never hang indefinitely. Each must apply the timeout
policy from `ConnectionManager` and report `timeout` if exceeded.

---

## 10. API Contract (for B8 UI)

**OD3 (CHAT2 decision — 2026-06-28):** Health API is split into two endpoints.
The public endpoint exposes only `status` (ok/degraded/critical). Detailed operational
information — integration states, feature availability, failure classes — is available
only on authenticated endpoints and must never appear on the public endpoint.

### GET /api/health  (PUBLIC)

Returns minimal health for Docker probes and monitoring tools. No failure detail.

```json
{"status": "degraded", "timestamp": "2026-06-28T10:30:00Z"}
```

### GET /api/v2/control-plane/status  (AUTHENTICATED)

Returns the current `ControlPlaneStatus` and `FeatureAvailability`.
Called by the frontend on mount and on polling interval.

**No authentication bypass:** This endpoint requires a valid JWT. It is not public.
If the user cannot authenticate (e.g., token expired during outage), they must log in
again using local credentials.

**Response schema:**

```json
{
  "timestamp": "2026-06-28T10:30:00Z",
  "overall_health": "degraded",
  "local_auth_available": true,
  "config_readable": true,
  "config_writable": true,
  "database_available": true,
  "storage_available": true,
  "integration_states": {
    "nextcloud": {
      "service_name": "nextcloud",
      "status": "down",
      "failure_class": "dns_failure",
      "failure_message": "Could not resolve hostname: nextcloud.example.com",
      "last_check_at": "2026-06-28T10:29:55Z",
      "last_ok_at": "2026-06-28T08:00:00Z",
      "latency_ms": null,
      "endpoint_url": "https://nextcloud.example.com"
    },
    "woocommerce": {
      "service_name": "woocommerce",
      "status": "ok",
      "failure_class": "ok",
      "failure_message": null,
      "last_check_at": "2026-06-28T10:29:55Z",
      "last_ok_at": "2026-06-28T10:29:55Z",
      "latency_ms": 142.3,
      "endpoint_url": "https://shop.example.com"
    }
  },
  "feature_availability": {
    "login": "available",
    "settings": "available",
    "runtime_config": "available",
    "diagnostics": "available",
    "health_dashboard": "available",
    "logs_viewer": "available",
    "admin_panel": "available",
    "feature_flags": "available",
    "plugin_manager": "available",
    "backup_restore": "available",
    "product_explorer": "disabled",
    "source_explorer": "disabled",
    "change_sets": "available",
    "dry_run": "disabled",
    "execution": "available",
    "scheduler": "available",
    "ai_insights": "available"
  }
}
```
