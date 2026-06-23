# WooPrice Roadmap

## Current Status

Current branch: main
Current feature stream: 7.x

---

## Completed

### Migration Era (Phases 1–6)

| Phase | Description | Commit |
|---|---|---|
| Phase 1–3 | Core backend: FastAPI, product cache, sync engine, auth | — |
| Analytics Sprint A | Analytics page | `f4ab6cb` |
| Auth Integration | AuthProvider, JWT, RequirePermission | bundled |
| Direction Layer | RTL/LTR support, Tailwind logical properties | `585373e` |
| Phase 4c | Logs page migration | `bf1d458` |
| WS-A | Workspace shell, cache refresh, spreadsheet status | `4b38182` |
| WS-B | Preview SSE, pre-fetch filters, product table | `4b38182` |
| WS-C | Dry Run, Apply SSE, Writeback, Inline edit, Rollback | `6bb8342` |
| WS-D | Integration audit: H-D1 and MD-2 found and resolved | `6bb8342` |
| Phase 5 | Production cutover preparation, documentation | `377acae` |
| Phase 6 | Legacy frontend replacement, React SPA cutover | shipped |

### 7.x Feature Stream (completed)

| Item | Description | Notes |
|---|---|---|
| 7.4A | Product Browser | Server-side filter, sort, paginate, category multi-select |
| 7.4A R1 | Bug fixes | stock_status=all, enum validation |
| 7.4A R2 | Remediation | Page size persistence, price filter parity, deterministic sort |
| 7.4B | Permission Architecture Review | Analysis only |
| 7.5A | Route Security Hardening | /workspace, /settings guards; permission-aware sidebar |
| 7.5A R1 | Permission Inheritance Remediation | effectiveHasPerm, can_access_site gate, 24 tests |
| 7.5A R2 | /home Route Guard + Component Tests | 50 component tests, PLATFORM_MAP accuracy fixes |
| A1 | Change Set Platform Architecture Design | Design only — no implementation |

---

## Current Phase: 7.x Feature Stream

The 7.x numbering is an implementation-level feature stream running within the broader product development effort. It is separate from the Phase 1–6 migration era numbering.

See `docs/PLATFORM_MAP.md` Section E for the detailed 7.x roadmap tree.

Near-term items:

| Item | Description | Status |
|---|---|---|
| 7.5B | Permission Model V2 (can_browse_products, can_dry_run splits) | Planned |
| 7.5C | Admin UX Rebuild | Planned |
| 7.6A | Settings Center | Planned |
| 7.6B | Product Browser Advanced Filters | Planned |
| 7.7A | Bulk Edit Framework | Design complete (A1); implementation pending |
| 7.7B | Inline Editing in Product Browser (price/stock edit in rows) | Planned |
| 7.8A | Dashboard Redesign | Planned |
| 7.9A | Saved Views | Planned |

---

## Strategic Direction (Owner Decisions)

The following represents the owner-authorized product direction. These items require
architecture design before implementation. See `docs/OWNER_DECISIONS.md` for rationale.

### Priority order

1. Safe pricing operations
2. Scheduling (first-class deferred and windowed execution)
3. Scoped permissions (Brand / Category / Channel scope assignments)
4. Multi-channel foundation (WooCommerce + Digikala + SnapShop)
5. Lightweight synchronization (delta detection, not full sheet scans)
6. AI Pricing (future — not scheduled)

### Change Set Scheduling Stream (S1–S4)

This stream covers **Change Set execution scheduling** — the ability for a seller to
choose when a Change Set executes (now, deferred, or low-traffic window).

This is distinct from multi-channel automation sync schedules (see 8.0 below).

| Item | Description | Status |
|---|---|---|
| S1 | Scheduling architecture (modes: Now / Deferred / Low-traffic window) | Blocked on A2 |
| S2 | Scheduler backend (queue executor, heartbeat, abandonment detection) | Blocked on S1 |
| S3 | Schedule UI (mode selector, time picker, low-traffic recommendation) | Blocked on S2 |
| S4 | Scheduled Change Set history and cancellation | Blocked on S2 |

No S1–S4 implementation begins before A2 architecture is approved.

### Change Set Platform

Architecture design: A1 complete.
Next: A2 architecture (scoped permissions + channel adapter layer + scheduling contracts).
Implementation: after A2 approved.

### Scoped Permissions

Users will be assigned scope (Brand, Category, or Channel) by admin.
Change Sets may only contain products within the user's assigned scope.
This is a new permission dimension, not a replacement for existing flags.

### Multi-Channel

Target: 3–5 channels (WooCommerce, Digikala, SnapShop).
Channel adapter interface to be designed in A2.
No implementation until interface is approved.

### Spreadsheet Evolution

Spreadsheet moves from workflow driver to change event source.
Delta detection: detect changed rows vs. products_cache; propose Change Set.
Full sheet scanning is an anti-pattern to eliminate.

---

## Open Findings

### Medium (from WS-C audit — tracked, non-blocking)

- WS-C M1: CANCEL_ERROR stores error in writebackMsg (field collision)
- WS-C M2: Apply button enabled after applyPhase=error but startApply no-ops
- WS-C M3: Header checkbox has no indeterminate state

### Low (from WS-C audit)

- WS-C L1: applyRunning constant dead code
- WS-C L2: inline edit icon buttons missing group class
- WS-C L3: rollbackAdvisory banner has no dismiss button
- WS-C L4: applyItems array accumulates without cap

---

## Stable Checkpoints

- `react-wsd-stable`
- `75c4be2`
- `6fdd894`
- `6bb8342`
- `4ef73a8`
- `5a2eeff` (Phase 5 documentation stabilization)
- `377acae` (Phase 5 Codex remediation — all findings resolved)
- `5ead5b1` (7.5A R2: /home route guard, component tests, PLATFORM_MAP accuracy)
