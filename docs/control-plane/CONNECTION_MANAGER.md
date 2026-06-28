# WooPrice Beta — Connection Manager

**Document:** CONNECTION_MANAGER.md
**Series:** CP1 Architecture Specification
**Status:** SPECIFICATION — awaiting CHAT2 review. No implementation has begun.

---

## 1. Overview

The Connection Manager is a singleton service within `app/beta/connections/` that
manages all outbound network connections from the WooPrice Beta application to
external integration services. It sits between the Health Engine, Diagnostic Runner,
and any application code that contacts an external service.

**Responsibilities:**
- Enforce retry policy and exponential backoff per service
- Maintain circuit breakers to avoid hammering unreachable services
- Classify connection failures into typed `FailureClass` values
- Cache successful connection probes to reduce unnecessary network traffic
- Apply configurable timeout policies per service
- Track recovery detection (when a previously-failed service becomes reachable again)

The Connection Manager **does not own credentials**. Credentials are loaded by
the `AuthCheck` from `SecretManager`. The Connection Manager handles transport
only: TCP, TLS, HTTP connections and their failure classification.

---

## 2. Service Registry

The Connection Manager maintains a registry of known services. Each service entry
defines its connection parameters.

```python
class ServiceName(str, Enum):
    NEXTCLOUD    = "nextcloud"
    WOOCOMMERCE  = "woocommerce"
    CURRENCY_API = "currency_api"
    SMTP         = "smtp"          # future — B15 notification system
    GENERIC_HTTP = "generic_http"  # plugin-defined adapters


@dataclass
class ServiceDefinition:
    name: ServiceName
    base_url: str              # from RuntimeConfigService
    health_probe_path: str     # path for unauthenticated HTTPCheck
    expected_status_code: int  # expected HTTP status from health probe
    timeout_policy: TimeoutPolicy
    retry_policy: RetryPolicy
    circuit_breaker: CircuitBreaker
```

Service definitions are loaded from `RuntimeConfigService` on startup. When an
administrator updates a service URL through Runtime Configuration, the Connection
Manager reloads the service definition without restart.

---

## 3. ConnectionResult

```python
@dataclass
class ConnectionResult:
    service: ServiceName
    success: bool
    failure_class: FailureClass     # always set; "ok" on success
    failure_message: str            # human-readable; never contains secrets
    latency_ms: Optional[float]     # None if connection failed before response
    status_code: Optional[int]      # HTTP status code, if applicable
    timestamp: datetime
    attempt_number: int             # 1-based; which retry this result came from
    from_cache: bool                # True if result was served from connection cache
```

---

## 4. Timeout Policy

Timeouts are configurable per service. Defaults are conservative to prevent UI hangs.

```python
@dataclass
class TimeoutPolicy:
    connect_timeout_s: float = 5.0    # TCP connect timeout
    read_timeout_s: float = 10.0      # HTTP read timeout (time to first byte)
    total_timeout_s: float = 15.0     # Total request timeout (connect + read)
    # total_timeout_s overrides the sum if exceeded first

    # TLS-specific
    tls_handshake_timeout_s: float = 5.0

    # DNS-specific
    dns_timeout_s: float = 5.0
```

**Configurable at runtime** via `wooprice configure set nextcloud.timeout_s 10`.
The `RuntimeConfigService` updates the service definition in the Connection Manager
registry without restart.

**Hard limits:** No timeout value may exceed 60 seconds. The Connection Manager
rejects configuration values above this limit.

---

## 5. Retry Policy

```python
@dataclass
class RetryPolicy:
    max_attempts: int = 2           # total attempts (1 = no retry)
    retryable_failure_classes: frozenset = frozenset({
        FailureClass.TIMEOUT,
        FailureClass.UNREACHABLE,   # may be transient
    })
    # Note: dns_failure, tls_failure, unauthorized, forbidden,
    # invalid_response are NOT retried by default.
    # dns_failure and tls_failure are structural — retry is pointless.
    # unauthorized and forbidden indicate configuration errors — retry is wrong.
```

