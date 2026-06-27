# WooPrice Beta — UI Architecture

**Document:** UI_ARCHITECTURE.md
**Series:** B1 Architecture Blueprint

---

## Overview

The WooPrice Beta frontend is a React 18 SPA built with TypeScript, Tailwind CSS,
and Vite. It communicates exclusively with the versioned REST API — never directly
to the database or filesystem.

**Key constraint:** The `[BETA]` environment label is always visible and
cannot be suppressed by any user action, feature flag, or configuration value.

---

## Technology Stack

| Layer | Technology |
|---|---|
| Framework | React 18 |
| Language | TypeScript |
| Styling | Tailwind CSS |
| Build tool | Vite |
| HTTP client | Axios (typed API client, auto-generated from OpenAPI) |
| State | React Context + hooks (no global store until B10+) |
| Auth | JWT (access + refresh token; stored in memory + httpOnly cookie) |
| Forms | React Hook Form |
| Tables | TanStack Table |
| Charts | Recharts (B9+ for AI viewer) |

---

## Shell Layout

```
┌────────────────────────────────────────────────────────────┐
│  TopBar — [BETA ENVIRONMENT]  WooPrice Beta  v1.0.0        │
│           User: <email>   [Logout]                         │
├───────────────┬────────────────────────────────────────────┤
│  Sidebar      │  Main content area                         │
│  (permission- │                                            │
│   aware       │  ┌─────────────────────────────────────┐   │
│   navigation) │  │  Page component (route-matched)     │   │
│               │  │                                     │   │
│  Dashboard    │  │  <FeatureGate flag="FEATURE_*">     │   │
│  Products     │  │      <PageContent />                │   │
│  Sources      │  │  </FeatureGate>                     │   │
│  Rules        │  │                                     │   │
│  Safety       │  └─────────────────────────────────────┘   │
│  Change Sets  │                                            │
│  Dry Run      │                                            │
│  Execution    │                                            │
│  Scheduler    │                                            │
│  AI           │                                            │
│  Plugins      │                                            │
│  Admin        │                                            │
└───────────────┴────────────────────────────────────────────┘
```

### TopBar (`components/Layout/TopBar.tsx`)

- Persistent `[BETA ENVIRONMENT]` label (driven by API response, not URL/hostname)
- Application name, current version
- Current user email
- Logout button
- The label cannot be hidden or styled away — it is part of the component's required
  rendering and not wrapped in a flag gate

### Sidebar (`components/Layout/Sidebar.tsx`)

- Permission-aware: navigation items are shown only if the user has the required permission
- Feature-flag-aware: nav items for disabled features are hidden entirely
- Collapses on mobile viewport
- Active route is highlighted
- Plugin UI modules appear in the sidebar under "Extensions" when installed and enabled

---

## Routing

Routes are defined in `App.tsx` using React Router. Every route is wrapped in:
1. `AuthGuard` (redirect to login if not authenticated)
2. `FeatureGate` (renders 404 if feature flag is off)
3. `RequirePermission` (renders 403 if user lacks permission)

```tsx
const routes = [
    { path: "/dashboard", element: <Dashboard />, permission: null, flag: null },
    { path: "/products", element: <ProductList />, permission: "read:products", flag: null },
    { path: "/sources", element: <SourceList />, permission: "read:sources", flag: null },
    { path: "/rules", element: <RuleList />, permission: "read:rules", flag: "FEATURE_RULE_ENGINE" },
    { path: "/safety", element: <SafetyPolicyList />, permission: "read:safety", flag: "FEATURE_SAFETY_ENGINE" },
    { path: "/changesets", element: <ChangeSetList />, permission: "read:change_sets", flag: "FEATURE_CHANGE_SETS" },
    { path: "/dryrun", element: <DryRunViewer />, permission: "read:dry_run", flag: "FEATURE_DRY_RUN" },
    { path: "/execution", element: <ExecutionViewer />, permission: "read:execution", flag: "FEATURE_EXECUTION" },
    { path: "/scheduler", element: <SchedulerViewer />, permission: "read:schedules", flag: "FEATURE_SCHEDULER" },
    { path: "/ai", element: <AIInsightsViewer />, permission: "read:ai_insights", flag: "FEATURE_AI" },
    { path: "/plugins", element: <PluginManager />, permission: "admin:plugins", flag: "FEATURE_PLUGIN_SYSTEM" },
    { path: "/admin", element: <AdminPanel />, permission: "admin:all", flag: null },
];
```

