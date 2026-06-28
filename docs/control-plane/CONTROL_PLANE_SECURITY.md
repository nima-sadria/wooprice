# WooPrice Beta — Control Plane Security

**Document:** CONTROL_PLANE_SECURITY.md
**Series:** CP1 Architecture Specification
**Status:** CHAT2 APPROVED with modifications — 2026-06-28. Specification complete. READY FOR OWNER REVIEW. No implementation has begun.

---

## 1. Overview

CP1 introduces security-critical architectural boundaries between the Control Plane
and external services. This document defines those boundaries, the authentication
invariants that CP1 establishes, and the security requirements for runtime
configuration and diagnostics.

CP1 does not implement the authentication system (that is B7). CP1 establishes the
**security principles and boundaries** that B7 must implement. Any B7 implementation
that contradicts this document requires Owner approval.

---

## 2. Core Security Invariants

### I1 — Local Authentication Is Always Available

JWT token validation must use `BETA_JWT_SECRET` and the local Beta user database only.
No token validation step may contact Nextcloud, WooCommerce, or any external service.

**Consequence:** An administrator can always log in if:
- The application server is running
- The database is accessible
- The credentials are correct (verified against the local user table)

External service availability has **zero effect** on login success or failure.

### I2 — External Auth Failures Never Collapse to "Invalid Credentials"

If an external authentication integration (Nextcloud OCS, future OAuth provider,
future LDAP) is configured and fails, the failure must be reported with the exact
failure class. It must never be collapsed to "Invalid credentials" or "Login failed."

This invariant applies to all layers:
- Backend service
- API response body
- CLI output
- UI display

### I3 — External Auth Is Optional and Must Fail Safely

If Nextcloud authentication integration (future feature, not in CP1 or B7) is
configured and enabled, its failure must not block local admin login. The failure
is surfaced as an integration failure, and local login remains available.

### I4 — Control Plane Endpoints Require Local JWT Only

All Control Plane API endpoints are protected by local JWT validation.
No Control Plane endpoint may require a second factor that depends on an external service
(e.g., "also verify against Nextcloud before allowing settings access").

### I5 — Configuration Changes Are Always Audited

Every write to the managed TOML config file, every Runtime Config API call, and every
`wooprice configure set` invocation must produce an audit log entry. The audit log
must be written before the change is considered complete.

---

## 3. Authentication Boundary Design

### 3.1 What Is Local Auth

Local auth uses the `BetaUser` table in the Beta config database (SQLite/PostgreSQL).
Every administrator and user has:
- `email` — login identifier
- `password_hash` — bcrypt-hashed password stored locally
- `is_admin` — boolean admin flag
- `permissions` — set of named permissions
- `is_active` — boolean account active flag

Login: `POST /api/auth/login` receives `{email, password}`. The backend:
1. Looks up `BetaUser` by email.
2. Verifies `password` against `password_hash` using bcrypt.
3. If match and `is_active=True`: issues JWT (access token + refresh token).
4. If no match: returns HTTP 401 with `{"error": "invalid_credentials"}`.
5. At no point does step 4 contact any external service.

### 3.2 What Is Explicitly Forbidden

- Verifying the user's local password against Nextcloud at any point during the
  login flow. (This was the production WooPrice 7.5A failure mode.)
- Caching or proxying Nextcloud credentials for local login purposes.
- Using the JWT secret from the production WooPrice system (that's `JWT_SECRET`, not
  `BETA_JWT_SECRET` — they are different keys and must never be shared).
- Delegating the login decision to any external auth provider as the primary path.

### 3.3 Future External Auth (Post-B7)

If Nextcloud SSO, OAuth 2.0, or LDAP authentication is added in a future phase:

- It must be implemented as an **optional, additive** login flow alongside local auth.
- Local login must remain available when external auth is disabled or failing.
- External auth failure must surface with the exact failure class (not "Login failed").
- The feature flag `FEATURE_EXTERNAL_AUTH` must gate external auth — it is off by default.

This is an architectural constraint, not a B7 scope item.

