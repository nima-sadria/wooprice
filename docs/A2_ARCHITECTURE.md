# WooPrice A2 Architecture Design

**Status:** Design only — no implementation. This document must be approved before
any A2 component is built.

**Prerequisites:** A1 session-derived design (background context), approved governance
in `docs/OWNER_DECISIONS.md`, `docs/PLATFORM_MAP.md`, `docs/ROADMAP.md`.

---

## 1. System Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          PRICE SOURCES                                   │
│  Nextcloud/OnlyOffice │ Excel Upload │ Numbers │ MySQL │ Custom DB       │
│  WooPrice Native Table                                                    │
└─────────────────────────────┬───────────────────────────────────────────┘
                               │  Source Adapter Layer  (Layer 1)
                               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    WOOPRICE CORE PLATFORM                                 │
│                                                                           │
│  ┌──────────────┐   ┌──────────────────┐   ┌───────────────────────┐    │
│  │ Source       │   │ Transformation    │   │ Safety Policy         │    │
│  │ Adapter      │──▶│ Rule Engine       │──▶│ Engine                │    │
│  │ Layer        │   │ (Layer 2)        │   │ (Layer 3)             │    │
│  └──────────────┘   └──────────────────┘   └───────────┬───────────┘    │
│                                                          │               │
│                            ┌─────────────────────────────▼─────────┐    │
│                            │          Change Set Engine (Layer 4)   │    │
│                            │  draft → dry run → confirm → schedule  │    │
│                            └─────────────────────┬─────────────────┘    │
│                                                   │                      │
│                            ┌──────────────────────▼──────────────────┐  │
│                            │        Scheduling Engine (Layer 5)      │  │
│                            │  now / deferred / low-traffic window    │  │
│                            └──────────────────────┬──────────────────┘  │
│                                                   │                      │
│         ┌─────────────────────────────────────────▼──────────────────┐  │
│         │              AI Layer (Layer 7)                             │  │
│         │  Error detection │ Freshness │ Competitor │ Automation      │  │
│         └────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────┬───────────────────────┘
                                                   │  Channel Adapter Layer (Layer 6)
                                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         DESTINATION CHANNELS                             │
│  WooCommerce (now) │ Digikala │ SnapShop │ Shopify │ Magento │ Amazon   │
│  Custom CMS                                                               │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Layer 1 — Source Adapter

### Purpose

Abstract WooPrice from any specific price source. Every source is accessed through
a common interface. Adding a new source type requires only a new adapter — no changes
to core logic.

### Adapter Interface

```
SourceAdapter
  ├── adapter_id: str
  ├── connect(config: SourceConfig) → ConnectionResult
  ├── test_connection() → HealthResult
  ├── get_schema() → SourceSchema            # field names, types, detected structure
  ├── read_full() → SourceSnapshot           # full read (for import or initial delta baseline)
  ├── read_delta(since: SourceCheckpoint) → DeltaSnapshot   # changed rows only
  └── write_back(rows: List[WriteBackRow]) → WriteBackResult  # Optional Writeback
```

### Source Types

| Adapter | Transport | Format | Status |
|---|---|---|---|
| NextcloudAdapter | WebDAV | XLSX | Implemented — only current adapter |
| ExcelUploadAdapter | HTTP multipart | XLSX / XLSM | Future |
| NumbersAdapter | Export conversion | XLSX/CSV via Numbers export | Future |
| MySQLAdapter | TCP / connection string | SQL query result | Future |
| CustomDBAdapter | Configurable via plugin | Any via adapter | Future |
| NativePricingTableAdapter | Internal DB | WooPrice `pricing_table` schema | Future |

### Field Mapping

Admin performs a one-time field mapping after connecting a source.
Mapping is saved per source. Re-validated on every read via schema fingerprint.

```
FieldMapping
  ├── product_id_field: SourceField   # REQUIRED: maps to wc_id / sku
  ├── price_field: SourceField        # REQUIRED
  ├── cost_field: SourceField | null  # for cost+profit rules
  ├── currency_field: SourceField | null
  ├── stock_field: SourceField | null
  └── custom_fields: Dict[str, SourceField]   # user-defined extensions
```

### Source Stability Validation

Before every read, the adapter validates:

| Check | Action on failure |
|---|---|
| Schema fingerprint matches stored mapping | Block import; prompt re-mapping |
| Product ID field populated in all rows | Block import with row-level error list |
| No duplicate product IDs within source | Warn with conflict list |
| Price field numeric / parseable | Block rows with parse errors |
| Currency field matches expected values | Warn on unrecognized values |
| Rial/Toman unit sanity (if currency = IRR) | Warn if price < 1,000 (likely wrong unit) |