---

## Feature Pages

### Dashboard (`features/dashboard/`)

- Summary cards: active sources, pending change sets, last execution timestamp,
  active schedules, AI insights (if `FEATURE_AI` enabled)
- Recent activity feed (last 10 events across all domains)
- System health badges (from `/api/health`)
- Environment label and version

### Products (`features/products/`)

- Paginated product table with search and filter
- Product detail view: source record, current price, last rule result, open change sets
- AI insight panel (feature-gated) — shows advisory insights for the selected product

### Sources (`features/sources/`)

- Source adapter list (name, type, status, last fetch timestamp)
- Source add wizard (multi-step form; gated by `FEATURE_PLUGIN_SYSTEM` for custom adapters)
- Source detail: fetch history, error log, test connection button

### Rules (`features/rules/`)

- Rule list with priority order (drag-and-drop reorder — B7)
- Rule detail: conditions, transformations, last evaluation result
- Rule test form: run a single rule against a sample product

### Safety (`features/safety/`)

- Policy list with status (active/inactive)
- Policy detail: constraint definition, last check results
- Safety override form (requires explicit admin confirmation with reason field)

### Change Sets (`features/changesets/`)

- Change Set list: status (PENDING, APPROVED, APPLIED, REJECTED), product count, created at
- Change Set detail: full diff view (before/after prices), rule trace, safety check results
- Approve/Reject actions (require permission; show confirmation dialog)

### Dry Run (`features/dryrun/`)

- Dry Run list: date, product count, outcome summary
- Dry Run detail: per-product result (would apply / would block / would skip)
- Start Dry Run button (triggers a TEP dry run pass for current change set)

### Execution (`features/execution/`)

- Execution history list: date, products updated, errors
- Execution detail: per-product outcome, error details
- No "Execute Now" button in B5 — read-only viewer only (execution initiated via Scheduler)

### Scheduler (`features/scheduler/`)

- Schedule list: name, cron expression, next run, status (ACTIVE / PAUSED / CANCELLED)
- Schedule detail: run history, last outcome
- Pause/Resume/Cancel actions
- B11: Add schedule form

### AI Insights (`features/ai/`)

- Advisory insight list: severity badge, category, summary, generated at
- Insight detail: full explanation, evidence, recommendation trace
- Filter by severity and category
- Insight archive action (moves to archived state)

### Plugins (`features/plugins/`)

- Installed plugin list: name, version, category, status (ACTIVE / INACTIVE / QUARANTINED)
- Plugin install wizard: upload or path; manifest preview; permission review; confirm
- Plugin detail: config form (based on plugin config_schema), enable/disable buttons
- Plugin update checker

### Admin (`features/admin/`)

- User management: list, create, edit role, deactivate, reset password
- Feature flag manager: table of all flags with toggle buttons
- Configuration viewer (read-only; no secrets shown)
- Audit log viewer: filterable event stream
- Backup management: create, list, restore
- Diagnostic report: run and view

---

## Authentication Flow

```
User visits protected route
  ↓
AuthGuard checks in-memory access token
  ├── Token valid → proceed
  └── Token expired or missing
        ↓
      Attempt silent refresh (POST /api/auth/refresh with httpOnly cookie)
        ├── Refresh success → new access token in memory → proceed
        └── Refresh failed → redirect to /login

Login form
  ↓
POST /api/auth/login (email + password)
  ↓
API returns { access_token, refresh_token }
  ├── access_token → stored in memory (React state; never localStorage)
  └── refresh_token → set as httpOnly, Secure, SameSite=Strict cookie by API

Logout
  ↓
DELETE /api/auth/session (invalidates refresh token server-side)
  ↓
Clear in-memory access token
  ↓
Redirect to /login
```

---

## API Client (`api/client.ts`)

The API client is a typed Axios instance:

