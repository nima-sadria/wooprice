# WooPrice Owner Decisions

This document records authoritative decisions made by the project owner.
It is the canonical "why" behind architectural and product choices.

AI agents and developers must read this document before implementing any feature
that touches workflow, permissions, channels, data architecture, or scheduling.

When an owner decision conflicts with technical documents, owner decisions win.
When in doubt: ask the owner before implementing.

---

## Document Authority Matrix

Documents have authority within their domain. Conflicts across domains are resolved by domain,
not by a single global ranking.

| Domain | Authoritative document | Wins over | Examples of questions it answers |
|---|---|---|---|
| **Policy** — what the product must do and why | `docs/OWNER_DECISIONS.md` (this file) | Everything else | Is approval required? What is the spreadsheet's role? What channels are supported? |
| **Delivery process** — how changes are shipped safely | `docs/WORKFLOW.md` | PLATFORM_MAP, ARCHITECTURE, ROADMAP | What gates must pass before a commit? What counts as a HIGH audit finding? |
| **Agent control** — which operations require human sign-off | `docs/OWNER_AGENT_WORKFLOW.md` | AI_OPERATING_MANUAL (gate list only) | When must an AI agent stop and wait? What text constitutes approval? |
| **Sequencing** — what gets built and when | `docs/ROADMAP.md` | PLATFORM_MAP Section E, ARCHITECTURE future items | Is S2 blocked on S1? Is 7.7B planned or in progress? |
| **Current implementation truth** — what the code actually does today | Code + database schema | All documents | Does Products.tsx have inline editing? Which routes are guarded? |
| **Derived references** — structured summaries of the above | `docs/PLATFORM_MAP.md`, `docs/ARCHITECTURE.md` | Each other | Convenience maps of routes, permissions, APIs. Must not conflict with code or policy. |

**Conflict resolution rules:**

1. **Policy conflict:** If this file contradicts ARCHITECTURE.md or PLATFORM_MAP.md on a policy question (approval, scope, channels, scheduling), this file wins. Update the lower-authority doc.
2. **Factual conflict:** If code contradicts any document on a factual claim ("does this endpoint exist?", "is this feature implemented?"), code wins. Update the document.
3. **Sequencing conflict:** If ROADMAP.md contradicts PLATFORM_MAP Section E on item status, ROADMAP.md wins. Update PLATFORM_MAP.
4. **Unresolvable conflict:** If the conflict cannot be resolved by domain (e.g., two policy questions contradict each other within this file), stop and escalate to the owner. Do not pick a side.

---

## Business Context

### Business Type

WooPrice is an **internal enterprise platform**, not a SaaS product.

- Single organization
- Multiple internal teams sharing one installation
- No public-facing user registration
- No per-tenant billing or isolation at the application level

### Primary Users

| Team | Primary Use |
|---|---|
| Sales Team | Create and schedule price change proposals within assigned scope |
| Purchasing Team | Create cost-based price adjustments; track change history |
| Management Team | Review analytics; oversight of scheduled changes |

### Non-Goals

- Public user self-registration
- Per-customer pricing logic
- Marketplace seller onboarding
- External API for third-party integrations (short-term)
- Real-time price feeds or websocket market data

---

## Workflow Authority

### Canonical Workflow

```
Seller
  ↓
Change Set (scoped to seller's assigned brands/categories/channels)
  ↓
Dry Run (validate scope, price anomalies, safety rules)
  ↓
Seller Confirmation (seller reviews dry run result and triggers execution)
  ↓
Schedule (now / deferred / low-traffic window)
  ↓
Apply (execute to channel)
```

This is the primary workflow. Every feature addition must fit within or extend this model.
Nothing replaces it.

### Dry Run Contract

Dry Run is **required** for some write paths and **not required** for others.
Do not make universal statements like "no channel write without dry run" — they are inaccurate.