Validation failures block Change Set creation. They never produce silent data errors.

### Source Checkpoint (Delta Detection)

```
SourceCheckpoint
  ├── adapter_id
  ├── last_read_at: datetime
  ├── row_hashes: Dict[product_id, str]   # hash of source row at last read
  └── schema_fingerprint: str
```

Delta read: compare current row hashes vs checkpoint. Changed rows → proposed Change Set.

### Native Pricing Table Schema

For users with no external source. Stored in WooPrice's own database.

```sql
pricing_table
  id          INTEGER PK
  product_id  VARCHAR    -- wc_id or sku
  name        VARCHAR
  price       DECIMAL(12,2)
  cost        DECIMAL(12,2)
  currency    VARCHAR(10)
  stock       INTEGER
  formula     VARCHAR    -- optional: 'cost * 1.3', 'cost * fx_usd + 500'
  updated_at  DATETIME
```

Simple formula support: expressions referencing `cost`, `fx_usd`, `fx_eur` variables.
No macro execution — parsed expression tree only, evaluated server-side.

---

## 3. Layer 2 — Transformation Rule Engine

### Purpose

Convert source values (cost, raw price, or formula) into a final channel price.
Rules are explicit, visible, and auditable. No hidden transformations.

### Rule Types

| Rule | Formula | Notes |
|---|---|---|
| `ManualPriceRule` | `final = source_price` | Direct passthrough |
| `CostPlusRule` | `final = cost + margin_amount` | margin_amount in source currency |
| `CostFXRule` | `final = cost × fx_rate + margin` | fx_rate from configured FX source |
| `CostFXFeeRule` | `final = cost × fx_rate + margin + channel_fee` | channel_fee from ChannelAdapter |
| `CompetitorRule` | `final = competitor_price ± adjustment` | Requires CompetitorDataSource (future) |
| `FormulaRule` | `final = eval(expression, context)` | Admin-defined; variables: cost, fx_usd, fx_eur, channel_fee |

### Rule Context

```
RuleContext
  ├── product_id
  ├── source_row: SourceRow
  ├── fx_rates: Dict[str, Decimal]     # from configured FX provider
  ├── channel_fees: Dict[str, Decimal] # from ChannelAdapter.get_fee_schedule()
  ├── competitor_prices: Dict[str, Decimal] | null   # future
  └── effective_date: datetime
```

### Rule Evaluation Output

```
PriceProposal
  ├── product_id
  ├── final_price: Decimal
  ├── currency: str
  ├── applied_rule_id: str
  ├── rule_chain: List[RuleApplication]   # every rule evaluated + why skipped/applied
  └── fx_rate_used: Decimal | null
```

`rule_chain` is stored on the ChangeSetItem for full audit provenance.

### Rule Precedence (most specific wins)

```
1. Explicit Change Set item override   (seller forces a specific value; allowed only if
                                        safety policy permits overrides for this seller)
2. User / seller scope rule            (rule for this seller's Brand/Category/Channel scope)
3. Brand rule                          (rule for the product's brand)
4. Category rule                       (rule for the product's category)
5. Channel / store rule                (rule for the destination channel)
6. Global default rule                 (store-wide fallback)
```

A seller's user-scope rule cannot exceed the maximum price change permitted by the
category or brand rule above it. Safety Policy Engine enforces this after transformation.

### FX Rate Source

FX rates are not embedded in rules. They are fetched separately and passed as context.

```
FXRateProvider (interface)
  ├── get_rates(base: str, targets: List[str]) → Dict[str, Decimal]
  └── get_rate_age() → timedelta   # how stale is the cached rate
```

Current implementation: `alanchand.com` API (already wired for IRR rates).
Future: configurable provider per store.

---

## 4. Layer 3 — Safety Policy Engine

### Purpose

Validate proposed prices against admin-configured rules before any Change Set item
is accepted. Failures produce warnings or blocks — never silent passes.

### Policy Rule Types