### 5.1 Retryable vs Non-Retryable Failures

| FailureClass | Retried by default | Reason |
|---|---|---|
| `dns_failure` | No | Structural; retry returns same result within TTL |
| `tls_failure` | No | Structural; certificate issues do not self-resolve |
| `timeout` | Yes | May be transient network congestion |
| `unauthorized` | No | Sending wrong credentials again is harmful |
| `forbidden` | No | Access control issue — retry does not help |
| `unreachable` | Yes (1 retry) | May be a transient connection blip |
| `invalid_response` | No | Server-side issue; retry unlikely to help |

### 5.2 Retry Scope

Retries apply to **network-level** operations only. Application-level failures
(HTTP 401, 403, unexpected body) are not retried. The retry policy is applied
within the Connection Manager before returning a result to the caller.

---

## 6. Exponential Backoff

Backoff is applied between retry attempts.

```python
@dataclass
class ExponentialBackoff:
    base_delay_s: float = 0.5       # delay before first retry
    multiplier: float = 2.0         # delay × multiplier each attempt
    max_delay_s: float = 10.0       # cap on delay
    jitter: bool = True             # add random ±25% to delay (prevents thundering herd)
```

Backoff schedule for `max_attempts=3`, `base_delay_s=0.5`:

| Attempt | Delay before this attempt |
|---|---|
| 1 | 0 (immediate) |
| 2 | ~0.5s (±jitter) |
| 3 | ~1.0s (±jitter) |

Backoff delays are applied only within a single call to `ConnectionManager.test()`.
They are not persisted across independent calls.

---

## 7. Circuit Breaker

The circuit breaker prevents repeated network calls to a service that is clearly
unavailable, protecting both the application and the external service from
unnecessary traffic.

### 7.1 States

```
CLOSED ──(failure threshold exceeded)──▶ OPEN
  ▲                                         │
  │                              (recovery window elapsed)
  │                                         ▼
  └────────(probe succeeds)────── HALF-OPEN
```

```python
class BreakerState(str, Enum):
    CLOSED    = "closed"    # normal; all requests pass through
    OPEN      = "open"      # failing; all requests fail immediately (no network)
    HALF_OPEN = "half_open" # recovery probe: one request allowed through


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 3      # consecutive failures to open the circuit
    recovery_window_s: float = 30.0 # seconds in OPEN before moving to HALF_OPEN
    success_threshold: int = 1      # consecutive successes in HALF_OPEN to close
```

### 7.2 Behavior Per State

| State | Behavior |
|---|---|
| `CLOSED` | Request proceeds normally through retry + timeout policy |
| `OPEN` | Request fails immediately with `failure_class` from the last real failure. No network. |
| `HALF_OPEN` | One request is allowed through. If it succeeds → CLOSED. If it fails → OPEN. |

### 7.3 Circuit Breaker and Health Checks

Health checks from `DiagnosticRunner` and CLI **bypass the circuit breaker**. When
the administrator explicitly runs `wooprice integrations test nextcloud`, the circuit
breaker must not intercept it — the operator is explicitly asking for a live check.

Background polling and API-triggered health checks also bypass the circuit breaker
for the same reason.

Circuit breaker applies only to **application-level integration calls**
(e.g., A2 Source Adapter fetching from Nextcloud, WooCommerce write path).

---

## 8. Connection Cache

Successful connection probes are cached to reduce redundant network traffic.

```python
@dataclass
class CacheEntry:
    service: ServiceName
    result: ConnectionResult
    cached_at: datetime
    ttl_s: float                    # Time-to-live for this cache entry
```

### 8.1 Cache TTL

| Service | Default TTL | Rationale |
|---|---|---|
| Nextcloud | 60s | Balanced — quick recovery detection |
| WooCommerce | 60s | Balanced |
| Currency API | 300s | Low-change external service |
| Database | 30s | Critical; short TTL for fast failure detection |
| Storage | 30s | Critical; short TTL |