```typescript
const apiClient = axios.create({
    baseURL: runtimeConfig.apiBaseUrl,  // from /api/health response at app load
    withCredentials: true,              // needed for httpOnly cookie
    headers: { "Content-Type": "application/json" },
});

// Request interceptor: inject access token
apiClient.interceptors.request.use((config) => {
    const token = tokenManager.getAccessToken();
    if (token) {
        config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
});

// Response interceptor: handle 401, retry with refresh
apiClient.interceptors.response.use(
    (response) => response,
    async (error) => {
        if (error.response?.status === 401 && !error.config._retry) {
            error.config._retry = true;
            await tokenManager.refresh();
            return apiClient(error.config);
        }
        return Promise.reject(error);
    }
);
```

---

## State Management

In B2–B5, state is managed using React Context and local component state. No global
store (Redux, Zustand) is added until complexity requires it (B10+ evaluation).

| Context | Provides |
|---|---|
| `AuthContext` | Current user, token management, login/logout |
| `FeatureFlagContext` | Flag snapshot, `useFeatureFlag(flag)` hook |
| `ConfigContext` | App config (version, env label, base URL) |

---

## Environment Label Rendering

The environment label is rendered by `TopBar.tsx`. Its value comes from the `env_label`
field returned by `GET /api/health`:

```typescript
const envLabelColors = {
    beta: "bg-orange-100 text-orange-800 border border-orange-300",
    dev: "bg-blue-100 text-blue-800 border border-blue-300",
    production: "bg-red-100 text-red-800 border border-red-300",
};

// TopBar always renders the label — never conditionally hidden
<span className={`px-2 py-0.5 rounded text-xs font-mono font-bold ${envLabelColors[config.env]}`}>
    {config.env_label}
</span>
```

---

## Responsive Layout

The sidebar collapses to a hamburger-triggered drawer on viewports below 768px. The
main content area uses a fluid grid. Tables become horizontally scrollable on small
screens. No mobile-specific features are planned for B5 — this is desktop-first.

---

## Error Handling

| Error type | UI behavior |
|---|---|
| API 401 Unauthorized | Silent refresh attempt → redirect to login if refresh fails |
| API 403 Forbidden | Show permission error page (not a redirect) |
| API 404 Not Found | Show "not found" inline message |
| API 503 Service Unavailable | Show "service unavailable" banner; retry button |
| Network error | Show "connection error" banner; retry button |
| Unexpected API error | Show generic error message; log to console |
| Integration plane failure | Show exact failure class (see Control Plane Resilience); Settings / Diagnostics remain accessible |

All error states show what happened and what the user can do next. Raw API error
messages are never shown directly — they are mapped to user-facing messages.

Integration failures must show the specific failure class (dns_failure, tls_failure,
timeout, unauthorized, forbidden, unreachable, invalid_response), never a collapsed
generic message.

---

## Control Plane Resilience

**Owner decision — 2026-06-27**

The UI must maintain access to the Control Plane even when Integration Plane services
are down.

**Control Plane UI surfaces (always accessible):**
- Login page
- Settings / Admin panel
- Integration credentials configuration (so the operator can fix credentials)
- Diagnostics view
- Feature flags manager
- Plugin manager
- Logs viewer
- Backup / update controls

**Integration Plane UI surfaces (may be disabled during outage):**
- Product Explorer, Source Explorer, Change Set Viewer, Dry Run Viewer,
  Execution Viewer, Scheduler Viewer, AI Insights Viewer

**Required UI behavior during integration outage:**

1. Show Settings / Integrations / Diagnostics — always.
2. Hide or disable dependent operational feature menus (those that require live
   integration data to be meaningful).
3. Show a clear repair path: which integration is failing, exact failure class,
   how to fix it (e.g., edit credentials, check network, review certificate).

**Failure class display rule:** Diagnostics and integration health checks must
display the exact failure class (dns_failure, tls_failure, timeout, unauthorized,
forbidden, unreachable, invalid_response). A generic "could not connect" or
"invalid credentials" message is not acceptable when the root cause is a DNS or
TLS failure.

**B8 requirement:** Settings and Diagnostics pages remain available during
integration outage. Dependent feature menu items are disabled (not hidden) when
integration health is failing, with a tooltip or banner explaining the outage.

**B13 requirement:** Admin panel (feature flags, plugin manager, audit log,
user management) must be accessible independent of Integration Plane status.
These are Control Plane surfaces and must never be gated behind integration
health.
