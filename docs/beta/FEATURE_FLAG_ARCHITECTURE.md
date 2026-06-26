# WooPrice Beta — Feature Flag Architecture

**Document:** FEATURE_FLAG_ARCHITECTURE.md
**Series:** B1 Architecture Blueprint

---

## Overview

Feature flags control which Beta capabilities are active at runtime. Flags are stored
in the Beta database and evaluated by the Feature Flag Evaluator on each request.
They can be toggled via the CLI (`wooprice ai toggle`) or the Admin UI without a
restart.

---

## Defined Flags

| Flag name | Default | Controls |
|---|---|---|
| `FEATURE_RULE_ENGINE` | `true` | Rule Engine phase of TEP |
| `FEATURE_SAFETY_ENGINE` | `true` | Safety Policy Engine phase of TEP |
| `FEATURE_CHANGE_SETS` | `true` | Change Set Engine phase of TEP |
| `FEATURE_DRY_RUN` | `true` | Dry Run Engine phase of TEP |
| `FEATURE_EXECUTION` | `true` | Execution Engine phase of TEP |
| `FEATURE_SCHEDULER` | `true` | Scheduling Engine (A2.8) |
| `FEATURE_AI` | `true` | AI Foundation advisory layer (A2.9) |
| `FEATURE_MULTI_CHANNEL` | `false` | Multiple simultaneous channel adapters |
| `FEATURE_COMPETITOR_FEATURES` | `false` | Competitor price monitoring features |
| `FEATURE_PLUGIN_SYSTEM` | `true` | Plugin Registry and Loader |

### TEP flag constraint

Flags for TEP components (`FEATURE_RULE_ENGINE` through `FEATURE_SCHEDULER`) follow
a dependency chain. Disabling an upstream stage automatically prevents downstream stages
from running. The evaluator enforces this:

```
FEATURE_RULE_ENGINE
  → required for FEATURE_SAFETY_ENGINE
      → required for FEATURE_CHANGE_SETS
          → required for FEATURE_DRY_RUN
              → required for FEATURE_EXECUTION
                  → required for FEATURE_SCHEDULER
```

Disabling `FEATURE_DRY_RUN` also disables `FEATURE_EXECUTION` and `FEATURE_SCHEDULER`.
The Admin UI shows these dependency relationships and warns before disabling an upstream flag.

---

## Database Schema

Flags are stored in the `beta_feature_flags` table:

```
beta_feature_flags
  id          TEXT PK   (flag name, e.g., "FEATURE_RULE_ENGINE")
  is_enabled  BOOLEAN   NOT NULL DEFAULT TRUE
  description TEXT
  admin_only  BOOLEAN   NOT NULL DEFAULT FALSE
  locked      BOOLEAN   NOT NULL DEFAULT FALSE
  updated_at  TIMESTAMP
  updated_by  TEXT nullable  (user id of last modifier)
```

The `locked` field marks flags that cannot be toggled at runtime (set only at
migration time or by a superadmin). TEP flags that form the core safety chain
should not normally be locked, but they may be locked by Owner decision for
compliance or audit reasons.

---

## Flag Evaluator (`app/beta/feature_flags/evaluator.py`)

```python
class FeatureFlagEvaluator:
    def is_enabled(self, flag: str) -> bool:
        """Return True if flag is enabled, accounting for dependency chain."""

    def require(self, flag: str) -> None:
        """Raise FeatureDisabledError if flag is not enabled."""

    def snapshot(self) -> dict[str, bool]:
        """Return current state of all flags as a dict."""

    def toggle(self, flag: str, *, enabled: bool, user_id: str) -> None:
        """Toggle a flag; validate dependency chain; write audit event."""
```

The evaluator caches flag values in memory and refreshes every 30 seconds. The cache
is also invalidated explicitly by the `toggle()` call.

### `FeatureDisabledError`

```python
class FeatureDisabledError(Exception):
    def __init__(self, flag: str):
        self.flag = flag
        super().__init__(f"Feature {flag!r} is not enabled in this environment")
```

---

## API Enforcement

Feature flags are enforced as FastAPI dependencies. Each router that requires a flag
declares it using the `require_feature` dependency factory:

```python
from app.beta.feature_flags.dependency import require_feature

router = APIRouter()

@router.get("/changesets")
async def list_change_sets(
    _: None = Depends(require_feature("FEATURE_CHANGE_SETS")),
    ...
):
    ...
```

When the flag is disabled:
- The endpoint returns `HTTP 404 Not Found` (the feature is treated as non-existent, not forbidden)
- The response body: `{"detail": "Feature not available in this environment"}`
- The `FEATURE_*` flag name is NOT exposed in the response (no information disclosure)

---

## Frontend Enforcement

The frontend receives the flag snapshot from `/api/v2/flags/snapshot` on app load.
Feature-gated UI sections are wrapped in `FeatureGate`:

```tsx
// components/FeatureGate.tsx
interface FeatureGateProps {
    flag: string;
    fallback?: React.ReactNode;
    children: React.ReactNode;
}

export const FeatureGate: React.FC<FeatureGateProps> = ({ flag, fallback, children }) => {
    const { flags } = useFeatureFlags();
    if (!flags[flag]) {
        return fallback ? <>{fallback}</> : null;
    }
    return <>{children}</>;
};
```

Usage:

```tsx
<FeatureGate flag="FEATURE_AI">
    <AIInsightsPanel />
</FeatureGate>
```

Navigation items for disabled features are hidden entirely (not greyed out) to avoid
confusion about what is available.

---

## CLI Enforcement

CLI commands that depend on features check the flag before calling the API:

```bash
wooprice ai insights
```

If `FEATURE_AI` is disabled:
```
[BETA ENVIRONMENT]
✗ The AI feature (FEATURE_AI) is not enabled in this environment.
  To enable it: wooprice ai toggle --enable
```

---

## Admin UI

The Admin UI (`/admin/flags`) shows all flags in a table with current status and
description. Toggle buttons are displayed for each flag. Locking a flag requires
superadmin permission.

### Toggle confirmation

When toggling a TEP flag that will affect downstream flags:

```
⚠  Warning: Disabling FEATURE_CHANGE_SETS will also disable:
   • FEATURE_DRY_RUN
   • FEATURE_EXECUTION
   • FEATURE_SCHEDULER

   This will stop all scheduled executions immediately.
   Type "disable" to confirm, or Cancel.
```

---

## Boot-time Defaults

If the Beta database is not yet initialized (first boot before migrations), the
Feature Flag Evaluator falls back to the boot-time defaults declared in the managed
config file (`[features]` section). This ensures the app starts correctly before the
first migration run.

```python
BOOT_DEFAULTS = {
    "FEATURE_RULE_ENGINE": True,
    "FEATURE_SAFETY_ENGINE": True,
    "FEATURE_CHANGE_SETS": True,
    "FEATURE_DRY_RUN": True,
    "FEATURE_EXECUTION": True,
    "FEATURE_SCHEDULER": True,
    "FEATURE_AI": True,
    "FEATURE_MULTI_CHANNEL": False,
    "FEATURE_COMPETITOR_FEATURES": False,
    "FEATURE_PLUGIN_SYSTEM": True,
}
```

After database initialization, the `beta_001` migration seeds all flags from
`BOOT_DEFAULTS`. Subsequent flag state changes are stored in the database only.

---

## Audit Logging

Every flag toggle is written to the audit log:

```json
{
    "event": "feature_flag_toggled",
    "flag": "FEATURE_AI",
    "previous_value": true,
    "new_value": false,
    "user_id": "<user-id-placeholder>",
    "user_email": "<user-email-placeholder>",
    "timestamp": "<iso-timestamp>",
    "env": "beta"
}
```

Flag toggle events are never purged from the audit log, even after the retention
window, because they are part of the system change record.

---

## Adding New Flags (Phase B3+)

When a new feature flag is needed:

1. Add the flag name to `BOOT_DEFAULTS` in `evaluator.py`
2. Add the flag to the `beta_feature_flags` table seeding in the relevant Beta migration
3. Add the flag to `FEATURE_FLAG_ARCHITECTURE.md` (this document)
4. Gate the API endpoints using `require_feature`
5. Gate the frontend using `FeatureGate`
6. Document the dependency relationships if the flag has TEP implications