| Rule | Trigger | Default action |
|---|---|---|
| `MaxChangePercentRule` | `|new - old| / old > threshold` | warn |
| `CategoryLimitRule` | per-category max % | warn |
| `BrandLimitRule` | per-brand max % | warn |
| `UserLimitRule` | per-user/seller max % | warn |
| `ChannelLimitRule` | per-channel max % | warn |
| `MinPriceBoundRule` | `new < floor` | warn |
| `MaxPriceBoundRule` | `new > ceiling` | warn |
| `ZeroMissingRule` | `new == 0 or new is null` | warn |
| `RialTomanRule` | price < 1,000 and currency = IRR | warn |
| `ExtraZeroRule` | price ≥ 10× historical max | warn |
| `MissingZeroRule` | price ≤ 0.1× historical min | warn |
| `HistoricalDeviationRule` | price deviates > N stddev from product's 90-day history | warn |
| `BulkAnomalyRule` | > X% of batch are large changes | warn |

**Default for all rules: warn (not block). Admin must opt-in to block.**

### Policy Evaluation

```
PolicyEngine.evaluate(
  product_id,
  old_price,
  proposed_price,
  context: PolicyContext
) → PolicyResult

PolicyContext
  ├── user_id
  ├── channel_id
  ├── category_id
  ├── brand_id
  └── store_policies: List[PolicyRule]   # loaded from DB per store

PolicyResult
  ├── action: 'pass' | 'warn' | 'block'
  ├── violations: List[PolicyViolation]
  │     └── { rule_id, severity, message, old_value, proposed_value, threshold }
  └── override_allowed: bool   # admin can bypass if true
```

### Policy Store (DB schema sketch)

```sql
safety_policies
  id            INTEGER PK
  store_id      VARCHAR
  rule_type     VARCHAR     -- 'max_change_pct', 'category_limit', etc.
  scope_type    VARCHAR     -- 'global', 'category', 'brand', 'user', 'channel'
  scope_id      VARCHAR     -- category_id or brand_id or user_id or channel_id
  threshold     DECIMAL
  action        VARCHAR     -- 'warn' or 'block'
  enabled       BOOLEAN     DEFAULT TRUE
  updated_by    INTEGER     -- admin user_id
  updated_at    DATETIME
```

### Admin Override

Admin can bypass any warn or block rule. Override:
- requires explicit confirmation in UI ("I understand this bypasses the rule")
- always produces an `AuditEvent` with `override_reason`
- never silent

---

## 5. Layer 4 — Change Set Engine

### Purpose

The core workflow unit. Every price change flows through a Change Set.
Current Workspace (spreadsheet preview → dry run → apply) is re-expressed as a
Change Set producer in the target architecture.

### Core Entities

```
ChangeSet
  ├── id: UUID
  ├── created_by: user_id
  ├── channel_id: str                  # target channel
  ├── source_adapter_id: str           # where prices came from
  ├── field_mapping_id: str            # which mapping was used
  ├── scope: ScopeSpec                 # Brand/Category/Channel filter
  ├── schedule_mode: 'now' | 'deferred' | 'low_traffic'
  ├── scheduled_at: datetime | null
  ├── status: ChangeSetStatus
  ├── dry_run_id: UUID | null
  ├── approval_step_id: UUID | null    # future (second-party approval)
  ├── created_at: datetime
  └── updated_at: datetime

ChangeSetItem
  ├── id: UUID
  ├── changeset_id: UUID
  ├── product_id: int                  # wc_id
  ├── source_value: DECIMAL            # raw value from source
  ├── old_value: DECIMAL               # cache value at draft time
  ├── proposed_value: DECIMAL          # after transformation
  ├── applied_rule_id: str
  ├── rule_chain: JSON                 # full PriceProposal.rule_chain
  ├── policy_result: JSON              # full PolicyResult
  └── status: ItemStatus

DryRunReport
  ├── id: UUID
  ├── changeset_id: UUID
  ├── items_total: int
  ├── items_passed: int
  ├── items_warned: int
  ├── items_blocked: int
  ├── dry_run_status: 'passed' | 'warnings' | 'blocked'
  ├── blocked_items: List[ChangeSetItem]
  ├── warnings: List[PolicyViolation]
  └── created_at: datetime

ExecutionBatch
  ├── id: UUID
  ├── changeset_id: UUID
  ├── batch_index: int
  ├── item_ids: List[UUID]             # ChangeSetItem IDs in this batch
  ├── status: 'pending' | 'executing' | 'completed' | 'failed'
  ├── claimed_at: datetime | null
  ├── heartbeat_at: datetime | null
  └── completed_at: datetime | null
```

### Change Set State Machine