| Write path | Dry Run required? | Notes |
|---|---|---|
| Spreadsheet Apply (current Workspace flow) | **Yes** | Dry run must pass before Apply is enabled |
| Change Set Apply (future) | **Yes** | Dry run is mandatory step in canonical workflow |
| Scheduled Change Set Apply (future) | **Yes** | Dry run must have passed before scheduling |
| Direct Edit (price/stock inline edit) | **No** | No dry run gate; invalidates existing dry runs for the product |
| Emergency Apply | **No** | No dry run gate; uses atomic claim + per-item freshness check instead |
| Rollback | **No** | No dry run gate; admin-only; reads old_value from ChangeHistory |
| Undo | **No** | No dry run gate; admin-only; reads from audit history |

**Exempt path safety controls:** Direct Edit, Emergency Apply, Rollback, and Undo do not
require dry run but each has its own safety controls:
- Direct Edit: invalidates all open dry runs for the affected product
- Emergency Apply: atomic SQL claim prevents double-execution; per-item freshness check detects stale prices
- Rollback and Undo: admin-only; produce ChangeHistory entries and audit log entries

### Approval Policy

There are two distinct confirmation concepts. Do not conflate them:

| Concept | Description | Status |
|---|---|---|
| **Seller confirmation** | The seller who created the Change Set reviews the dry run and explicitly triggers execution. This is always required. | Implemented (current Apply flow) |
| **Second-party approval** | A different person (manager, admin, or peer) must review and approve before execution. | Optional, disabled by default, not yet implemented |

**Second-party approval (opt-in):**

| State | Behavior |
|---|---|
| Default (approval off) | Change Set → Dry Run → Seller confirms → Schedule → Execute |
| Approval enabled (opt-in) | Change Set → Dry Run → Approver reviews → Approval Step → Seller schedules → Execute |

- Second-party approval is activated per policy — for example, admin-configured thresholds for large price swings.
- Most sellers apply their own Change Sets without requiring a second approver.
- The system must not require or prompt for approval unless a policy rule explicitly activates it.
- No second-party approval workflow is scheduled for implementation until A2+ architecture is designed.

**Implementation constraint:** Do not design data models, APIs, or UI components that assume second-party approval is always present. It is an optional layer. Seller confirmation (first-party review) is always present and is not "approval" in the second-party sense.

---

## System-of-Record Decisions

### WooCommerce is the system of record for product data.

The WooPrice product cache is a read-optimized snapshot of WooCommerce. It is not authoritative. If cache and WooCommerce disagree, WooCommerce wins.

### The spreadsheet is NOT the system of record.

The spreadsheet is a human-maintained input device. It was historically used as the primary workflow driver ("scan sheet → apply prices"). This is being changed.

**Source contract — four defined roles:**

| Role | Definition | Status |
|---|---|---|
| **Import** | Read source data (rows, prices, stock) into WooPrice. Creates a Change Set or preview. | Implemented (current Workspace flow reads Nextcloud XLSX) |
| **Export** | Generate an outbound file or table *from* WooPrice for an external system (e.g., accounting, archive). Source file is not modified. | Not yet implemented |
| **Optional Writeback** | Write WooPrice-calculated results *back to the source file* when explicitly enabled. This updates the same file that was imported. | Implemented (current writeback feature — off by default; must not be a required step) |
| **Event Source** | WooPrice monitors source for row-level changes and automatically proposes a Change Set for changed rows only. | Target state — not yet implemented |

**Constraints:**
- The source must never be treated as authoritative truth for product prices.
- Full source scanning on every operation is an anti-pattern to eliminate.
- Optional Writeback is retained as a convenience feature; it must not be a required workflow step.
- Export and Optional Writeback are distinct: Export generates new output; Writeback modifies the original source.

---

## Permission Philosophy

### Scope-Based Permissions

Admin assigns user scope once. Scope may be expressed as one or more of:

| Scope Type | Example |
|---|---|
| Brand | Samsung, Apple, Xiaomi |
| Category | Laptops, Phones, Accessories |
| Store / Channel | WooCommerce-Main, Digikala-Store |

A user can only create Change Sets that contain products within their assigned scope.
Attempting to include out-of-scope products in a Change Set must be rejected at creation time.

### Current vs. Future Model