---

## 4. Secret Handling in CP1

### 4.1 Secrets Never Pass Through RuntimeConfigService

`RuntimeConfigService` must not set, get, store, log, or return any secret value.
The protected secret list (from B3 `SECRET_FIELDS`):

```
BETA_JWT_SECRET
BETA_REST_API_SECRET
BETA_POSTGRES_PASSWORD
BETA_NEXTCLOUD_PASSWORD
BETA_WOOCOMMERCE_KEY
BETA_WOOCOMMERCE_SECRET
```

If a caller attempts to `RuntimeConfigService.set("BETA_NEXTCLOUD_PASSWORD", value)`,
the service must raise `ProtectedKeyError` and write an audit log entry for the
attempt.

### 4.2 Secrets Never Appear in HealthCheckResult

The `HealthCheckResult.detail` field must never contain credentials. The `AuthCheck`
loads credentials from `SecretManager` and uses them in the request; the resulting
`detail` contains only response metadata (status code, response time, OCS statuscode).

### 4.3 Secrets Never Appear in DiagnosticReport

The `DiagnosticReport` produced by `DiagnosticRunner` must never contain secrets.
The `detail` fields of all checks are scrubbed before the report is serialized.
The scrubbing function is the same as B3's `redact_env_dict` extended to TOML values.

### 4.4 Secrets Never Appear in Audit Log

Audit log entries for config changes include the key and the new value. For secret
keys (as defined by `SECRET_FIELDS`), the value is always `[REDACTED]`.
For non-secret keys (URLs, timeouts), the value is logged in full.

### 4.5 AuthCheck Credential Access Pattern

```python
class AuthCheck:
    def __init__(self, service: ServiceName, secret_manager: SecretManager):
        self._service = service
        self._secret_manager = secret_manager

    async def run(self, url: str) -> HealthCheckResult:
        # Credentials loaded here — never stored as instance variables
        credentials = self._secret_manager.get_credentials(self._service)
        try:
            response = await self._send_authenticated_probe(url, credentials)
        finally:
            del credentials  # Explicitly delete reference
        return self._build_result(response)   # result contains no credentials
```

---

## 5. Control Plane API Security

### 5.1 Endpoint Protection

| Endpoint | Auth required | Permission |
|---|---|---|
| `GET /api/v2/health` | JWT | Any authenticated user |
| `POST /api/v2/health/check` | JWT | `admin:diagnostics` |
| `GET /api/v2/control-plane/status` | JWT | Any authenticated user |
| `GET /api/v2/config/` | JWT | `admin:config` |
| `PUT /api/v2/config/{key}` | JWT | `admin:config` |
| `POST /api/v2/config/validate` | JWT | `admin:config` |
| `POST /api/v2/diagnostics/run` | JWT | `admin:diagnostics` |
| `GET /api/v2/diagnostics/{run_id}` | JWT | `admin:diagnostics` |
| `GET /api/v2/diagnostics/history` | JWT | `admin:diagnostics` |

These permissions are proposed for B7. CP1 defines the intent; B7 implements
the permission model.

### 5.2 Rate Limiting

The login endpoint (`POST /api/auth/login`) must have rate limiting. This is a B7
concern, but CP1 establishes the requirement:

- Per-IP: 10 attempts per minute
- Per-identifier (email): 5 attempts per minute
- Lockout: 15 minutes after 10 failed attempts per identifier

Rate limiting state must be stored in Redis (from B6) or in-memory (CP1/CLI, where
rate limiting is not applicable).

### 5.3 No Unauthenticated Config Access

`GET /api/v2/config/` is never public. Even if the UI is in "degraded mode", an
unauthenticated user cannot read or modify configuration. The administrator must
log in first (which always works via local auth), and then can edit configuration.

---

## 6. Audit Requirements

### 6.1 Events Produced by CP1