```
                     scope violation
draft ──────────────────────────────────────────────────► rejected
  │
  │ validate scope
  ▼
validating
  │
  ├─ pass ──► validated
  │
  └─ fail ──► invalid (items removed or changeset blocked)

validated ──► pending_dry_run
                │
                ▼
             dry_run_complete ──► dry_run_status = blocked ──► blocked
                │
                │ dry_run_status = passed or warnings
                ▼
             [pending_approval] ──► (future: if second-party approval enabled)
                │
                ▼ seller confirmation
             scheduled
                │
                ▼ scheduled_at reached OR now mode
             queued
                │
                ▼ ExecutionEngine claims it
             executing
                │
                ├─ all items OK ──────────────────────────► completed
                ├─ some items skipped (stale) ─────────────► partial
                └─ all items failed ──────────────────────► failed
                          │
                          ▼ (admin action)
                       rolled_back
```

### Scope Enforcement

Scope is checked at Change Set creation time. Out-of-scope products are rejected
immediately — not after dry run.

```
ScopeSpec
  ├── brands: List[str] | null        # null = all brands
  ├── categories: List[int] | null    # null = all categories
  └── channels: List[str] | null      # null = all channels

ScopeEnforcer.validate(user, changeset_items) → ScopeValidationResult
  ├── approved: List[ChangeSetItem]
  └── rejected: List[RejectedItem]    # with reason: 'out_of_scope'
```

Admin users are implicitly scoped to everything. No explicit scope assignment needed.

### Dry Run Contract (enforced in engine)

| Path | Dry Run Required |
|---|---|
| Change Set Apply | Yes — dry_run_status must be `passed` or `warnings` |
| Scheduled Apply | Yes — dry run must have passed before scheduling |
| Direct Edit | No — invalidates existing dry runs for the product |
| Emergency Apply | No — uses atomic claim + per-item freshness check |
| Rollback / Undo | No — reads from ChangeHistory |

---

## 6. Layer 5 — Scheduling Engine

### Purpose

Allow Change Sets to execute immediately, at a future time, or during a configured
low-traffic window. Scheduling is a first-class feature, not an afterthought.

### Schedule Modes

| Mode | Description | When to use |
|---|---|---|
| `now` | Execute immediately after seller confirmation | Urgent price corrections |
| `deferred` | Execute at a specific `scheduled_at` datetime | Planned price changes |
| `low_traffic` | Execute during the store's configured quiet hours | Bulk updates, catalog refreshes |

### Low-Traffic Window Configuration

```
StoreScheduleConfig
  ├── quiet_hours_start: time    # e.g., 00:00
  ├── quiet_hours_end: time      # e.g., 06:00
  ├── timezone: str              # e.g., 'Asia/Tehran'
  └── max_concurrent_jobs: int   # default 1 — no parallel execution
```

UI should surface "low-traffic window" as the recommended default selection.

### Scheduler Components

```
SchedulerDaemon
  Loop every 60s:
  ├── Find ChangeSets where:
  │     status = 'scheduled'
  │     AND (schedule_mode = 'now'
  │          OR scheduled_at <= now()
  │          OR (schedule_mode = 'low_traffic' AND now() IN quiet_hours))
  └── Move to 'queued'

QueueWorker
  Loop every 5s:
  ├── Claim one 'queued' ChangeSet (atomic UPDATE WHERE status='queued')
  ├── rowcount = 0 → another worker claimed it; skip
  └── Run ExecutionEngine(changeset)

HeartbeatMonitor
  Loop every 30s:
  ├── Find ExecutionBatches where:
  │     status = 'executing'
  │     AND heartbeat_at < now() - 30s
  └── Mark as 'failed'; mark ChangeSet as 'partial' or 'failed'
      (ExecutionEngine can resume on restart — checks for 'executing' batches)
```

### Execution Engine

```
ExecutionEngine.run(changeset_id):

  1. Load pending ExecutionBatches for this ChangeSet
     (skip any already 'completed' — idempotent resume after crash)

  2. For each batch:
     a. Claim batch (atomic UPDATE WHERE status='pending')
        rowcount = 0 → already claimed; skip

     b. For each item in batch:
        i.  Freshness check: current products_cache[product_id].price == item.old_value
            Mismatch → mark item 'skipped_stale'; continue
        ii. Call channel_adapter.write_prices([item])
            Success → update products_cache; insert ChangeHistory entry
            Failure → mark item 'failed'; continue (do not abort batch)

     c. Update batch heartbeat every 5 items
     d. Mark batch 'completed'

  3. Evaluate ChangeSet outcome:
     - All items succeeded → 'completed'
     - Some items skipped/failed, some succeeded → 'partial'
     - All items failed → 'failed'

  4. Insert AuditEvent for ChangeSet completion
```

