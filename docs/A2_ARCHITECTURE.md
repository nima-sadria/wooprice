# WooPrice A2 Architecture Design — Revision R1

**Status:** Design only — pending Codex re-audit.
**Supersedes:** A2 initial design (commit `150b120`, 2026-06-24).
**Incorporates:** Owner decisions R1 (2026-06-24).
**Not implemented.** No code changes. No DB migrations. No deployment.

---

## R1 Owner Decisions — Quick Reference

| # | Decision | Effect on A2 |
|---|---|---|
| 1 | Trusted Automation deferred | AI layer redesigned; seller confirmation always mandatory; no auto-schedule |
| 2 | Live freshness verification mandatory | Layer 6 blocks execution if channel unreachable |
| 3 | Scope = INTERSECTION semantics | Product must satisfy ALL assigned scope dimensions |
| 4 | Canonical Product Model | `products` + `channel_listings`; WC IDs demoted to channel-specific identifiers |
| 5 | PostgreSQL strategic target | Full schema with constraints, FKs, concurrency model; SQLite for dev only |
| 6 | Workspace compatibility | Parallel operation; no cutover without reconciliation + parity + owner approval |

---

## 1. System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          PRICE SOURCES                                       │
│  Nextcloud/OnlyOffice (WebDAV)  │  Excel Upload  │  Numbers                 │
│  MySQL  │  Custom DB  │  WooPrice Native Pricing Table                       │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                   │  Layer 1: Source Adapter
                                   ▼
                   ┌───────────────────────────────┐
                   │    Canonical Product Model     │
                   │  products (UUID + SKU)         │
                   │  channel_listings (per channel)│
                   └───────────────┬───────────────┘
                                   │
     ┌──────────────┬──────────────┴──────────────┬──────────────┐
     │              │                             │              │
     ▼              ▼                             ▼              ▼
Layer 2:      Layer 3:                     Layer 4:        Layer 7:
Rule Engine   Safety Policy Engine         Change Set      AI Layer
                                           Engine          (detect/recommend)
     │              │                             │
     └──────────────┴──────────────┬──────────────┘
                                   │
                      Layer 5: Scheduling Engine
                      (now / deferred / low-traffic window)
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│              Layer 6: Channel Adapter                                        │
│      Live freshness verification (mandatory before every execution)          │
│  WooCommerce  │  Digikala  │  SnapShop  │  Shopify  │  Magento  │  Custom   │
└─────────────────────────────────────────────────────────────────────────────┘

Database: PostgreSQL (production) │ SQLite (local dev / transition only)
```

---

## 2. Canonical Product Model

### Decision

WooPrice must not use WooCommerce IDs as the primary product identity. WooPrice owns
canonical product identity. WooCommerce is a channel.

### Core Entities

```
products                          ← WooPrice canonical product
  id: UUID  PRIMARY KEY
  sku: VARCHAR(255)  UNIQUE NOT NULL   ← stable, source-agnostic identifier
  name: VARCHAR(1000) NOT NULL
  created_at: TIMESTAMPTZ
  updated_at: TIMESTAMPTZ

channel_listings                  ← per-channel product representation
  id: UUID  PRIMARY KEY
  product_id: UUID  → products.id
  channel_id: VARCHAR(100)  → channel_adapters.channel_id
  channel_product_id: VARCHAR(255)     ← e.g., wc_id, digikala_id, shopify_gid
  price: NUMERIC(14,4)
  stock: INTEGER
  currency: VARCHAR(10)
  sync_status: VARCHAR(50)         ← 'unknown' | 'synced' | 'stale' | 'error'
  last_synced_at: TIMESTAMPTZ      ← when WooPrice last wrote to this channel
  last_verified_at: TIMESTAMPTZ   ← when live freshness was last confirmed
  audit_metadata: JSONB
  UNIQUE (channel_id, channel_product_id)
```

### Relationship Model

```
Product  1─────N  Channel Listing
              ├── WooCommerce Listing   { channel_product_id = wc_id }
              ├── Shopify Listing       { channel_product_id = shopify_gid }
              └── Digikala Listing      { channel_product_id = digikala_product_id }
```

Each channel listing maintains its own channel identifier, price state, stock state,
synchronization metadata, and audit metadata independently.

### Migration from products_cache

`products_cache` (keyed on `wc_id`) migrates to:
- `products`: one row per product; SKU or wc_id used to seed SKU during migration
- `channel_listings`: one row per product per channel (initially WooCommerce only)

`products_cache` remains operational in parallel until Phase 2 routes all WC reads/writes
through `channel_listings`. No existing table is dropped until cutover criteria are met.

---

## 3. Layer 1 — Source Adapter

### Purpose

Decouple WooPrice from any specific price source. Change Set engine, transformation
engine, and safety engine never call source-specific code directly.

### Capability Flags

```
SourceAdapterCapabilities
  supports_delta: bool           # can return only rows changed since last checkpoint
  supports_streaming: bool       # can page through large sources without loading all rows
  supports_writeback: bool       # Optional Writeback: can write results back to source
  supports_snapshots: bool       # can return a stable snapshot token for checkpointing
  supports_deletion: bool        # can report deleted rows explicitly
  requires_full_on_schema_change: bool  # full read required after any schema change
  max_page_size: int | null      # streaming page limit; null if not applicable
  stable_row_identity: str       # 'product_id' | 'sku' | 'row_number' | 'none'
```

Adapters with `stable_row_identity = 'none'` cannot produce delta reads. Full reads only.
This must be surfaced clearly in the source configuration UI.

### Interface

```
SourceAdapter
  connect(config: SourceConfig) → ConnectionResult
  test_connection() → HealthResult
  get_capabilities() → SourceAdapterCapabilities
  get_schema() → SourceSchema
  get_field_mapping() → FieldMapping | null

  read_snapshot(mapping: FieldMapping) → SourceSnapshot      # always available
  read_delta(mapping: FieldMapping, since: SourceCheckpoint) → DeltaSnapshot
      # requires supports_delta = true

  write_back(rows: List[WriteBackRow]) → WriteBackResult
      # requires supports_writeback = true
```

### SourceSnapshot

```
SourceSnapshot
  adapter_id: str
  snapshot_token: str | null          # opaque; null if not supported
  snapshot_at: TIMESTAMPTZ
  row_count: int
  schema_fingerprint: str             # SHA256 of schema structure
  rows: Iterator[SourceRow]           # lazy stream; not materialized in memory
```

### SourceRow (canonical)

```
SourceRow
  product_id: str          # stable after field mapping applied
  name: str | null
  price: Decimal | null
  cost: Decimal | null
  currency: str | null
  stock: int | null
  source_row_ref: str      # opaque: row number, DB primary key, cell address
  source_row_hash: str     # SHA256 of raw source row content
  raw_fields: dict         # all original source columns before mapping
```

### FieldMapping (versioned)

Old mapping versions are retained. Active version is `is_current = true`.

```
FieldMapping
  id: UUID
  source_adapter_id: UUID
  version_number: int
  schema_fingerprint: str           # must match source at read time
  product_id_field: SourceField     # REQUIRED
  price_field: SourceField          # REQUIRED
  cost_field: SourceField | null
  currency_field: SourceField | null
  stock_field: SourceField | null
  custom_fields: dict
  is_current: bool
  created_by: int
  created_at: TIMESTAMPTZ
