# WooPrice

A high-performance WooCommerce product and price management platform designed for stores with large catalogs, variable products, and spreadsheet-based workflows.

WooPrice provides fast product browsing, bulk price updates, intelligent caching, and WooCommerce synchronization while minimizing API load on production stores.

---

## Project Overview

Managing thousands of WooCommerce products directly through the WordPress admin panel becomes increasingly inefficient as catalogs grow.

WooPrice addresses this by introducing a local product cache layer and a spreadsheet-driven workflow that allows users to:

- Load products instantly from a local cache
- Update prices and stock in bulk from an Excel / Nextcloud spreadsheet
- Preview all changes before applying them (Dry Run)
- Apply only the changes that passed validation
- Roll back individual products to their last known good state
- Write confirmed updates back to the source spreadsheet
- Synchronize only changed products, reducing WooCommerce API load
- Stream all long-running operations in real time via SSE

### Key Capabilities

| Capability | Description |
|---|---|
| WooCommerce synchronization | Full, light, and deep-variation cache refresh via REST API |
| Spreadsheet integration | Excel/XLSX price list on Nextcloud via WebDAV |
| Dry Run | Validates scope before apply; blocks on critical errors |
| Apply | SSE-streamed write of validated changes to WooCommerce |
| Rollback | Per-product admin rollback to pre-sync price/stock |
| Writeback | Confirms applied prices back to the source spreadsheet |
| Product cache | Local SQLite cache for instant loading and diff calculation |
| SSE-based operations | All cache refresh, preview, and apply operations stream progress in real time |

---

## Architecture

```text
 Nextcloud / OnlyOffice (Excel price list)
        │  WebDAV
        ▼
   React Frontend (Vite + TypeScript + Tailwind)
        │  HTTP / SSE  (proxied in dev; served from /static in production)
        ▼
   FastAPI Backend  (port 8000, Docker)
        │
        ┌──────────────┬──────────────┬──────────────┐
        ▼              ▼              ▼              ▼
  Product Cache   Sync Engine   Update Engine   Auth / JWT
  (SQLite)             │         (Prices/Stock)
                       ▼
                  WooCommerce
                  (REST API)
```

### Frontend

| Layer | Technology |
|---|---|
| Framework | React 18 |
| Build | Vite 5 |
| Language | TypeScript |
| Styling | Tailwind CSS v3 |
| State | `useReducer` state machines per page |
| Real-time | `EventSource` (SSE) via `useSSEStream` hook |
| Auth | JWT stored in `localStorage`; `AuthProvider` + `useAuth` |
| Direction | `DirectionProvider` applies `document.documentElement.dir` globally |

### Backend

| Layer | Technology |
|---|---|
| Framework | FastAPI (Python) |
| Database | SQLite via SQLAlchemy (Docker volume `/app/data`) |
| Auth | JWT (HS256), Nextcloud credential verification |
| SSE | FastAPI `StreamingResponse` with `text/event-stream` |
| Deployment | Docker on port 8000 |

> **Migration note:** The frontend is currently mid-migration from a legacy static HTML/JS UI to a React SPA. Both coexist; `static/index.html` serves the legacy UI. The React build output is not yet deployed to production. See [docs/MIGRATION_STATUS.md](docs/MIGRATION_STATUS.md).

---

## Current Migration Status

### Completed

| Phase | Description |
|---|---|
| Phase 1–3 | Core backend, auth, product cache, sync engine |
| Analytics | Product analytics page (React) |
| Auth | JWT login flow, `AuthProvider`, `RequirePermission` |
| Direction Layer | Global LTR/RTL via `DirectionProvider`; all Tailwind utilities logical |
| Logs | Audit log + sync history page (React) |
| WS-A | Workspace shell: layout, header buttons, cache refresh panel, spreadsheet status |
| WS-B | Preview stream: SSE progress steps, filters, category hierarchy, product table |
| WS-C | Dry Run / Apply / Writeback / Cancel / Inline edits / Rollback |
| WS-D Audit | Integration audit; H-D1 and MD-2 defects found and resolved |

### Pending

| Phase | Description |
|---|---|
| Phase 5 | Production Cutover Preparation |
| Phase 6 | Legacy Frontend Replacement |

Full status and open findings: [docs/MIGRATION_STATUS.md](docs/MIGRATION_STATUS.md)

---

## Safety Principles

- **Backend stability first** — backend APIs are never changed without a verified defect requiring it
- **Audit before approval** — every phase requires a formal audit with BLOCKERS / HIGH / MEDIUM / LOW report
- **No direct production cutover** — the React build is not served to production until Phase 5 is formally approved
- **Dry Run before Apply** — the Apply operation is blocked unless a passing Dry Run exists for the exact same scope
- **Rollback safety** — per-product rollback is admin-only and always invalidates the local dry run state
- **SSE safety** — terminal server events (stale_preview, freshness_unverifiable, dry_run_invalidated) win over subsequent EventSource onerror callbacks; Apply SSE never auto-retries

Full workflow rules: [docs/WORKFLOW.md](docs/WORKFLOW.md)

---

## Development Commands

### Frontend