### Batch Size

Default: 50 items per batch (WC Batch API accepts up to 100).
Configurable per channel adapter.
At 50 items/batch with 100ms inter-batch delay: ~2 min for 1,000 products.

---

## 7. Layer 6 — Channel Adapter

### Purpose

Abstract WooPrice from any specific commerce channel. WooCommerce is the first adapter.
All channel-specific logic is isolated behind this interface so new channels can be
added without modifying core engine code.

### Channel Adapter Interface

```
ChannelAdapter
  ├── channel_id: str
  ├── connect(config: ChannelConfig) → ConnectionResult
  ├── test_connection() → HealthResult
  │
  ├── fetch_products(filter: FetchFilter) → List[ChannelProduct]
  ├── fetch_product(product_id: str) → ChannelProduct
  │
  ├── write_prices(items: List[WriteItem]) → WriteResult
  ├── write_stock(items: List[StockWriteItem]) → WriteResult
  │
  ├── get_rate_limits() → RateLimitSpec
  ├── get_fee_schedule() → Dict[str, Decimal]   # channel fees per category/type
  └── get_batch_size_limit() → int
```

### Data Models

```
WriteItem
  ├── product_id: str           # channel-specific ID (wc_id, digikala_id, etc.)
  ├── field: 'price' | 'stock'
  ├── old_value: Decimal        # for stale detection
  ├── new_value: Decimal
  └── currency: str

WriteResult
  ├── succeeded: List[str]
  ├── failed: List[FailedWrite]
  │     └── { product_id, error_code, error_message, retryable: bool }
  ├── partial: bool
  └── rate_limit_remaining: int
```

### Channel Registry

```
ChannelRegistry
  ├── register(adapter: ChannelAdapter)
  ├── get(channel_id: str) → ChannelAdapter
  └── list_available() → List[ChannelMeta]
```

New channels are registered at startup. Core engine only calls the interface —
no channel-specific code in engine.

### WooCommerce Adapter (current)

Implementation details (already implemented, to be refactored behind interface):

- Batch write: `POST /wp-json/wc/v3/products/batch` (up to 100 items)
- Auth: consumer key + secret (not JWT — WC uses its own auth)
- Rate limiting: configurable per store; default 100ms inter-batch delay
- Error handling: HTTP 502 does not corrupt DB state (write confirmed only after success)
- Variation products: handled via `/wc/v3/products/{id}/variations/batch`

### Future Channel Adapters

| Channel | Expected complexity | Key differences |
|---|---|---|
| Digikala | Medium | REST API; different product ID scheme; IRR pricing |
| SnapShop | Medium | REST API; similar to Digikala |
| Shopify | Medium | GraphQL preferred; inventory / price are separate resources |
| Magento | High | REST + GraphQL; complex product types; attribute sets |
| Amazon | High | SP-API; region-specific; strict rate limits; ASIN mapping |
| Custom CMS | Low-Medium | Webhook-based; admin configures endpoint and payload template |

---

## 8. Layer 7 — AI Layer

### Design Principle

AI in WooPrice proposes, never auto-applies. Every AI output is a suggestion that
a human must review before it becomes a Change Set. The trusted automation path
allows scheduling — not applying — without human interaction per-run, but requires
initial human setup and a confirmation window.

### Components

#### 8.1 Error Detector

Runs at Change Set draft time, before scope validation.
Detects likely data entry errors in source rows.

```
ErrorDetector.scan(items: List[ChangeSetItem], context) → List[ErrorWarning]

Checks:
- price < 1,000 and currency = IRR → likely missing zeros (Rial/Toman confusion)
- price ≥ 100× old_value → likely extra zeros or wrong currency
- price = 0 → missing price
- price = old_value exactly → no change (informational, not an error)
- product_id not in products_cache → unmapped product
```

Output: pre-flight warning list shown in Change Set draft UI before submission.

#### 8.2 Market Freshness Monitor

Tracks how recently channel prices were verified / updated.

```
FreshnessMonitor
  ├── stale_threshold_days: int   # admin-configured; default 30
  ├── scan(products_cache) → List[StaleProduct]
  └── suggest_changeset(stale_products) → ChangeSetDraftSuggestion
```

Stale products are surfaced in the Dashboard and Product Browser.
Suggestions are Change Set drafts — seller reviews, modifies, and confirms.