**Current (flat flags):** `can_edit_price = true` applies to all products.

**Target:** `can_edit_price = true, scope = [brand:samsung, brand:apple]` applies to Samsung and Apple products only.

Scope enforcement is a new layer on top of existing permission flags. The existing flag system remains; scope is additive.

### Admin Scope

Admins are implicitly scoped to everything. Admin scope does not need explicit assignment.

---

## Scheduling Philosophy

Scheduling is a first-class feature. It is not optional.

Every Change Set must have a schedule mode:
- **Now**: execute immediately after dry run
- **Deferred**: execute at a specific future time
- **Low-traffic window**: execute during configured quiet hours (e.g., 00:00–06:00)

Users should be encouraged to schedule changes during low-traffic windows by default. The UI should surface this as a recommended option.

Scheduling protects:
- WooCommerce server load
- Database write contention
- Customer-facing price stability during peak hours

---

## Change Set Capacity

### Defined capacity bounds

| Tier | Description |
|---|---|
| **Typical** | < 100 products per Change Set. Covers the overwhelming majority of daily operations (one brand, one category, one seller's weekly update). |
| **Supported** | Up to 1,000 products per Change Set. System must handle this without degradation. |
| **Not supported** | > 1,000 products in a single Change Set. Use multiple Change Sets or the Fetch/Sync engine instead. |

### Rationale

Internal teams update pricing by brand or category. A typical brand has 20–80 products.
The 1,000-product ceiling provides a 10× safety margin while keeping batch execution times
predictable (< 2 minutes at WC batch API rate limits).

### Implementation constraints

- Change Set creation must reject or warn when item count exceeds 1,000.
- Progress reporting and timeout handling must be designed for the 1,000-product ceiling.
- Bulk engine (7.7A) must enforce this ceiling at the API layer.

---

## Multi-Channel Strategy

WooPrice is a channel-agnostic pricing platform. WooCommerce is the first supported channel.

### Target channel list

| Channel | Priority | Type |
|---|---|---|
| WooCommerce | Now — implemented | E-commerce platform |
| Digikala | Next — near-term | Iranian marketplace |
| SnapShop | Near-term | Iranian marketplace |
| Shopify | Future | E-commerce platform |
| Magento | Future | E-commerce platform |
| Amazon | Future | Global marketplace |
| Custom CMS | Future | Any store via adapter |

WooPrice must not be architecturally locked to WooCommerce. Every WooCommerce-specific
operation must be behind a channel adapter interface so future channels can be added
without modifying core logic.

### Channel model

Each channel:
- Has its own product catalog (may differ from WooCommerce)
- Has its own API credentials, rate limits, and field schema
- Has its own price validation rules and submission format
- Receives its own Change Set execution
- Is represented in the permission scope model (scope can be channel-specific)

### Execution model

A Change Set targets one channel. Multi-channel price updates use parallel Change Sets,
one per channel. There is no cross-channel transaction — each channel's execution is
independent.

### Implementation constraint

All WooCommerce-specific code must be behind a channel adapter interface before any
second channel is built. The interface must be designed in A2 and approved before
implementation begins.

---

## Price Source Strategy

**Strategic principle:** WooPrice must ask where the price source is, not assume one exists.
The spreadsheet is a supported source, not the identity of WooPrice.

### Supported source types

| Source type | Description | Status |
|---|---|---|
| Nextcloud / OnlyOffice spreadsheet | XLSX file via WebDAV | Implemented — only current source adapter |
| Excel file upload | Direct .xlsx upload without WebDAV | Future — source adapter required |
| Apple Numbers | .numbers file via export/conversion | Future |
| MySQL / MariaDB | Direct database query | Future |
| Custom database | Any DB via configured adapter | Future |
| WooPrice native pricing table | Built-in table within WooPrice | Future |

### Source selection model

WooPrice must present a source selection step before any sync or Change Set workflow.
The system should not silently assume Nextcloud or any other specific source.

If the user already has an external source (spreadsheet or database):
- WooPrice connects to it using the appropriate adapter
- Admin performs a one-time field mapping: source columns → WooPrice fields

**Example field mapping:**

| Source field | WooPrice field |
|---|---|
| Column A (or `product_name`) | Product Name |
| Column B (or `price`) | Price |
| Column C (or `cost`) | Cost |
| Column D (or `currency`) | Currency |
| Column E (or `stock`) | Stock |

Field mapping is saved per source. It must be re-validated when the source schema changes.

If the user does not have an external source:
- WooPrice provides a **native pricing table** with:
  - Product name, Product ID / SKU, Price, Cost, Currency, Stock
  - Simple formulas (cost + margin, cost × rate)
  - Percentage calculations
  - Basic formatting (highlight, sort, filter)
  - No external dependency

### Source stability validation

Before accepting data from any source, WooPrice must validate:

| Rule | Description |
|---|---|
| Stable product IDs | Product IDs or SKUs do not change between reads |
| Stable column mapping | Source schema has not changed since last mapping |
| No missing required values | Price, product ID, and currency fields are populated |
| No currency / unit mismatch | Rial vs. Toman vs. USD detected and flagged |
| No duplicate conflicting product IDs | Same product ID appears with different prices in the same source |
| No unexpected schema change | New columns, removed columns, or reordered columns must trigger a re-mapping prompt |

Validation failures must block Change Set creation, not produce silent data errors.

### Spreadsheet subsection (current implementation)

The current Workspace (Nextcloud XLSX scan → preview → dry run → apply) remains
operational. It is the only implemented source path. It is not removed in the 7.x stream.
It is gradually wrapped into the multi-source model as the source adapter layer matures.

**Delta detection target state:**

```
Full Fetch at 12:00
  ↓
WooPrice updates products_cache (prices, stock, categories)
  ↓
Source row is changed by a user (one row, any source)
  ↓
WooPrice detects the changed row (delta vs. current cache)
  ↓
Proposes a Change Set for the changed row only
  ↓
Seller reviews, schedules, applies
```

**Principles:**
1. Do not re-read the entire source repeatedly. One full read per scheduled cycle. Delta detection for changes.
2. Source changes are proposals, not commands. A changed row creates a Change Set in draft state. Humans review and schedule before execution.
3. Writeback is optional. The writeback feature (writing confirmed prices back to the source) is retained for record-keeping but must not be a required workflow step. Default: off.

---

## Transformation Rules

Price transformation rules define how WooPrice converts a source value (cost, import price,
or raw field) into a final channel price. Rules must be adjustable per product, category,
brand, channel, and user scope.

### Supported rule types

| Rule type | Description |
|---|---|
| Manual price | Use the source price value directly with no transformation |
| Cost + profit | `final_price = cost + profit_amount` |
| Cost × FX rate + profit | `final_price = cost × fx_rate + profit_amount` |
| Cost × FX rate + profit + fees | `final_price = cost × fx_rate + profit_amount + channel_fee` |
| Competitor-based | `final_price = competitor_price ± adjustment` (future, requires competitor data source) |
| Channel-specific | Override any rule with a channel-specific value or formula |

### Rule precedence

When multiple rules could apply to a product, precedence is (most specific wins):

1. Explicit Change Set override — seller overrides the rule for this specific Change Set item, if allowed by safety policy
2. User / seller scope rule — rule configured for this specific seller's scope (Brand/Category/Channel assignment)
3. Brand-level rule
4. Category-level rule
5. Channel / store rule — rule configured for the destination channel
6. Global default rule (least specific)

The most specific rule always wins. Admin configures which rules exist and at which level.
A seller's user-scope rule cannot exceed the bounds set by the admin's category or brand rule.

### Implementation constraints

- Transformation rules are not implemented yet. They are a future capability.
- Rule engine design must be part of A2+ architecture.
- No rule engine code before A2 is approved.
- FX rate sourcing must be separate from rule evaluation (rules reference an FX rate source, they do not embed it).

---

## Safety Rules Configuration

Safety rules protect against unintended price changes. They must be configurable by
store admin, not hardcoded.

### Admin-configurable rule types

| Rule | Description |
|---|---|
| Maximum price-change percentage | Block or warn when a price changes by more than N% vs. last known value |
| Category-specific limits | Different max-change rules per product category |
| Brand-specific limits | Different max-change rules per brand |
| User-specific limits | Different max-change rules per seller user |
| Channel-specific limits | Different limits for WooCommerce vs. Digikala vs. other channels |
| Minimum price bound | Reject prices below an absolute floor |
| Maximum price bound | Reject prices above an absolute ceiling |
| Zero / missing detection | Flag products with price = 0 or price = missing |
| Rial / Toman anomaly detection | Detect price values that appear to be in the wrong unit (e.g., 10 vs. 10,000,000) |
| Historical deviation detection | Flag prices that deviate significantly from the product's own price history |
| Bulk anomaly detection | Flag when a batch contains an unusual proportion of large changes |
| Admin override | Admin can bypass any rule with explicit confirmation and audit log entry |

### Rule behavior model

Each rule has two configurable actions:

| Action | Description |
|---|---|
| **warn** | Change Set proceeds; admin sees a warning; audit log records the warning |
| **block** | Change Set creation is rejected until the rule violation is resolved |

Default behavior for all rules: **warn** (not block). Admin must explicitly set a rule to block.

### Implementation constraints

- Current safety rules (alarm thresholds, dry_run_status blocked/warnings) remain operational.
- The configurable rule system described above is a future capability, designed in A2+.
- Any new safety rule implementation must not weaken existing dry run or apply protections.
- Admin override must always produce an audit log entry — it must never be silent.

---

## Priority Goals

In order of importance:

1. **Safe pricing operations** — Spreadsheet Apply and Change Set Apply require dry run validation before execution. Direct Edit, Emergency Apply, Rollback, and Undo are exempt from dry run but each has dedicated safety controls. No scope violations. No unintended mass changes. Configurable safety rules protect every write path.
2. **Scheduling** — First-class deferred and windowed execution. Protect channel server load.
3. **Scoped permissions** — Users operate only within their assigned Brand/Category/Channel.
4. **Multi-source architecture** — WooPrice is not locked to one price source. Source adapter interface designed before adding source type 2.
5. **Multi-channel foundation** — Channel adapter interface designed before second channel is built.
6. **Transformation rules engine** — Adjustable per-product, per-category, per-brand, per-channel price calculation rules.
7. **Lightweight synchronization** — Delta detection replaces full source scanning.
8. **AI Pricing** — Future. AI-suggested price recommendations based on market data, competition, and sales velocity. Not scheduled for current roadmap.

---

## Strategic Principles

These principles constrain all architectural decisions. They override convenience choices.

1. **WooPrice is not a spreadsheet tool.** The spreadsheet is one supported source type among many. Architecture must not assume a spreadsheet exists.

2. **WooPrice is not a WooCommerce plugin.** WooCommerce is one supported channel. Architecture must not assume WooCommerce is the only destination.

3. **The source adapter and channel adapter are independent.** Changing the price source does not change the destination channel, and vice versa. These are separate layers.

4. **Safety rules are configurable, not hardcoded.** Admin defines what constitutes an anomaly for their store. WooPrice provides the rule engine; the store provides the thresholds.

5. **Transformation rules are explicit and visible.** The user must be able to see exactly how a source value becomes a final channel price. No hidden transformations.

6. **All writes are auditable.** Every price change sent to a channel must be traceable to a source row, a transformation rule, a user, and a Change Set.

---

## Future AI Strategy

AI Pricing is a future capability, not a current project.

When designed, it will:
- Suggest optimal prices based on sales velocity, competition, and cost inputs
- Surface suggestions as proposed Change Sets (not auto-apply)
- Require seller review and approval before any Change Set is submitted
- Be scoped to the seller's assigned brands and categories

AI will never auto-apply prices without human confirmation. It proposes; humans decide.

---

## Decisions Log

| Date | Decision | Rationale |
|---|---|---|
| 2026-06-23 | Approval is optional, not default | Internal teams trust each other; approval adds friction without risk reduction for typical operations |
| 2026-06-23 | Spreadsheet is not system of record | WooCommerce prices are authoritative; spreadsheet is a human input tool |
| 2026-06-23 | Scope model: Brand/Category/Channel | Sales team members specialize by product category; they should not accidentally modify out-of-scope products |
| 2026-06-23 | Multi-channel: 3–5 channels target | Digikala and SnapShop are planned; channel adapter pattern prevents future rewrites |
| 2026-06-23 | Scheduling is first-class | WooCommerce on shared hosting; overnight bulk runs reduce customer-visible disruption |
| 2026-06-23 | AI Pricing is future-only | Current priority is operational reliability; AI suggestions require clean data foundation first |
| 2026-06-23 | Change Set capacity: typical <100, supported up to 1000 | Reflects internal team size and WC batch API practical ceiling |
| 2026-06-23 | Spreadsheet contract: Import / Export / Event Source / Optional Writeback | Four distinct roles defined; prevents role confusion in future implementation |
| 2026-06-23 | Document authority matrix established | Resolves conflicts without escalating every disagreement to the owner |
| 2026-06-24 | Multi-source architecture: WooPrice is not locked to one spreadsheet provider | Spreadsheet is a supported source type; architecture must support Excel, OnlyOffice, Numbers, MySQL, custom DB, native table |
| 2026-06-24 | Multi-channel expanded: target includes Shopify, Magento, Amazon, custom CMS | WooPrice is a channel-agnostic platform, not a WooCommerce plugin |
| 2026-06-24 | Transformation rules are adjustable per product/brand/category/channel | Internal pricing logic varies by team and channel; hardcoded rules prevent adoption |
| 2026-06-24 | Safety rules are admin-configurable, not hardcoded | Store admin defines anomaly thresholds; WooPrice provides the rule engine |
| 2026-06-24 | Native pricing table: WooPrice must support users with no external source | Not all users have a spreadsheet or external DB |
| 2026-06-24 | Source stability validation required before Change Set creation | Silent schema drift causes data corruption; explicit validation gates catch it early |

## Contract Index

The following decisions are expressed as explicit contracts that constrain implementation.
Any code, API, or UI design that touches these areas must read the corresponding section.

| Contract | Section in this file | Key constraint |
|---|---|---|
| Capacity contract | Change Set Capacity | Typical < 100; supported max 1,000; API must reject above 1,000 |
| Price source contract | Price Source Strategy | Multi-source: Nextcloud/Excel now; Apple Numbers, MySQL, custom DB, native table future. Source is not the identity of WooPrice. |
| Spreadsheet contract | Price Source Strategy → Spreadsheet subsection | Four roles: Import / Export / Event Source / Optional Writeback. Never system of record. |
| Transformation rules contract | Transformation Rules | Rule types and 6-level precedence defined; rule engine is future (A2+); no engine code before A2 approved. |
| Dry Run contract | Workflow Authority → Dry Run Contract | Spreadsheet/ChangeSet Apply require dry run; Direct Edit, Emergency Apply, Rollback, Undo are exempt with own safety controls. |
| Safety rules contract | Safety Rules Configuration | Admin-configurable warn/block rules; defaults to warn; admin override always audited. |
| Approval contract | Workflow Authority → Approval Policy | Seller confirmation always required. Second-party approval optional, disabled by default, not yet implemented. |
| Scope contract | Permission Philosophy | Out-of-scope products rejected at Change Set creation. Admins implicitly global scope. |
| Scheduling contract | Scheduling Philosophy + Change Set Capacity | Three modes (Now / Deferred / Low-traffic). No scheduling code until A2 approved. |
| Multi-channel contract | Multi-Channel Strategy | One Change Set per channel. WC adapter required before adding channel 2. |

---

## AI Resource Policy

- Prefer single-agent execution.
- Avoid parallel agent spawning.
- Avoid subagent-heavy workflows.
- Keep implementation, audit, and architecture work separated into dedicated conversations.
- Use concise context snapshots instead of extremely long sessions.