```bash
cd frontend

# Install dependencies
npm install

# Start dev server (port 5173, proxies /api to localhost:8000)
npm run dev

# Production build (output: frontend/dist/)
npm run build
```

### Backend

```bash
# Run all tests
pytest

# Start backend (development)
uvicorn app.main:app --reload --port 8000
```

### Docker (production)

```bash
# Start
docker compose up -d

# Stop
docker compose down

# Rebuild
docker compose up -d --build

# Logs
docker compose logs -f
```

---

## Repository Structure

```text
wooprice/
│
├── app/                        # FastAPI backend
│   ├── main.py                 # All routes and SSE endpoints
│   ├── models.py               # SQLAlchemy models
│   ├── database.py             # DB session setup
│   ├── config.py               # Environment variable loading
│   ├── validation.py           # Price / stock validation logic
│   └── services/
│       ├── auth.py             # JWT + Nextcloud auth
│       ├── nextcloud.py        # WebDAV / spreadsheet fetch
│       ├── product_cache.py    # Local product cache management
│       └── woocommerce.py      # WooCommerce REST API client
│
├── frontend/                   # React SPA (migration in progress)
│   ├── src/
│   │   ├── App.tsx             # Router + providers
│   │   ├── auth.tsx            # AuthProvider, useAuth, RequirePermission
│   │   ├── direction.tsx       # DirectionProvider (LTR/RTL)
│   │   ├── components/
│   │   │   ├── AppShell.tsx    # Layout: sidebar + topbar + outlet
│   │   │   ├── Sidebar.tsx     # Responsive navigation sidebar
│   │   │   └── Topbar.tsx      # Top bar with user avatar
│   │   ├── hooks/
│   │   │   └── useSSEStream.ts # EventSource wrapper with generation guard
│   │   └── pages/
│   │       ├── Workspace.tsx   # Main sync workspace (WS-A/B/C)
│   │       ├── Analytics.tsx   # Product analytics
│   │       ├── Logs.tsx        # Audit log + sync history
│   │       ├── Home.tsx        # Dashboard / home
│   │       ├── Settings.tsx    # User settings
│   │       └── Admin.tsx       # Admin panel
│   ├── dist/                   # Production build output (not committed)
│   └── package.json
│
├── static/                     # Legacy frontend (served by FastAPI)
│   └── index.html              # Legacy UI entry point (active in production)
│
├── tests/                      # Backend pytest tests (47 tests)
├── alembic/                    # DB migrations
├── docker-compose.yml
├── requirements.txt
├── docs/
│   ├── WORKFLOW.md             # Development and audit workflow
│   ├── ARCHITECTURE.md         # Technical architecture reference
│   └── MIGRATION_STATUS.md     # Current migration state and open findings
└── README.md
```

---

## Configuration

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

### Required Variables

| Variable | Description |
|---|---|
| `NEXTCLOUD_URL` | Nextcloud server URL |
| `NEXTCLOUD_USER` | Nextcloud username for WebDAV |
| `NEXTCLOUD_PASSWORD` | Nextcloud password |
| `NEXTCLOUD_FILE_PATH` | WebDAV path to the Excel price list |
| `WC_URL` | WooCommerce store URL |
| `WC_KEY` | WooCommerce consumer key |
| `WC_SECRET` | WooCommerce consumer secret |
| `JWT_SECRET` | Random secret ≥ 32 bytes — generate with `python -c "import secrets; print(secrets.token_hex(48))"` |

### Access Control Variables

| Variable | Description |
|---|---|
| `SUPER_ADMIN_USERS` | Comma-separated Nextcloud usernames that are always super-admin |
| `BOOTSTRAP_APP_ADMINS` | Comma-separated `username` or `username:email` entries seeded as admins on first startup |
| `BOOTSTRAP_APP_USERS` | Comma-separated entries seeded as operators on first startup |

### How Access Control Works

```text
Login input (username or email)
    │
    ├─ Contains '@'? → look up app_users.email (case-insensitive)
    │      ├─ Not found → HTTP 403 denied
    │      └─ Found → resolve to canonical username
    │
    ▼
canonical_username
    │
    ├─ Verify Nextcloud credentials
    │      └─ Invalid → HTTP 401 denied
    │
    ├─ In SUPER_ADMIN_USERS?
    │      └─ YES → issue admin token (app_users never consulted)
    │
    └─ NO → look up app_users
               ├─ Not found or inactive → HTTP 403 denied
               └─ Found and active → issue JWT
                   └─ Every request checks pv == app_user.permission_version
                       └─ Mismatch → HTTP 401 token revoked
```

JWT `sub` is always the canonical Nextcloud username, never an email.

---

## Product Name Strategy

WooPrice separates display names from WooCommerce names. Column A of the spreadsheet is always the authoritative display name source. WooCommerce names never overwrite spreadsheet names. Product matching uses Product ID and Variation ID only.

---

## Known Limitations

See [docs/MIGRATION_STATUS.md](docs/MIGRATION_STATUS.md) for the current list of open LOW-severity findings from the WS-C and WS-D audits.

---

## License

Private project. Copyright © Nima Sadria. All rights reserved.
