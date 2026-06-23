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
Schedule (now / deferred / low-traffic window)
  ↓
Apply
```

This is the primary workflow. Every feature addition must fit within or extend this model. Nothing replaces it.

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

**Spreadsheet contract — four defined roles:**

| Role | Description | Status |
|---|---|---|
| **Import** | User manually uploads a sheet to seed a Change Set in draft state | Supported (current Workspace flow) |
| **Export** | System writes confirmed price changes back to the sheet after apply | Optional; current writeback feature — not a required workflow step |
| **Event Source** | WooPrice detects changed rows vs. products_cache and proposes a Change Set automatically | Target state (not yet implemented) |
| **Optional Writeback** | After Apply, write confirmed values back to sheet for record-keeping | Optional; off by default in the target workflow |

**Constraints:**
- The spreadsheet must never be treated as authoritative truth for product prices.
- Full sheet scanning on every operation is an anti-pattern to eliminate.
- Writeback is retained as a feature but must not be a required step in any future workflow.

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

WooPrice will support 3–5 sales channels. WooCommerce is the first. Future channels include:

- Digikala
- SnapShop

Each channel:
- Has its own product catalog (may differ from WooCommerce)
- Has its own API credentials and rate limits
- Receives its own Change Set execution
- Is represented in the Permission model (scope can be channel-specific)

The Change Set model must be channel-aware from A2 forward. A Change Set targets one channel. Multi-channel updates use parallel Change Sets, one per channel.

All WooCommerce-specific code must be behind a channel adapter interface so future adapters can be added without touching core logic.

---

## Spreadsheet Strategy

### Target state

```
Full Fetch at 12:00
  ↓
WooPrice updates products_cache (prices, stock, categories)
  ↓
Spreadsheet row is changed by a user (one row)
  ↓
WooPrice detects the changed row (delta vs. current cache)
  ↓
Proposes a Change Set for the changed row only
  ↓
Seller reviews, schedules, applies
```

### Principles

1. **Do not re-read the entire spreadsheet repeatedly.** One full read per scheduled cycle. Delta detection for incremental changes.
2. **Spreadsheet changes are proposals, not commands.** A changed spreadsheet row creates a Change Set in draft state. Humans review and schedule before execution.
3. **Writeback is optional.** The writeback feature is retained for record-keeping convenience but must not be a required step in any workflow. Default: off.

### Short-term

The current Workspace (spreadsheet scan → preview → dry run → apply) remains operational. It is not removed in the 7.x stream. It is gradually replaced as the Change Set model matures.

---

## Priority Goals

In order of importance:

1. **Safe pricing operations** — No WC write without dry run validation. No scope violations. No unintended mass changes.
2. **Scheduling** — First-class deferred and windowed execution. Protect WC server.
3. **Scoped permissions** — Users operate only within their assigned Brand/Category/Channel.
4. **Multi-channel foundation** — Channel adapter interface designed before second channel is built.
5. **Lightweight synchronization** — Delta detection replaces full sheet scanning.
6. **AI Pricing** — Future. AI-suggested price recommendations based on market data, competition, and sales velocity. Not scheduled for current roadmap.

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

## Contract Index

The following decisions are expressed as explicit contracts that constrain implementation.
Any code, API, or UI design that touches these areas must read the corresponding section.

| Contract | Section in this file | Key constraint |
|---|---|---|
| Capacity contract | Change Set Capacity | Typical < 100; supported max 1,000; API must reject above 1,000 |
| Spreadsheet contract | Spreadsheet Strategy → Spreadsheet contract | Four roles: Import / Export / Event Source / Optional Writeback. Never system of record. |
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