```

If source schema fingerprint differs from mapping's fingerprint: block import; prompt re-mapping.

### Source Stability Validation

| Validation | Failure action |
|---|---|
| Schema fingerprint matches mapping | Block; prompt re-mapping |
| All rows have `product_id` populated | Block; surface row-level error list |
| No duplicate product IDs within snapshot | Block; surface conflict list |
| Price field numeric / parseable | Block affected rows |
| Currency field recognized | Warn |
| IRR unit sanity (price < 1,000 and IRR) | Warn |
| Row count plausibility vs last checkpoint | Warn if drop > 10% |

### Deletion Semantics

| Capability | Behavior |
|---|---|
| `supports_deletion = true` | Deleted rows returned with `action = 'delete'`; Change Set item type = 'delete' |
| `supports_deletion = false` | Missing rows on full read → warn only; no auto-delete proposal |

Deletion items always require explicit seller confirmation. Never auto-applied.

### Source Checkpoint

```
SourceCheckpoint
  id: UUID
  source_adapter_id: UUID
  snapshot_token: str | null
  snapshot_at: TIMESTAMPTZ
  schema_fingerprint: str
  row_count: int
  advanced_by: UUID | null           # changeset_id that advanced this checkpoint
  created_at: TIMESTAMPTZ
```

**Checkpoint advancement:** Only after a derived Change Set executes successfully
(`completed` or `partial` with no system errors). On failure: checkpoint does NOT advance.

**Duplicate-ID failure:** If snapshot contains duplicate product IDs, the entire import
is blocked with a report listing all duplicates. No partial import from a duplicate snapshot.

### Adapter Implementations

| Adapter | Source | Status |
|---|---|---|
| NextcloudAdapter | Nextcloud/OnlyOffice XLSX via WebDAV | Implemented — only current adapter |
| ExcelUploadAdapter | Direct .xlsx upload | Future |
| NumbersAdapter | .numbers via export conversion | Future |
| MySQLAdapter | Configurable SQL query | Future |
| CustomDBAdapter | Any DB via connection string | Future |
| NativePricingTableAdapter | WooPrice built-in pricing table | Future |

---

## 4. Layer 2 — Transformation Rule Engine

### Purpose

Convert source values into final channel prices using a configurable, auditable,
versioned rule system. All transformations are explicit and retained in the Change Set
item for full audit provenance.

### Rule Types

| Rule | Formula | Notes |
|---|---|---|
| `ManualPriceRule` | `final = source.price` | Direct passthrough |
| `CostPlusRule` | `final = source.cost + margin` | margin in source currency |
| `CostFXRule` | `final = source.cost × fx_rate + margin` | fx_rate from FX provider |
| `CostFXFeeRule` | `final = source.cost × fx_rate + margin + channel_fee` | fee from channel config |
| `FormulaRule` | `final = eval(expr, context)` | Admin-defined; vars: cost, fx_usd, fx_eur, channel_fee |

`CompetitorRule` is not in A2. Deferred with Trusted Automation (no external competitor
data source interface is defined yet).

### 6-Level Precedence (most specific wins)

```
1. Change Set item override  ← seller forces a value for one item
                               (permitted only if safety policy allows for this scope)