Cache TTL is configurable per service. A `ttl_s=0` disables caching (always live).

### 8.2 Cache Invalidation

The cache entry for a service is immediately invalidated when:
- An explicit on-demand health check is triggered for that service
- The service URL is updated via `RuntimeConfigService`
- The circuit breaker transitions from HALF_OPEN to CLOSED

### 8.3 Stale Cache Behavior

If a cache entry has expired and a new check has not yet completed:
- `ConnectionResult.from_cache = True`
- `ControlPlaneStatus` for that service returns `status = unknown`
- The frontend shows "Status unknown — last checked N minutes ago"
- A new check is triggered automatically to refresh the cache

---

## 9. Failure Classification Logic

The Connection Manager is responsible for mapping raw Python/httpx exceptions and
HTTP responses to `FailureClass` values.

```python
def classify_exception(exc: Exception, url: str) -> FailureClass:
    if isinstance(exc, socket.gaierror):
        return FailureClass.DNS_FAILURE
    if isinstance(exc, ssl.SSLError):
        return FailureClass.TLS_FAILURE
    if isinstance(exc, (httpx.ConnectTimeout, httpx.ReadTimeout, socket.timeout)):
        return FailureClass.TIMEOUT
    if isinstance(exc, (httpx.ConnectError, ConnectionRefusedError)):
        return FailureClass.UNREACHABLE
    return FailureClass.INVALID_RESPONSE


def classify_http_response(status_code: int) -> FailureClass:
    if status_code == 401:
        return FailureClass.UNAUTHORIZED
    if status_code == 403:
        return FailureClass.FORBIDDEN
    if 200 <= status_code < 300:
        return FailureClass.OK
    return FailureClass.INVALID_RESPONSE
```

**This is the canonical classification logic.** No other module may independently
classify network exceptions. All integration checks — in the Health Engine, Diagnostic
Runner, and A2 Source Adapter — must route exception classification through the
Connection Manager.

---

## 10. Recovery Detection

When a service transitions from `down` or `degraded` to `ok`, the Connection Manager:

1. Invalidates the circuit breaker (forces CLOSED state)
2. Invalidates the connection cache
3. Updates the `IntegrationState.last_ok_at` timestamp
4. Emits a recovery event to `ControlPlaneService`
5. `ControlPlaneService` recomputes `ControlPlaneStatus` and `FeatureAvailability`
6. (B6+) The updated status is pushed via SSE to connected UI clients

The UI removes the Offline Banner and re-enables previously-disabled sidebar items
upon receiving the updated `FeatureAvailability` from the API.

---

## 11. Integration with A2 Source Adapter

When the A2 Source Adapter (A2.2) needs to contact Nextcloud, it must route through
the Connection Manager rather than creating its own `httpx.AsyncClient` directly.
This ensures:
- Retry and backoff are applied consistently
- Circuit breaker is applied (to avoid hammering a failing Nextcloud)
- Failure classification is consistent with what the Health Engine reports

**A2 code is frozen.** The integration point will be an adapter shim in `app/beta/`
that wraps A2.2's connection calls with the Connection Manager. A2 source files are
never modified.

The shim architecture:
```
A2 Source Adapter
  └── calls app/beta/connections/adapter_shim.py
        └── ConnectionManager.get_http_client(ServiceName.NEXTCLOUD)
              → returns a configured httpx.AsyncClient with
                timeout policy + circuit breaker state applied
```

---

## 12. Thread Safety and Async

The Connection Manager is designed for async usage (FastAPI + asyncio). All public
methods are coroutines (`async def`). The circuit breaker and cache use asyncio locks
to prevent race conditions.

The CLI uses the Connection Manager through a synchronous wrapper
(`asyncio.run(manager.test_connection(service))`).