#### 8.3 Competitor Awareness (Future)

```
CompetitorDataSource (interface)
  ├── fetch_prices(product_ids: List[str]) → Dict[str, Decimal]
  └── get_last_updated() → datetime

CompetitorRule feeds from this source (see Layer 2).
```

Competitor prices are never auto-applied. They inform `CompetitorRule` suggestions only.

#### 8.4 Trusted Automation Path

For stores with stable, predictable pricing (e.g., cost × FX + margin):

```
TrustedAutomationConfig
  ├── enabled: bool                 # off by default
  ├── rule_id: str                  # which transformation rule is trusted
  ├── scope: ScopeSpec              # which products/categories are in scope
  ├── safety_policy_id: str         # which safety policy must pass cleanly
  ├── schedule_mode: 'low_traffic'  # always low-traffic window for automation
  └── confirmation_window_hours: int  # human can cancel up to N hours before execution

Flow:
  1. FX rate updates → CompetitorDataSource updates (if configured)
  2. TrustedAutomationEngine evaluates affected products
  3. If ALL items pass safety policy cleanly (no warnings, no blocks):
     → Create ChangeSet → auto-schedule for low-traffic window
     → Notify owner: "Automation scheduled N items for 02:00"
     → Owner can cancel before execution window
  4. If ANY item triggers a warning or block:
     → Do NOT auto-schedule
     → Notify owner: "Automation paused: N items require review"
```

Auto-scheduling only happens when all safety rules pass. Any anomaly pauses automation
and requires human review. Admin override is always audited.

---

## 9. Data Flow Diagrams

### 9.1 Import → Change Set → Apply (full path)

```
Source
  │
  │ SourceAdapter.read_full() or read_delta()
  ▼
SourceSnapshot (rows with field mapping applied)
  │
  │ ScopeEnforcer.validate(user, items)
  ▼
Scoped items (out-of-scope rejected immediately)
  │
  │ RuleEngine.evaluate(item, context) for each item
  ▼
PriceProposals (each with rule_chain)
  │
  │ PolicyEngine.evaluate(item, old_price, proposed_price) for each item
  ▼
PolicyResults (pass / warn / block per item)
  │
  │ ChangeSetEngine.create_draft(items)
  ▼
ChangeSet [status: draft]
  │
  │ ErrorDetector.scan(items)  (AI pre-flight)
  ▼
ChangeSet + ErrorWarnings (shown to seller in UI)
  │
  │ Seller reviews, accepts
  ▼
ChangeSet [status: validated]
  │
  │ DryRun.run(changeset)
  ▼
DryRunReport
  │
  ├─ status = blocked → seller sees blocked items; fix and re-run
  │
  └─ status = passed / warnings → Seller confirms
         │
         ▼
      ChangeSet [status: scheduled, mode: now/deferred/low_traffic]
         │
         │ SchedulerDaemon picks up at scheduled time
         ▼
      ChangeSet [status: queued]
         │
         │ QueueWorker claims it
         ▼
      ExecutionEngine runs batches
         │
         ├─ For each item: freshness check → ChannelAdapter.write_prices()
         ├─ Success → products_cache update + ChangeHistory entry
         └─ Done → ChangeSet [completed / partial / failed]
                       │
                       ▼
                   AuditEvent + optional writeback to source
```

### 9.2 Scope Enforcement Flow

```
User requests Change Set creation
  │
  ├─ is_admin? ──YES──► skip scope check; proceed
  │
  └─ NO ──► load user.scope = [brand:samsung, category:phones]
               │
               ▼
            For each product in request:
              product.brand ∈ user.scope.brands? → pass
              product.category ∈ user.scope.categories? → pass
              both fail → reject item with 'out_of_scope'
               │
               ▼
            Rejected items returned to UI before Change Set is created
            (not a dry run failure — creation is blocked for out-of-scope items)
```

### 9.3 Event Source Delta Flow (future)

```
SourceWatcher wakes on schedule (or webhook trigger)
  │
  │ SourceAdapter.read_delta(since: last_checkpoint)
  ▼
DeltaSnapshot (changed rows vs last checkpoint)
  │
  │ Compare row values vs products_cache
  ▼
Changed products (value delta detected)
  │
  │ RuleEngine + PolicyEngine evaluate each changed product
  ▼
ChangeSetDraftSuggestion
  │
  │ Seller notification: "3 products changed in source; review proposed Change Set"
  ▼
Seller opens draft Change Set → reviews → confirms or modifies → schedules
```