2. User / seller scope rule
3. Brand rule
4. Category rule
5. Channel / store rule
6. Global default rule       ← always present as fallback
```

A seller-level rule cannot produce a price change exceeding the category/brand rule bound.
This is enforced by the Safety Policy Engine after transformation.

### Rule Versioning

```
rules_version_hash = SHA256(
  sorted(serialized active transformation_rule rows
         within the Change Set's scope and channel_id)
)
```

Stored in `DryRunDigest`. Any rule change after dry run computation → digest invalid.

### PriceProposal (output)

```
PriceProposal
  product_id: str
  final_price: Decimal
  currency: str
  applied_rule_id: UUID
  rule_level: str               # which precedence level matched
  rule_chain: List[RuleApplication]   # full audit chain (every rule evaluated)
  fx_rate_used: Decimal | null
  fx_rate_age: timedelta | null
```

`rule_chain` is stored verbatim on `ChangeSetItem` for audit provenance.

### FX Rate Source

FX rates are never embedded in rules. Fetched from FX provider (current: alanchand.com),
cached per `StoreConfig.fx_max_age_minutes` (default: 60 min). Expired rate → block
execution until refreshed.

---

## 5. Layer 3 — Safety Policy Engine

### Purpose

Evaluate proposed prices against admin-configured rules. The Safety Policy Engine is
the sole owner of safety validation — deterministic, rule-based.

### AI Boundary

```
AI layer may:     detect anomalies, recommend, explain
Safety Engine:    pass, warn, block (authoritative)

AI layer may NOT:
  Override or bypass any safety policy rule
  Set dry_run_status to 'passed' when Policy Engine returned 'blocked'
  Suppress policy violations from the dry run report
  Modify policy thresholds
```

This boundary is architectural. AI receives SafetyEvaluation as read-only and may
add explanations, but the evaluation result itself is immutable.

### Rule Types (12)

| Rule | Trigger | Default action |
|---|---|---|
| `MaxChangePercentRule` | `|new - old| / old > threshold` | warn |
| `CategoryLimitRule` | per-category max change % | warn |
| `BrandLimitRule` | per-brand max change % | warn |
| `UserLimitRule` | per-user/seller max change % | warn |
| `ChannelLimitRule` | per-channel max change % | warn |
| `MinPriceBoundRule` | `new < floor` | warn |
| `MaxPriceBoundRule` | `new > ceiling` | warn |
| `ZeroMissingRule` | `new == 0 or new is null` | warn |
| `RialTomanRule` | price < 1,000 and currency = IRR | warn |
| `ExtraZeroRule` | price ≥ 10× historical max | warn |
| `MissingZeroRule` | price ≤ 0.1× historical min | warn |
| `BulkAnomalyRule` | > X% of batch items have large changes | warn |

**Default for all: warn. Block requires explicit admin opt-in.**
This default must never change without "Owner approval to change safety policy."

### Policy Versioning

```
policies_version_hash = SHA256(
  sorted(serialized active safety_policy rows
         within the Change Set's scope and channel_id)
)
```

Stored in `DryRunDigest`. Any policy change after dry run → digest invalid.

### PolicyEngine.evaluate()

```
PolicyEngine.evaluate(product_id, old_price, proposed_price, context) → PolicyResult

PolicyContext:
  user_id, channel_id, category_id, brand_id
  active_policies: List[PolicyRule]   # pre-loaded for the Change Set scope

PolicyResult:
  action: 'pass' | 'warn' | 'block'
  violations: List[PolicyViolation]
    └── { rule_id, rule_type, action, message, old_value, proposed_value, threshold }
  override_allowed: bool              # true only if actor is_admin
```

### Admin Override

Requires `is_admin = true`, explicit confirmation parameter in API call, and always
produces an `AuditEvent` with `override_reason`. Never silent.

---

## 6. Layer 4 — Change Set Engine

### 6.1 Immutable Dry Run Binding

Every dry run produces a `DryRunDigest` — a cryptographic commitment to the full state
at dry run time. Any input change invalidates the digest and blocks execution.

```
DryRunDigest
  id: UUID  PRIMARY KEY
  changeset_id: UUID  UNIQUE              # one digest per Change Set
  computed_at: TIMESTAMPTZ

  # Component hashes (each independently verifiable)
  source_snapshot_hash: VARCHAR(64)    # SHA256 of all source_row_hash values in snapshot
  mapping_version_id: UUID             # exact field_mapping version used
  rules_version_hash: VARCHAR(64)      # from Layer 2
  policies_version_hash: VARCHAR(64)   # from Layer 3
  scope_hash: VARCHAR(64)              # SHA256 of changeset.scope JSON (sorted keys)
  channel_id: VARCHAR(100)
  items_hash: VARCHAR(64)              # SHA256 of sorted (product_id, old_value, proposed_value)

  # Combined digest
  digest: VARCHAR(64)  NOT NULL        # SHA256 of all component hashes in defined order
```

**Inputs that invalidate the digest:**

| Input | Invalidation trigger |
|---|---|
| Source snapshot | Source file updated after dry run |
| Field mapping | Mapping re-versioned |
| Transformation rules | Any rule in scope added, edited, or disabled |
| Safety policies | Any policy in scope added, edited, or disabled |
| Item list / old values | Direct edit, rollback, or freshness change on a product in the Change Set |

**Invalidation consequence:** Change Set status reset to `validated`. Seller must
re-run dry run and re-confirm. Seller is notified.

### 6.2 State Machine

```
draft
  │ validation triggered
  ▼
validating ──► scope_violation ──► rejected
  │
  ▼
validated
  │ dry run triggered
  ▼
dry_run_pending
  │ SafetyEvaluation complete
  ▼
dry_run_done
  ├── dry_run_status = blocked ──► seller fixes → back to validated
  └── dry_run_status = passed | warnings
        │ seller reviews and confirms
        ▼
      confirmed
        │ seller selects schedule mode
        ▼
      scheduled
        │ SchedulerDaemon picks up (execute_after <= now())
        ▼
      queued
        │ QueueWorker claims; revalidation runs
        │
        ├── revalidation fails ──► back to validated (re-dry-run required)
        ▼
      executing
        │
        ├── all applied ──────────────────────────────────► completed
        ├── some applied, some skipped / failed ──────────► partial
        └── all failed ────────────────────────────────────► failed
                 │
                 │ admin action
                 ▼
             rolled_back

Additional:
  queued | scheduled | confirmed ──► cancellation_requested ──► cancelled
  executing ──► cancelling ──► cancelled  (completes current batch, then stops)
  failed ──► retry_pending ──► queued     (if retry_count < max_retries)
  failed ──► exhausted                    (if retry_count >= max_retries)
```

### 6.3 Core Entities

```
ChangeSet
  id: UUID  PK
  status: VARCHAR(50)
  source_adapter_id: UUID  → source_adapters.id
  field_mapping_id: UUID  → field_mappings.id      # exact version at creation time
  channel_id: VARCHAR(100)  → channel_adapters.channel_id
  created_by: INTEGER  → app_users.id
  scope: JSONB
  schedule_mode: VARCHAR(50)  IN ('now','deferred','low_traffic')
  scheduled_at: TIMESTAMPTZ
  dry_run_digest_id: UUID  → dry_run_digests.id
  dry_run_status: VARCHAR(50)  IN ('passed','warnings','blocked')
  confirmed_at: TIMESTAMPTZ
  confirmed_by: INTEGER  → app_users.id
  approval_step_id: UUID  → approval_steps.id
  item_count: INTEGER  CHECK (<= 1000)
  cancel_requested_at: TIMESTAMPTZ
  cancel_requested_by: INTEGER  → app_users.id
  created_at, updated_at: TIMESTAMPTZ

ChangeSetItem
  id: UUID  PK
  changeset_id: UUID  → change_sets.id

  # Canonical product identity
  product_id: UUID  → products.id
  channel_listing_id: UUID  → channel_listings.id

  # Source provenance (immutable after creation)
  source_adapter_id: UUID  → source_adapters.id
  source_row_ref: VARCHAR(500)   # opaque source row identifier
  source_row_hash: VARCHAR(64)   # SHA256 of raw source row at snapshot time
  source_snapshot_token: TEXT    # snapshot token from SourceSnapshot

  # Values
  old_value: NUMERIC(14,4)       # from channel_listings at draft time
  proposed_value: NUMERIC(14,4)  # after transformation
  final_value: NUMERIC(14,4)     # after admin adjustment (if any)
  applied_value: NUMERIC(14,4)   # confirmed by channel response

  # Audit chain
  rule_applied_id: UUID  → transformation_rules.id
  rule_chain: JSONB              # full PriceProposal.rule_chain
  fx_rate_snapshot: NUMERIC(14,6)
  policy_result: JSONB

  execution_status: VARCHAR(50)
  applied_at: TIMESTAMPTZ
  created_at: TIMESTAMPTZ
```

### 6.4 Scope Enforcement — Intersection Semantics

Product must satisfy ALL assigned scope dimensions simultaneously.

```
ScopeSpec (JSONB on ChangeSet)
  brands: List[str] | null        # null = no restriction on this dimension
  categories: List[int] | null
  channels: List[str] | null

INTERSECTION rule (non-admin users):
  brand_ok = scope.brands is null OR product.brand IN scope.brands
  cat_ok   = scope.categories is null OR product.category IN scope.categories
  ch_ok    = scope.channels is null OR product.channel IN scope.channels
  in_scope = brand_ok AND cat_ok AND ch_ok

scope = null on all dimensions → admin/super-admin only

Scope is checked at Change Set creation time. Out-of-scope items are returned
in the creation response — not after dry run. They do not enter the Change Set.
```

### 6.5 Execution-Time Revalidation

All checks run before QueueWorker begins executing. Any failure aborts execution.

```
Pre-execution checklist:

1. Dry Run Digest validity
   Recompute digest from current state
   Mismatch → reset status to 'validated'; require re-dry-run and re-confirmation

2. Permission check
   Load current permissions for changeset.created_by from DB
   Missing permissions → block; AuditEvent('execution_blocked_permissions')

3. Policy version check
   Recompute policies_version_hash
   Mismatch → reset to 'validated'; require re-dry-run

4. Mapping version check
   Verify field_mapping_id still matches DryRunDigest.mapping_version_id and is_current=true
   Mismatch → reset to 'validated'; require re-dry-run

5. Seller / user status check
   Verify changeset.created_by is still active (not deleted or deactivated)
   Inactive → block; AuditEvent; notify admin

6. Channel freshness verification  (see Section 8.2)
   Unverifiable → BLOCK execution; AuditEvent('execution_blocked_freshness_unverifiable')
   Stale items → reset to 'validated'; seller must re-confirm with updated old_values
```

---

## 7. Layer 5 — Scheduling Engine

### Schedule Modes

| Mode | Trigger | Use case |
|---|---|---|
| `now` | Immediately after confirmation | Urgent corrections |
| `deferred` | Explicit `scheduled_at` UTC time | Planned campaigns |
| `low_traffic` | Next occurrence of configured quiet window | Bulk updates |

### Low-Traffic Window — DST Handling

```
StoreScheduleConfig
  channel_id, quiet_start (TIME), quiet_end (TIME), timezone (IANA), max_concurrent_jobs

Computing execute_after:
  tz = pytz.timezone(config.timezone)
  today_local = datetime.now(tz).date()
  next_window = tz.localize(datetime.combine(today_local, config.quiet_start))
  if datetime.now(tz) >= next_window:
    next_window += timedelta(days=1)
  execute_after = next_window.astimezone(pytz.utc)   # store UTC in DB

Never compute execute_after by adding seconds to a local time string.
DST transitions are handled by computing in local timezone and converting to UTC.
```

### Scheduler Components

```
SchedulerDaemon  (every 60s)
  Move scheduled_changesets WHERE status='queued' AND execute_after <= now() → claiming

QueueWorker  (per channel; every 5s)
  SELECT changeset_id FROM scheduled_changesets
  WHERE status='queued' AND channel_id=$ch AND execute_after <= now()
  LIMIT 1
  FOR UPDATE SKIP LOCKED     ← PostgreSQL pattern; no worker contention

  rowcount = 0 → none available; sleep
  → Set status='executing', claim_lease_id=UUID()
  → Run ExecutionEngine

HeartbeatLoop  (during execution; every 10s)
  UPDATE scheduled_changesets SET heartbeat_at=now()
  WHERE changeset_id=$id AND claim_lease_id=$lease
  rowcount = 0 → lease lost; abort execution

AbandonmentDetector  (every 30s)
  Find execution_batches WHERE status='executing' AND heartbeat_at < now()-30s
  → Reset to 'pending'; increment retry_count
  Find scheduled_changesets WHERE status='executing' AND heartbeat_at < now()-30s
  → Reset to 'retry_pending'
```

### Per-Channel Concurrency Control

```
channel_execution_slots
  channel_id PK, max_concurrent (default 1), current_count (default 0)

Acquire before execution:
  UPDATE channel_execution_slots
  SET current_count = current_count + 1
  WHERE channel_id=$ch AND current_count < max_concurrent
  RETURNING *
  rowcount = 0 → at capacity; release; retry later

Release on completion or failure:
  UPDATE channel_execution_slots
  SET current_count = GREATEST(0, current_count - 1)
```

### Cancellation

| From state | Trigger | To state | Notes |
|---|---|---|---|
| `queued`, `retry_pending`, `confirmed` | Cancel requested | `cancelled` | Immediate |
| `executing` | Cancel requested | `cancelling` | Completes current batch, then stops |
| `cancelling` | Batch boundary reached | `cancelled` | Applied items are NOT reversed |

Applied items are never reversed on cancellation. Use Rollback for that.

### Retry / Backoff

```
Per adapter: max_retries (default 3), backoff_base_s (default 60),
             backoff_multiplier (default 2.0), max_backoff_s (default 3600)

wait = min(base × multiplier^retry_count, max_backoff_s)

On batch failure:
  retry_count++
  retry_count > max_retries → status = 'exhausted' (manual review required)
  else: status = 'retry_pending'; retry_after = now() + wait
```

### Execution Engine

```
ExecutionEngine.run(changeset_id, lease_id):

  1. Run pre-execution checklist (Section 6.5)
     → Any failure: abort; update status

  2. Acquire channel execution slot
     → At capacity: release lease; return to 'queued'

  3. Load pending ExecutionBatches (status='pending')
     Skip 'completed' batches — idempotent resume after crash

  4. For each batch:
     a. Claim: UPDATE execution_batches SET status='executing', claim_lease_id=UUID()
               WHERE id=$id AND status='pending'
        rowcount=0 → already claimed; skip

     b. Per-item freshness check:
        channel_listings.price == item.old_value
        Mismatch → execution_status='skipped_stale'; exclude from WriteItems

     c. ChannelAdapter.batch_write(write_items)
        For each success: record execution_attempt; update channel_listings;
                          insert ChangeHistory; update change_set_item status='applied'
        For each failure: record execution_attempt; mark item status='failed'

     d. Heartbeat every 5 items
        rowcount=0 → lease lost; abort

     e. Mark batch 'completed'

  5. Evaluate ChangeSet outcome
     All applied → 'completed'
     Some applied, some skipped/failed → 'partial'
     All failed → 'failed'

  6. Release channel execution slot
  7. Insert AuditEvent
```

---

## 8. Layer 6 — Channel Adapter

### 8.1 Interface

```
ChannelAdapter
  channel_id: str
  get_capabilities() → ChannelCapabilities
    └── batch_write_max: int, rate_limit_rps: float,
        supports_idempotency: bool, retry_config: RetryConfig

  fetch_products(filter: FetchFilter) → Iterator[ChannelProduct]
  fetch_product(channel_product_id: str) → ChannelProduct | null
  verify_freshness(channel_product_ids: List[str]) → FreshnessResult
  batch_write(items: List[WriteItem], batch_size: int) → BatchWriteResult
  get_fee_schedule() → Dict[str, Decimal]
```

### 8.2 Live Freshness Verification (Mandatory)

Contacts the live channel before execution. Non-negotiable.

```
FreshnessResult
  verifiable: bool
  checked_at: TIMESTAMPTZ
  items: List[FreshnessItem]
    └── { channel_product_id, channel_price, channel_updated_at,
          status: 'ok' | 'price_changed' | 'product_not_found' }
  summary: 'ok' | 'stale' | 'product_missing' | 'unverifiable'
```

| `summary` | Action |
|---|---|
| `ok` | Proceed with execution |
| `stale` | Reset Change Set to `validated`; seller re-confirms with updated old_values |
| `product_missing` | Block missing items; proceed with remaining (if any remain) |
| `unverifiable` | **BLOCK entire execution**; emit AuditEvent; do not proceed |

`unverifiable` = channel unreachable (network error, auth failure, timeout).
Never proceed under uncertainty.

After verification: update `channel_listings.last_verified_at` for all checked products.

### 8.3 Batch Write Model

All channel writes are batched. Per-item writes are not supported.

```
WriteItem
  channel_product_id: str
  channel_listing_id: UUID
  changeset_item_id: UUID
  attempt_number: int
  idempotency_key: str         # SHA256(changeset_item_id || attempt_number)
  field: 'price' | 'stock'
  old_value: Decimal
  new_value: Decimal
  currency: str

BatchWriteResult
  succeeded: List[ItemWriteSuccess]
    └── { channel_product_id, channel_listing_id, changeset_item_id,
          applied_value, channel_response: JSON }
  failed: List[ItemWriteFailure]
    └── { channel_product_id, changeset_item_id, error_code,
          error_message, retryable: bool, http_status: int | null }
  rate_limit_remaining: int | null
```

### 8.4 Partial Failure Handling

```
For each success:
  INSERT execution_attempts (status='confirmed', channel_response)
  UPDATE channel_listings SET price=applied_value, last_synced_at=now()
  INSERT change_history
  UPDATE change_set_items SET execution_status='applied', applied_value, applied_at

For each failure:
  INSERT execution_attempts (status='failed', error_code, error_message)
  UPDATE change_set_items SET execution_status='failed'
  If retryable AND retry_count < max_retries → schedule retry
```

### 8.5 Remote-Success / Local-Failure Recovery

```
On retry (write was submitted but local confirmation not received):

  1. attempt_number++; idempotency_key = SHA256(item_id || new_attempt_number)
  2. fetch_product(channel_product_id) → channel_price
  3. channel_price == proposed_value
     → Write was already applied; INSERT execution_attempt(status='confirmed',
       channel_response={recovered:true}); mark item 'applied'. Do NOT write again.
  4. channel_price == old_value
     → Write was not applied; proceed with retry batch_write
  5. channel_price is something else
     → Unknown state; mark item 'failed' with error='unexpected_channel_state';
       flag for admin review
```

### 8.6 Rate-Limit Handling

```
On HTTP 429 or rate_limit_remaining == 0:
  Complete items confirmed in partial response
  Mark remaining items in batch 'pending' (not failed)
  Mark batch 'retry_pending'; retry_after = now() + backoff
  Release channel execution slot
```

### 8.7 WooCommerce Adapter (current; to be refactored)

- Batch write: `POST /wp-json/wc/v3/products/batch` (max 100 items)
- Recommended: 50 items per batch, 100ms inter-batch delay
- Auth: WC consumer key + secret (not JWT)
- `supports_idempotency = false`
- Recovery: channel_price comparison (Case 3 above)
- Variations: `POST /wc/v3/products/{id}/variations/batch`
- HTTP 502 surfaces to caller; no indefinite retry

---

## 9. Layer 7 — AI Layer

### Decision: Trusted Automation Deferred

Trusted Automation is not in A2. Seller confirmation is mandatory for every execution
without exception. No system component may auto-schedule or auto-apply a Change Set.

```
WooPrice may:
  Recommend a schedule time
  Pre-populate a Change Set draft for seller review
  Explain safety violations in human-readable language

WooPrice may NOT (in A2 and any future phase without new owner decision):
  Auto-schedule a Change Set
  Auto-apply any price
  Execute any Change Set without explicit seller confirmation of the dry run result
```

### 9.1 Error Detector

Runs at Change Set draft time before scope validation.

```
Checks:
  price < 1,000 and currency = IRR → Toman vs Rial confusion
  price ≥ 100× channel_listings.price → likely extra zeros
  price ≤ 0.01× channel_listings.price → likely missing zeros
  price = 0 or null → missing price
  price = channel_listings.price → no change (informational)
  product_id not in products → unmapped product
```

Output: `ErrorWarning` list. Shown to seller before Change Set submission.
Warnings do not block creation. Seller may dismiss and proceed.

### 9.2 Market Freshness Monitor

```
FreshnessMonitor
  stale_threshold_days: int   # default 30; admin-configurable

  scan(channel_id) → List[StaleListing]
  suggest_review(stale_listings) → FreshnessDraftSuggestion
```

Stale listings surface in Dashboard and Product Browser.
`FreshnessDraftSuggestion` is a pre-populated Change Set draft — seller reviews,
modifies, and schedules explicitly.

### 9.3 Anomaly Explainer

After Safety Policy Engine produces violations, AI may add human-readable explanations.
These appear in the dry run report UI alongside the violation details.

```
AnomalyExplainer.explain(violation, context) → ExplanationText
  "This price would increase 340% (85,000 → 374,000 IRR).
   MaxChangePercentRule threshold for this category is 50%.
   Admin override required to proceed."
```

The explanation is informational only. It does not modify `PolicyResult.action`.
A `block` from the Safety Engine cannot be changed by the AI layer's explanation.

### 9.4 Competitor Awareness (Future)

Requires an external competitor data source interface not yet defined.
Deferred with Trusted Automation. Not in A2 scope.

---

## 10. Data Flow Diagrams

### 10.1 Standard Change Set Apply Path

```
Source (Nextcloud / MySQL / etc.)
  │
  │ SourceAdapter.read_snapshot()
  ▼
SourceSnapshot (lazy stream)
  │
  │ ErrorDetector.scan()  → pre-flight warnings to seller
  │ Source stability validation (schema, duplicates, missing IDs)
  ▼
Validated SourceRows
  │
  │ ScopeEnforcer.filter() — INTERSECTION semantics
  │ Rejected items returned immediately; do not proceed
  ▼
Scoped SourceRows
  │
  │ RuleEngine.evaluate() for each row → PriceProposals
  ▼
PriceProposals (with rule_chain, fx_rate_snapshot)
  │
  │ PolicyEngine.evaluate() for each item → PolicyResults
  ▼
PolicyResults (pass / warn / block per item)
  │
  │ ChangeSetEngine.create_draft() → compute DryRunDigest
  ▼
ChangeSet [dry_run_done] + DryRunDigest
  │
  │ Seller reviews dry run report
  │   blocked items: seller fixes and re-runs
  │   warnings: seller may proceed
  │
  │ Seller confirms (mandatory)
  ▼
ChangeSet [confirmed]
  │
  │ Seller chooses: now | deferred | low_traffic
  ▼
SchedulerDaemon → [queued]
  │
  │ QueueWorker claims (FOR UPDATE SKIP LOCKED)
  │ Pre-execution checklist: digest, permissions, policies, mapping, seller, freshness
  │   Unverifiable freshness → BLOCK
  │   Stale → reset to 'validated'
  ▼
ExecutionEngine
  │
  │ For each batch (50 items):
  │   Per-item freshness check → skip stale
  │   ChannelAdapter.batch_write()
  │   On success: channel_listings update + ChangeHistory + execution_attempt
  │   Heartbeat every 5 items
  ▼
ChangeSet [completed | partial | failed]
  AuditEvent written
  Source checkpoint advanced (only on success)
  Optional writeback to source (if adapter supports)
```

### 10.2 Exempt Write Paths

```
Direct Edit
  PUT /api/products/{id}/price
  → ChannelAdapter.batch_write([single item])
  → channel_listings update + ChangeHistory
  → DRY_RUN_INVALIDATE for all active ChangeSets containing this product

Emergency Apply
  Atomic claim → per-item: channel_listings.price == item.old_value check
  → ChannelAdapter.batch_write()
  → Checkpoints A/B/C (applying → wc_succeeded → applied)

Rollback / Undo
  Admin only → read ChangeHistory.old_value
  → ChannelAdapter.batch_write([single item])
  → new channel_listings entry + new ChangeHistory row
```

---

## 11. Permission Model Extension

### Scope Assignment

```
UserScopeAssignment  (JSONB on app_users or dedicated table)
  brands: List[str] | null
  categories: List[int] | null
  channels: List[str] | null

scope = null (all dimensions) → admin/super-admin only
scope with all empty lists → no access to any product
```

### effectiveHasScopedPerm

```
effectiveHasScopedPerm(user, permission, product) → bool

1. user null → false
2. is_admin or is_super_admin → true (no scope check)
3. !can_access_site → false
4. !permissions[permission] → false
5. user.scope == null → true (unrestricted)
6. INTERSECTION:
   brand_ok = scope.brands is null OR product.brand IN scope.brands
   cat_ok   = scope.categories is null OR product.category IN scope.categories
   ch_ok    = scope.channels is null OR product.channel IN scope.channels
   return brand_ok AND cat_ok AND ch_ok
```

Existing users without scope assignment get `scope = null` by default (no behavior change).

---

## 12. Audit Architecture

### AuditEvent (extended)

```
audit_events
  id: UUID PK
  event_type: VARCHAR(100) NOT NULL
  actor_user_id: INTEGER → app_users.id
  actor_ip: INET
  changeset_id: UUID → change_sets.id
  batch_id: UUID → execution_batches.id
  attempt_id: UUID → execution_attempts.id
  product_id: UUID → products.id
  channel_listing_id: UUID → channel_listings.id
  old_value: NUMERIC(14,4)
  new_value: NUMERIC(14,4)
  source_adapter_id: UUID → source_adapters.id
  rule_id: UUID → transformation_rules.id
  policy_violations: JSONB
  override_reason: TEXT            # admin safety bypasses only
  channel_id: VARCHAR(100)
  freshness_check_result: JSONB    # freshness-blocked events
  metadata: JSONB
  created_at: TIMESTAMPTZ NOT NULL
```

### Operation Provenance

| Operation | Required provenance |
|---|---|
| Change Set Apply | source_adapter_id, rule_id, rule_chain, actor, changeset_id, channel_id |
| Direct Edit | actor, product_id, channel_listing_id, old_value, new_value |
| Emergency Apply | actor, batch_id, product_id, old_value, new_value |
| Rollback / Undo | actor, product_id, restored_from reference |
| Safety override | actor, override_reason, violations bypassed |
| Freshness block | system actor, changeset_id, freshness_check_result |

---

## 13. Database Design

### 13.1 Strategic Direction

| Environment | Database |
|---|---|
| Production | PostgreSQL 15+ |
| Staging | PostgreSQL (must match production) |
| Local development | SQLite (acceptable) |
| Transition | SQLite acceptable until PostgreSQL migration verified |

### 13.2 Concurrency Model

```
Queue claim — FOR UPDATE SKIP LOCKED:
  SELECT changeset_id FROM scheduled_changesets
  WHERE status='queued' AND channel_id=$ch AND execute_after <= now()
  ORDER BY execute_after ASC
  LIMIT 1
  FOR UPDATE SKIP LOCKED

Multiple QueueWorkers (one per channel) run concurrently without blocking.
SKIP LOCKED means a row already claimed by another worker is silently skipped.

Status transitions — optimistic locking:
  UPDATE change_sets SET status=$new, updated_at=now()
  WHERE id=$id AND status=$expected
  RETURNING id
  rowcount=0 → concurrent update; caller retries
```

### 13.3 Locking Model

| Operation | Lock type |
|---|---|
| Queue claim | SELECT FOR UPDATE SKIP LOCKED |
| Batch claim | SELECT FOR UPDATE SKIP LOCKED |
| Channel slot acquisition | SELECT FOR UPDATE (single row, low contention) |
| ChangeSet status transition | Optimistic (WHERE status=$expected) |
| Admin override | SELECT FOR UPDATE advisory (prevent concurrent override) |

### 13.4 Full Schema (PostgreSQL)

```sql
-- Canonical product identity
CREATE TABLE products (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  sku         VARCHAR(255) UNIQUE NOT NULL,
  name        VARCHAR(1000) NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Per-channel product representation
CREATE TABLE channel_listings (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id           UUID NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
  channel_id           VARCHAR(100) NOT NULL,  -- FK added after channel_adapters
  channel_product_id   VARCHAR(255) NOT NULL,
  price                NUMERIC(14,4),
  stock                INTEGER,
  currency             VARCHAR(10),
  sync_status          VARCHAR(50) NOT NULL DEFAULT 'unknown',
  last_synced_at       TIMESTAMPTZ,
  last_verified_at     TIMESTAMPTZ,
  audit_metadata       JSONB,
  UNIQUE (channel_id, channel_product_id)
);
CREATE INDEX idx_channel_listings_product ON channel_listings(product_id);
CREATE INDEX idx_channel_listings_channel ON channel_listings(channel_id, sync_status);

-- Source adapter configurations
CREATE TABLE source_adapters (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  adapter_type      VARCHAR(100) NOT NULL,
  display_name      VARCHAR(255) NOT NULL,
  config_encrypted  BYTEA NOT NULL,         -- AES-256-GCM; key from APPLICATION_SECRET
  capabilities      JSONB NOT NULL,
  active            BOOLEAN NOT NULL DEFAULT TRUE,
  last_validated_at TIMESTAMPTZ,
  created_by        INTEGER NOT NULL REFERENCES app_users(id) ON DELETE RESTRICT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Field mappings (versioned)
CREATE TABLE field_mappings (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_adapter_id  UUID NOT NULL REFERENCES source_adapters(id) ON DELETE RESTRICT,
  version_number     INTEGER NOT NULL DEFAULT 1,
  schema_fingerprint VARCHAR(64) NOT NULL,
  mapping_definition JSONB NOT NULL,
  is_current         BOOLEAN NOT NULL DEFAULT TRUE,
  created_by         INTEGER NOT NULL REFERENCES app_users(id) ON DELETE RESTRICT,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (source_adapter_id, version_number)
);

-- Source checkpoints
CREATE TABLE source_checkpoints (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_adapter_id  UUID NOT NULL REFERENCES source_adapters(id) ON DELETE RESTRICT,
  snapshot_token     TEXT,
  snapshot_at        TIMESTAMPTZ NOT NULL,
  row_count          INTEGER,
  schema_fingerprint VARCHAR(64),
  advanced_by        UUID,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Channel adapter configurations
CREATE TABLE channel_adapters (
  channel_id        VARCHAR(100) PRIMARY KEY,
  adapter_type      VARCHAR(100) NOT NULL,
  display_name      VARCHAR(255) NOT NULL,
  config_encrypted  BYTEA NOT NULL,         -- AES-256-GCM
  rate_limit_config JSONB NOT NULL DEFAULT '{}',
  retry_config      JSONB NOT NULL DEFAULT '{}',
  active            BOOLEAN NOT NULL DEFAULT TRUE,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE channel_listings
  ADD CONSTRAINT fk_channel_listings_channel
  FOREIGN KEY (channel_id) REFERENCES channel_adapters(channel_id) ON DELETE RESTRICT;

-- Per-channel concurrency slots
CREATE TABLE channel_execution_slots (
  channel_id      VARCHAR(100) PRIMARY KEY REFERENCES channel_adapters(channel_id),
  max_concurrent  INTEGER NOT NULL DEFAULT 1 CHECK (max_concurrent >= 1),
  current_count   INTEGER NOT NULL DEFAULT 0 CHECK (current_count >= 0),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Schedule configuration per channel
CREATE TABLE store_schedule_config (
  channel_id          VARCHAR(100) PRIMARY KEY REFERENCES channel_adapters(channel_id),
  quiet_start         TIME NOT NULL,
  quiet_end           TIME NOT NULL,
  timezone            VARCHAR(100) NOT NULL DEFAULT 'UTC',
  max_concurrent_jobs INTEGER NOT NULL DEFAULT 1 CHECK (max_concurrent_jobs >= 1),
  updated_by          INTEGER NOT NULL REFERENCES app_users(id) ON DELETE RESTRICT,
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Transformation rules (hash-versioned at dry run time)
CREATE TABLE transformation_rules (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  scope_type  VARCHAR(50) NOT NULL
              CHECK (scope_type IN ('global','channel','category','brand','user')),
  scope_id    VARCHAR(255),
  rule_type   VARCHAR(100) NOT NULL,
  params      JSONB NOT NULL DEFAULT '{}',
  priority    INTEGER NOT NULL DEFAULT 0,
  active      BOOLEAN NOT NULL DEFAULT TRUE,
  created_by  INTEGER NOT NULL REFERENCES app_users(id) ON DELETE RESTRICT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_rules_scope ON transformation_rules(scope_type, scope_id) WHERE active = TRUE;

-- Safety policy rules (hash-versioned at dry run time)
CREATE TABLE safety_policies (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  scope_type  VARCHAR(50) NOT NULL
              CHECK (scope_type IN ('global','channel','category','brand','user')),
  scope_id    VARCHAR(255),
  rule_type   VARCHAR(100) NOT NULL,
  action      VARCHAR(10) NOT NULL DEFAULT 'warn' CHECK (action IN ('warn','block')),
  threshold   JSONB NOT NULL DEFAULT '{}',
  enabled     BOOLEAN NOT NULL DEFAULT TRUE,
  updated_by  INTEGER NOT NULL REFERENCES app_users(id) ON DELETE RESTRICT,
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_policies_scope ON safety_policies(scope_type, scope_id) WHERE enabled = TRUE;

-- Dry run digests (immutable; one per Change Set)
CREATE TABLE dry_run_digests (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  changeset_id          UUID NOT NULL,
  computed_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  source_snapshot_hash  VARCHAR(64) NOT NULL,
  mapping_version_id    UUID NOT NULL REFERENCES field_mappings(id) ON DELETE RESTRICT,
  rules_version_hash    VARCHAR(64) NOT NULL,
  policies_version_hash VARCHAR(64) NOT NULL,
  scope_hash            VARCHAR(64) NOT NULL,
  channel_id            VARCHAR(100) NOT NULL,
  items_hash            VARCHAR(64) NOT NULL,
  digest                VARCHAR(64) NOT NULL
);

-- Change Sets
CREATE TABLE change_sets (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  status            VARCHAR(50) NOT NULL DEFAULT 'draft',
  source_adapter_id UUID NOT NULL REFERENCES source_adapters(id) ON DELETE RESTRICT,
  field_mapping_id  UUID NOT NULL REFERENCES field_mappings(id) ON DELETE RESTRICT,
  channel_id        VARCHAR(100) NOT NULL REFERENCES channel_adapters(channel_id) ON DELETE RESTRICT,
  created_by        INTEGER NOT NULL REFERENCES app_users(id) ON DELETE RESTRICT,
  scope             JSONB NOT NULL DEFAULT '{}',
  schedule_mode     VARCHAR(50) CHECK (schedule_mode IN ('now','deferred','low_traffic')),
  scheduled_at      TIMESTAMPTZ,
  dry_run_digest_id UUID REFERENCES dry_run_digests(id) ON DELETE SET NULL,
  dry_run_status    VARCHAR(50) CHECK (dry_run_status IN ('passed','warnings','blocked')),
  confirmed_at      TIMESTAMPTZ,
  confirmed_by      INTEGER REFERENCES app_users(id) ON DELETE RESTRICT,
  approval_step_id  UUID,
  item_count        INTEGER NOT NULL DEFAULT 0 CHECK (item_count >= 0 AND item_count <= 1000),
  cancel_requested_at TIMESTAMPTZ,
  cancel_requested_by INTEGER REFERENCES app_users(id) ON DELETE RESTRICT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_changesets_status ON change_sets(status, updated_at);
CREATE INDEX idx_changesets_channel ON change_sets(channel_id, status);

-- Cross-FK from dry_run_digests to change_sets
ALTER TABLE dry_run_digests
  ADD CONSTRAINT fk_digest_changeset
  FOREIGN KEY (changeset_id) REFERENCES change_sets(id) ON DELETE CASCADE;
ALTER TABLE dry_run_digests
  ADD CONSTRAINT uq_digest_changeset UNIQUE (changeset_id);

-- Change Set Items
CREATE TABLE change_set_items (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  changeset_id         UUID NOT NULL REFERENCES change_sets(id) ON DELETE CASCADE,
  product_id           UUID NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
  channel_listing_id   UUID NOT NULL REFERENCES channel_listings(id) ON DELETE RESTRICT,
  source_adapter_id    UUID NOT NULL REFERENCES source_adapters(id) ON DELETE RESTRICT,
  source_row_ref       VARCHAR(500) NOT NULL,
  source_row_hash      VARCHAR(64) NOT NULL,
  source_snapshot_token TEXT,
  old_value            NUMERIC(14,4) NOT NULL,
  proposed_value       NUMERIC(14,4) NOT NULL,
  final_value          NUMERIC(14,4),
  applied_value        NUMERIC(14,4),
  rule_applied_id      UUID NOT NULL REFERENCES transformation_rules(id) ON DELETE RESTRICT,
  rule_chain           JSONB NOT NULL DEFAULT '[]',
  fx_rate_snapshot     NUMERIC(14,6),
  policy_result        JSONB NOT NULL DEFAULT '{}',
  execution_status     VARCHAR(50) NOT NULL DEFAULT 'pending'
                         CHECK (execution_status IN
                           ('pending','executing','applied','skipped_stale','failed','cancelled')),
  applied_at           TIMESTAMPTZ,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_items_changeset ON change_set_items(changeset_id, execution_status);
CREATE INDEX idx_items_product ON change_set_items(product_id);

-- Execution Batches
CREATE TABLE execution_batches (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  changeset_id    UUID NOT NULL REFERENCES change_sets(id) ON DELETE CASCADE,
  batch_index     INTEGER NOT NULL,
  status          VARCHAR(50) NOT NULL DEFAULT 'pending'
                    CHECK (status IN
                      ('pending','claiming','executing','completed','failed','cancelled')),
  claim_lease_id  UUID,
  claimed_by      VARCHAR(255),
  claimed_at      TIMESTAMPTZ,
  heartbeat_at    TIMESTAMPTZ,
  retry_count     INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
  retry_after     TIMESTAMPTZ,
  completed_at    TIMESTAMPTZ,
  UNIQUE (changeset_id, batch_index)
);
CREATE INDEX idx_batches_queue ON execution_batches(status, retry_after)
  WHERE status IN ('pending','retry_pending');

-- Per-item execution attempts (idempotent)
CREATE TABLE execution_attempts (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  batch_id            UUID NOT NULL REFERENCES execution_batches(id) ON DELETE CASCADE,
  changeset_item_id   UUID NOT NULL REFERENCES change_set_items(id) ON DELETE CASCADE,
  attempt_number      INTEGER NOT NULL DEFAULT 1 CHECK (attempt_number >= 1),
  idempotency_key     VARCHAR(64) NOT NULL,
  channel_request_id  VARCHAR(255),
  status              VARCHAR(50) NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending','submitted','confirmed','failed','skipped')),
  submitted_at        TIMESTAMPTZ,
  confirmed_at        TIMESTAMPTZ,
  error_code          VARCHAR(100),
  error_message       TEXT,
  channel_response    JSONB,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (changeset_item_id, attempt_number)
);
CREATE UNIQUE INDEX idx_attempts_idempotency ON execution_attempts(idempotency_key);

-- Scheduled Change Sets
CREATE TABLE scheduled_changesets (
  changeset_id        UUID PRIMARY KEY REFERENCES change_sets(id) ON DELETE CASCADE,
  mode                VARCHAR(50) NOT NULL CHECK (mode IN ('now','deferred','low_traffic')),
  execute_after       TIMESTAMPTZ NOT NULL,
  quiet_start         TIME,
  quiet_end           TIME,
  timezone            VARCHAR(100),
  status              VARCHAR(50) NOT NULL DEFAULT 'queued'
                        CHECK (status IN
                          ('queued','claiming','executing','cancelling','cancelled',
                           'completed','failed','retry_pending','exhausted')),
  claim_lease_id      UUID,
  claimed_by          VARCHAR(255),
  claimed_at          TIMESTAMPTZ,
  heartbeat_at        TIMESTAMPTZ,
  retry_count         INTEGER NOT NULL DEFAULT 0,
  retry_after         TIMESTAMPTZ,
  max_retries         INTEGER NOT NULL DEFAULT 3 CHECK (max_retries >= 0),
  cancel_requested_at TIMESTAMPTZ
);
CREATE INDEX idx_scheduled_queue ON scheduled_changesets(execute_after, status)
  WHERE status IN ('queued','retry_pending');

-- Optional second-party approval (disabled by default)
CREATE TABLE approval_steps (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  changeset_id   UUID NOT NULL REFERENCES change_sets(id) ON DELETE CASCADE,
  required_role  VARCHAR(255),
  status         VARCHAR(50) NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending','approved','rejected')),
  decided_by     INTEGER REFERENCES app_users(id) ON DELETE RESTRICT,
  decided_at     TIMESTAMPTZ,
  notes          TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Note: decided_by != changeset.created_by is enforced in service layer (not DB)

ALTER TABLE change_sets
  ADD CONSTRAINT fk_changeset_approval
  FOREIGN KEY (approval_step_id) REFERENCES approval_steps(id) ON DELETE SET NULL;

-- Extended audit events
CREATE TABLE audit_events (
  id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_type             VARCHAR(100) NOT NULL,
  actor_user_id          INTEGER REFERENCES app_users(id) ON DELETE SET NULL,
  actor_ip               INET,
  changeset_id           UUID REFERENCES change_sets(id) ON DELETE SET NULL,
  batch_id               UUID REFERENCES execution_batches(id) ON DELETE SET NULL,
  attempt_id             UUID REFERENCES execution_attempts(id) ON DELETE SET NULL,
  product_id             UUID REFERENCES products(id) ON DELETE SET NULL,
  channel_listing_id     UUID REFERENCES channel_listings(id) ON DELETE SET NULL,
  old_value              NUMERIC(14,4),
  new_value              NUMERIC(14,4),
  source_adapter_id      UUID REFERENCES source_adapters(id) ON DELETE SET NULL,
  rule_id                UUID REFERENCES transformation_rules(id) ON DELETE SET NULL,
  policy_violations      JSONB,
  override_reason        TEXT,
  channel_id             VARCHAR(100),
  freshness_check_result JSONB,
  metadata               JSONB,
  created_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_changeset ON audit_events(changeset_id, created_at);
CREATE INDEX idx_audit_product ON audit_events(product_id, created_at);
CREATE INDEX idx_audit_actor ON audit_events(actor_user_id, created_at);
CREATE INDEX idx_audit_created ON audit_events(created_at DESC);
```

### 13.5 Credential Handling

```
Scheme: AES-256-GCM
Key: PBKDF2-HMAC-SHA256(APPLICATION_SECRET, adapter_id || ':' || salt, iterations=100000)
Storage: (nonce || ciphertext || tag) in BYTEA column
Source: APPLICATION_SECRET env var — never in code; never in DB

Credentials never appear in: logs, SSE streams, AuditEvent.metadata, JSON responses
Admin "test connection" decrypts in-process only
```

### 13.6 Migration Approach (SQLite → PostgreSQL)

```
Step 1: Deploy new A2 tables to PostgreSQL (existing SQLite tables unchanged)
Step 2: Dual-write period (optional): SQLite for existing flows; PostgreSQL for new A2 tables
Step 3: Migration script pg_migrate.py:
  - Read SQLite: app_users, products_cache, change_history, audit_logs, etc.
  - Map: wc_id → products + channel_listings (channel_id = 'woocommerce')
  - Map: audit_logs → audit_events (extended schema)
  - Verify: row counts, spot-check values, report mismatches before cutover
Step 4: Reconciliation:
  SELECT COUNT(*) FROM products == products_cache row count
  SELECT COUNT(*) FROM channel_listings WHERE channel_id='woocommerce' == same
Step 5: Cutover (maintenance window):
  Enable maintenance mode
  Final SQLite → PostgreSQL sync
  Update DATABASE_URL
  Restart; smoke test
  Disable maintenance mode
Rollback: restore DATABASE_URL to SQLite; no data loss (SQLite never modified)
```

---

## 14. Durable Execution Recovery

### Per-Item Idempotency

```
idempotency_key = SHA256(changeset_item_id || '|' || str(attempt_number))
```

Sent to channel on every write. Channels supporting idempotency deduplicate on this key.
Channels that do not (WooCommerce) use the price comparison recovery path.

### Remote-Success / Local-Failure Recovery

```
On retry after suspected double-write:
  1. attempt_number++; new idempotency_key
  2. fetch_product(channel_product_id) → channel_price

  channel_price == proposed_value
    → Already applied; mark 'confirmed' with {recovered: true}. Do NOT write again.

  channel_price == old_value
    → Not applied; proceed with retry batch_write

  channel_price is something else
    → Unknown state; mark 'failed' with error='unexpected_channel_state'; admin review
```

### Crash Recovery

On worker restart, find `scheduled_changesets` with `status='executing'` and `claimed_by=this_worker`.
For each: load `execution_batches`; skip `completed`; resume from `pending`.
Already-completed batches are never re-executed (idempotent by design).

---

## 15. Implementation Sequence

**Owner mandate: Scheduling must not be introduced before channel abstraction, scoped
permissions, safety engine, rule engine, and canonical product model.**

```
Phase 1: Canonical Product Model
  products + channel_listings tables
  Migrate products_cache → products + channel_listings (WooCommerce channel)
  Reconcile: prices must match before Phase 2

Phase 2: Channel Adapter Layer
  channel_adapters, channel_execution_slots
  ChannelAdapter interface; WooCommerceAdapter wrapping existing woocommerce.py
  Live freshness verification mandatory from this phase forward
  All Apply paths route through ChannelAdapter
  Outcome: WooCommerce-specific code isolated behind interface

Phase 3: Scoped Permissions
  Extend app_users with scope JSONB (or dedicated user_scope_assignments table)
  effectiveHasScopedPerm; ScopeEnforcer; intersection semantics
  Existing users: scope=null (no behavior change)

Phase 4: Safety Policy Engine
  safety_policies table; PolicyEngine with 12 rule types
  Migrate alarm_thresholds → safety_policies (global warn rules)
  Outcome: configurable admin rules; existing thresholds preserved

Phase 5: Transformation Rule Engine
  transformation_rules table; RuleEngine; 5 rule types
  Default: ManualPriceRule (passthrough — no behavior change)

Phase 6: Change Set Engine + Immutable Dry Run
  change_sets, change_set_items, dry_run_digests,
  execution_batches, execution_attempts, approval_steps
  ChangeSetEngine; DryRunDigest; state machine; execution-time revalidation
  Existing Workspace continues in parallel

Phase 7: Source Adapter Layer
  source_adapters, field_mappings, source_checkpoints
  SourceAdapter interface; NextcloudAdapter wrapping nextcloud.py
  Field mapping UI; source stability validation; checkpoint system

Phase 8: Scheduling Engine  ← FIRST UNLOCKED after Phases 1–7
  scheduled_changesets, store_schedule_config
  SchedulerDaemon, QueueWorker, HeartbeatLoop, AbandonmentDetector
  Per-channel concurrency; DST-safe window computation

Phase 9: PostgreSQL Migration  (infrastructure; can run in parallel)
  Staging: PostgreSQL from Phase 1
  Production: PostgreSQL migration after Phase 6 (or earlier)
```

---

## 16. Workspace Compatibility

### Parallel Operation

```
Phases 1–7: Both flows active
  Workspace: POST /api/preview → SyncJob → products_cache → WooCommerce
  Change Set: SourceAdapter → ChangeSet → channel_listings → ChannelAdapter

Both flows write through ChannelAdapter (Phase 2+)
Both flows update channel_listings (Phase 1+)
Both flows produce AuditEvents
```

### Reconciliation (required before cutover)

```
reconcile():
  For each product in channel_listings WHERE channel_id='woocommerce':
    products_cache_price = products_cache.price WHERE wc_id = listing.channel_product_id
    if products_cache_price != listing.price: RECONCILIATION_MISMATCH

  Report: { matched, mismatched, workspace_only, listing_only }
  All mismatches investigated before cutover (target: 0 mismatches over 48h)
```

### Parity Tests (required before cutover)

- Same update through both flows → final channel state matches
- `change_history` entries equivalent
- AuditEvents equivalent
- Rollback works from both flows

### Cutover Criteria

```
1. Reconciliation passes (zero mismatches, 48h observation)
2. All parity tests pass
3. Owner explicitly approves cutover in writing

Until cutover: Workspace flow fully operational; no forced migration; no endpoint removal
```

---

## 17. Performance Considerations

| Operation | Target |
|---|---|
| Change Set draft creation (1,000 items) | < 5s |
| Dry Run (1,000 items, policy evaluation) | < 10s |
| DryRunDigest computation (1,000 items) | < 100ms |
| Pre-execution freshness check (1,000 products) | < 30s |
| Execution (1,000 items via WC adapter) | < 2 min |
| Source delta read (10,000-row source) | < 30s |
| Policy evaluation (per item) | < 1ms |
| Rule evaluation (per item, FX cached) | < 1ms |

**Freshness check:** WC allows large `?include=id1,id2,...` queries. Batch all 1,000
product IDs into minimal API calls. Target < 30s total including network roundtrip.

**FX rate:** Cache 1h; warm before batch starts; block execution if cache expired.

---

## 18. Risk Analysis

| Risk | Severity | Mitigation |
|---|---|---|
| Freshness check times out; execution proceeds | HIGH | `unverifiable` → hard block; no degraded mode |
| DryRunDigest hash differs due to non-canonical serialization | HIGH | Sort all inputs; use deterministic JSON serialization |
| Lease lost mid-batch; second worker double-writes | HIGH | `claim_lease_id` in heartbeat; batch UNIQUE constraint |
| PostgreSQL migration corrupts products | HIGH | Full SQLite backup; row count reconciliation; rollback path via DATABASE_URL |
| Scope null vs empty-list ambiguity | MEDIUM | Explicit: null = no restriction; [] = no access; documented in schema |
| DST shift causes window to fire at wrong local time | MEDIUM | Always compute in IANA local time; convert to UTC for storage |
| Rule change invalidates confirmed Change Set mid-night | LOW | Digest check detects it; seller notified; re-confirm required |
| Trusted Automation implemented without new owner decision | DESIGN | Deferred explicitly; no automation path exists in A2 |

---

## 19. Open Questions Resolved (from R0)

| # | Question | Resolution |
|---|---|---|
| 1 | Replace Workspace or parallel? | Parallel. Cutover requires reconciliation + parity + owner approval. |
| 2 | Second channel? | After WC adapter is in production and tested. |
| 3 | Native Pricing Table: Phase 1 or later? | Later. After source adapter interface is in production. |
| 4 | Trusted Automation: A2 or post-A2? | Deferred. Not in A2. |
| 5 | HistoricalDeviationRule require history? | Yes. Requires ≥ 30 days of price history in change_history. |
| 6 | FX rate max age? | Configurable. Default: 60 min. Execution blocked if cache expired. |
| 7 | Approval steps in A2 design? | Schema included. Disabled by default; activation requires owner policy decision. |

## 20. New Open Questions (R1)

| # | Question |
|---|---|
| 1 | Should freshness check batch size be configurable per channel adapter? |
| 2 | What is the fallback SKU strategy for products with no SKU in WooCommerce? |
| 3 | Should DryRunDigest invalidation notify the seller in real-time (SSE push) or wait for next session? |
| 4 | Should `scope_type = 'user'` in transformation_rules require admin review before activation? |
| 5 | Should `channel_execution_slots.max_concurrent` be configurable from Phase 8, or always 1 initially? |
