# WooPrice Owner Decisions

This document records authoritative decisions made by the project owner.
It is the canonical "why" behind architectural and product choices.

AI agents and developers must read this document before implementing any feature
that touches workflow, permissions, channels, data architecture, or scheduling.

When an owner decision conflicts with technical documents, owner decisions win.
When in doubt: ask the owner before implementing.

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

### Approval Philosophy

Approval is **optional**. It is **not** the default workflow.

- Most sellers apply their own Change Sets without requiring a second approver.
- Approval gates may be activated per policy (e.g., for large price swings or admin-configured thresholds).
- When approval is off (default): Change Set → Schedule → Execute directly.
- When approval is on (optional): Change Set → Approval Step → Schedule → Execute.

Do not design the system as if approval is always required. Do not prompt users for approval flows they did not configure.

---

## System-of-Record Decisions

### WooCommerce is the system of record for product data.

The WooPrice product cache is a read-optimized snapshot of WooCommerce. It is not authoritative. If cache and WooCommerce disagree, WooCommerce wins.

### The spreadsheet is NOT the system of record.

The spreadsheet is a human-maintained input device. It was historically used as the primary workflow driver ("scan sheet → apply prices"). This is being changed.

**Future spreadsheet role:**
- Import source: user manually imports a sheet to seed a Change Set
- Change event source: WooPrice detects changed rows and proposes a Change Set automatically

The spreadsheet must never be treated as authoritative truth for product prices. Full sheet scanning on every operation is an anti-pattern to eliminate.

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
3. **No writeback by default.** The current "writeback" feature (writing confirmed prices back to the sheet) may be retained as optional but should not be a required step in the workflow.

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