---

## 10. Permission Model Extension

Current flat flags are extended with a scope dimension.

### Extended Permission Model

```
UserPermission
  ├── user_id
  ├── permission: str   # existing can_* flags
  └── scope: ScopeSpec  # null = global (admin-only)

ScopeSpec
  ├── brands: List[str] | null
  ├── categories: List[int] | null
  └── channels: List[str] | null
```

Migration path: existing users get `scope = null` (global) to preserve current behavior.
Admins assign scope when teams specialize.

### Permission Evaluation

```
effectiveHasScopedPerm(user, permission, product) → bool

1. user null → false
2. user.is_admin or user.is_super_admin → true (bypass all)
3. !user.permissions.can_access_site → false (global gate)
4. !user.permissions[permission] → false (feature gate)
5. user.scope == null → true (global scope — can act on any product)
6. product.brand ∈ user.scope.brands OR product.category ∈ user.scope.categories → true
7. → false (out of scope)
```

---

## 11. Audit Architecture

### AuditEvent (extended from current AuditLog)

```
AuditEvent
  ├── id: UUID
  ├── event_type: str          # 'changeset_created', 'dry_run_complete', 'item_applied', etc.
  ├── actor_user_id: int
  ├── actor_ip: str
  ├── changeset_id: UUID | null
  ├── batch_id: UUID | null
  ├── product_id: int | null
  ├── old_value: Decimal | null
  ├── new_value: Decimal | null
  ├── source_adapter_id: str | null
  ├── rule_id: str | null       # transformation rule applied
  ├── policy_violations: JSON | null
  ├── override_reason: str | null  # if admin bypassed safety rule
  ├── channel_id: str | null
  └── created_at: datetime
```

### Provenance by Operation (per Dry Run Contract)

| Operation | Required provenance |
|---|---|
| Change Set Apply | source row, rule_id, rule_chain, user_id, changeset_id, channel_id |
| Direct Edit | user_id, product_id, old_value, new_value |
| Emergency Apply | user_id, emergency_batch_id, product_id, old_value, new_value |
| Rollback | user_id, product_id, restored_from: ChangeHistory.id |
| Undo | user_id, product_id, restored_from: AuditLog.id |

---

## 12. Database Impact

### New Tables Required (A2 implementation phase)

| Table | Purpose |
|---|---|
| `source_adapters` | Registered source configurations |
| `field_mappings` | Per-source field mapping definitions |
| `source_checkpoints` | Delta detection state per source |
| `change_sets` | Change Set header |
| `change_set_items` | Per-product items within a Change Set |
| `dry_run_reports` | Dry run results and violation lists |
| `execution_batches` | Batch execution tracking |
| `safety_policies` | Admin-configured safety rules per scope |
| `transformation_rules` | Admin-configured rule definitions |
| `pricing_table` | Native pricing table (for users with no external source) |
| `channel_adapters` | Registered channel configurations |
| `audit_events_v2` | Extended audit log (replaces audit_logs over time) |

### Existing Tables (unchanged in A2)

`app_users`, `products_cache`, `sync_jobs`, `sync_items`, `change_history`,
`change_tracking`, `audit_logs`, `daily_metrics`, `emergency_batches`,
`emergency_items`, `app_settings`

The current Workspace workflow continues operating against existing tables.
A2 tables are additive.

---

## 13. Migration Strategy

### Phase ordering

```
Current state:  Workspace (source → preview → dry run → apply)  — operational
                Running against: sync_jobs, sync_items, change_history

A2 Phase 1:     Source Adapter Layer (P1)
                Define SourceAdapter interface; wrap existing NextcloudAdapter
                No user-visible change; internal refactor only

A2 Phase 2:     Change Set Engine (schema + state machine)
                New DB tables; new API endpoints (draft, validate, dry run, schedule)
                Workspace flow still operational in parallel

A2 Phase 3:     Scheduling Engine
                SchedulerDaemon, QueueWorker, HeartbeatMonitor
                First scheduling UI

A2 Phase 4:     Channel Adapter Layer
                Wrap existing WooCommerce code behind ChannelAdapter interface
                No second channel until interface is in production and tested

A2 Phase 5:     Transformation Rule Engine
                Rule types, rule store, rule evaluation
                Safety Policy Engine (first configurable rules)

A2 Phase 6:     Scope-based Permissions
                UserPermission extended; ScopeEnforcer wired into Change Set creation

A2 Phase 7:     AI Layer (Error Detector, Freshness Monitor first)
                CompetitorAwareness and Trusted Automation as follow-on

A2 Phase 8:     Second Channel Adapter (Digikala or SnapShop)
                Only after Phase 4 is in production and tested
```