| Event | Logged fields |
|---|---|
| Config value read via API | `user_id`, `key`, `timestamp` |
| Config value changed via API | `user_id`, `key`, `previous_value`, `new_value`, `timestamp` (secrets: REDACTED) |
| Config value changed via CLI | `"cli"`, `key`, `previous_value`, `new_value`, `timestamp` |
| Config value change attempted (protected key) | `changed_by`, `key`, `timestamp`, `reason: "protected_key"` |
| Diagnostics run triggered | `triggered_by`, `run_id`, `target`, `timestamp` |
| Diagnostics run completed | `run_id`, `overall_status`, `failure_classes`, `timestamp` |
| Health check triggered on-demand | `triggered_by`, `target`, `timestamp` |
| Integration test run | `triggered_by`, `service`, `result`, `failure_class`, `timestamp` |

### 6.2 Audit Log Format

Consistent with the B3 audit log design — structured JSON, one event per line,
appended to `$BETA_STORAGE_PATH/logs/audit.log`.

```json
{
  "event": "config_change",
  "timestamp": "2026-06-28T10:35:00Z",
  "key": "nextcloud.url",
  "previous_value": "https://nextcloud.example.com",
  "new_value": "https://new-nextcloud.example.com",
  "changed_by": "api:admin@example.com",
  "validated": true,
  "applied": true
}
```

### 6.3 Audit Log Integrity

The audit log file is append-only. The application never deletes or modifies existing
entries. Rotation (if needed) must preserve all entries — only a copy is rotated,
never the active log.

---

## 7. Threat Model Additions (CP1-Specific)

### T1 — Configuration Endpoint Abuse

**Threat:** Authenticated admin misuses `PUT /api/v2/config/nextcloud.url` to redirect
Nextcloud traffic to a malicious server to capture credentials.

**Mitigation:**
- The `AuthCheck` sends credentials to the configured URL. A malicious redirect
  would receive those credentials.
- Mitigation: Runtime Config only updates the URL. Credentials are not transmitted
  when the URL is changed — the `AuthCheck` only runs when explicitly triggered by
  the operator (on-demand health check) or by the background poller.
- TLS validation is always enforced. Redirecting to a malicious server without a valid
  certificate causes `tls_failure` before credentials are sent.
- Audit log: all URL changes are logged with the new value visible.
- Acceptance: This attack requires an authenticated admin with `admin:config` permission.
  The threat model treats authenticated admins as trusted.

### T2 — Diagnostic Output Information Disclosure

**Threat:** `DiagnosticReport` JSON is returned to the API caller and might include
sensitive information about internal network layout.

**Mitigation:**
- `detail` fields are scrubbed before serialization.
- IP addresses in DNS resolution results are included (they are not secret in this
  context — administrators need them to diagnose routing issues).
- Hostnames are included (they come from the configured URLs, which the admin controls).
- No secrets, passwords, or keys appear in any `DiagnosticReport` field.
- Endpoint requires admin permission — not accessible to regular users.

### T3 — Health Check DoS

**Threat:** Repeated calls to `POST /api/v2/health/check` trigger expensive network
checks that consume resources or spam external services.

**Mitigation:**
- On-demand health checks are rate-limited: maximum 1 per service per 10 seconds
  per authenticated user.
- The circuit breaker prevents hammering a failed service.
- Background polling already runs checks; repeated on-demand triggers are de-duplicated
  (return cached result if last check was < 5 seconds ago).

---

## 8. Boundary With B7 Authentication

CP1 defines the invariants. B7 implements them. The handoff contract:

| CP1 defines | B7 implements |
|---|---|
| Local auth is always available | `BetaUser` table + `UserRepository.authenticate()` |
| External auth failure never collapses | `FailureClass` taxonomy in auth flow |
| Login never contacts Nextcloud | `UserService.authenticate()` — local bcrypt only |
| JWT validated locally | `jwt.decode()` against `BETA_JWT_SECRET` only |
| Rate limiting on login | Redis-backed sliding window counter |
| Sessions are not affected by integration outage | JWT lifecycle — no external dependency |

B7 must not introduce any auth flow that contacts an external service during the
primary login path without Owner approval.