Current Workspace is not removed until Change Set workflow covers 100% of its capabilities.
Both run in parallel during transition.

---

## 14. Performance Considerations

### Throughput targets

| Operation | Target |
|---|---|
| Change Set draft creation (1,000 items) | < 5s including scope check + rule eval |
| Dry Run (1,000 items) | < 10s |
| Execution (1,000 items at WC API rate) | < 2 min |
| Source delta detection (10,000 product source) | < 30s |
| Policy evaluation (per item) | < 1ms |
| Rule evaluation (per item, without FX fetch) | < 1ms |

### Bottlenecks and mitigations

| Bottleneck | Mitigation |
|---|---|
| FX rate fetch on every evaluation | Cache rates for 5 min; warm cache before batch |
| WC API rate limits | Adapter-declared limits; configurable inter-batch delay |
| Large Change Set serialization | Stream batch writes; never load all 1,000 items into memory at once |
| Source full read (large sheet) | Delta reads preferred; full read only on first import or schema change |
| Policy history queries (HistoricalDeviationRule) | Pre-compute 90-day stats on cache update; store as `price_stats` per product |

### Scale ceiling

| Resource | Current | A2 target |
|---|---|---|
| Products in cache | ~50,000 (tested) | 100,000 (target) |
| Change Set size | 1,000 max | 1,000 max (unchanged) |
| Concurrent Change Sets | 1 (current) | 1 per channel (future) |
| Channels | 1 | 3–5 |

---

## 15. Risk Analysis

| Risk | Severity | Mitigation |
|---|---|---|
| Source adapter breaks existing Workspace flow | HIGH | Nextcloud refactor is internal; no API change; parallel test run |
| Scope enforcement rejects admin users | HIGH | Admin always implicitly global-scoped; no assignment needed |
| Execution Engine double-claims a batch | HIGH | Atomic SQL UPDATE WHERE status='pending'; rowcount=0 check |
| Stale FX rate produces bad prices | HIGH | Rate age check before any batch; block if rate > configured max age |
| Safety policy set to block by default | MEDIUM | Default is always warn; opt-in required for block |
| Trusted Automation auto-schedules when it shouldn't | MEDIUM | Any safety warning pauses automation; confirmation window always present |
| Schema migration breaks existing data | MEDIUM | A2 tables are additive; existing tables unchanged until cutover |
| Second channel adapter corrupts product cache | MEDIUM | Each channel writes to its own cache partition; no cross-channel contamination |

---

## 16. Future Scalability

### Horizontal scaling readiness

The execution engine is designed for horizontal scaling from day one:
- Atomic SQL claim prevents double-execution across workers
- Heartbeat + abandon detection handles worker crashes
- Stateless workers — any worker can resume any ChangeSet

Currently: single QueueWorker. Future: multiple workers, one per channel,
coordinated by atomic claim on `execution_batches`.

### Multi-tenant readiness

Current: single-store internal platform. Future consideration: if WooPrice ever
becomes multi-tenant, the `store_id` column on `safety_policies`, `transformation_rules`,
`source_adapters`, and `channel_adapters` isolates configuration per store.
No architectural changes needed — `store_id` is already in the schema sketch.

### Pluggable adapters

Both SourceAdapter and ChannelAdapter are defined as interfaces (protocols in Python).
Future adapters can be registered as plugins without modifying core code.
This enables a marketplace model where third-party developers contribute adapters.

---

## 17. Open Questions for Owner Decision

The following questions must be answered before A2 implementation begins:

| # | Question | Options |
|---|---|---|
| 1 | Should A2 replace the current Workspace flow or run in parallel? | Parallel (recommended) / Replace immediately |
| 2 | Which channel should be the second adapter? | Digikala / SnapShop / other |
| 3 | Should the Native Pricing Table be part of A2 Phase 1 or a later phase? | Phase 1 / Later |
| 4 | Is Trusted Automation in scope for A2 or post-A2? | A2 / Post-A2 |
| 5 | Should HistoricalDeviationRule require a price history period before activating? | Yes (N days) / No |
| 6 | What is the FX rate max age before blocking a Change Set? | 1 hour / 4 hours / configurable |
| 7 | Should approval steps (second-party) be designed in A2 or deferred? | Design in A2 (no implementation) / Defer entirely |
