# WooPrice

A high-performance WooCommerce product and price management platform designed for stores with large catalogs, variable products, and spreadsheet-based workflows.

WooPrice provides fast product browsing, bulk price updates, intelligent caching, and WooCommerce synchronization while minimizing API load on production stores.

---

## Overview

Managing thousands of WooCommerce products directly through the WordPress admin panel becomes increasingly inefficient as catalogs grow.

WooPrice addresses this problem by introducing a local product cache layer and spreadsheet-driven workflow that allows users to:

* Load products instantly
* Update prices in bulk
* Manage variations efficiently
* Reduce WooCommerce API traffic
* Work with familiar spreadsheet interfaces
* Synchronize only changed products

The application treats WooCommerce as the source of truth while using a local cache for speed and scalability.

---

## Key Features

### Product Management

* WooCommerce REST API integration
* Simple product support
* Variable product support
* Product variation support
* Parent/variation relationship mapping
* Product status synchronization
* Stock status synchronization

### Spreadsheet Workflow

* Spreadsheet-driven product management
* Product ID mapping
* Variation ID mapping
* Custom naming support
* Bulk price editing
* Bulk stock updates

### Smart Product Cache

* Local persistent product cache
* Instant product loading
* Background synchronization
* Incremental updates
* Cache rebuild functionality
* Reduced WooCommerce load

### Performance Optimization

* Pagination support
* Change-only synchronization
* Persistent cache storage
* Background refresh
* Cache-aware API design
* Concurrent sync protection

### User Interface

* Fast product tables
* Large catalog support
* Persian language support
* IRANYekanX Variable Font support
* Monospaced Persian number rendering
* Spreadsheet-like workflow

---

## Architecture

```text
 Spreadsheet / Excel / OnlyOffice
        │
        ▼
   Frontend UI
        │
        ▼
 WooPrice Backend
        │
        ┌────────────────┼────────────────┐
        │                │                │
        ▼                ▼                ▼
 Product Cache      Sync Engine      Update Engine
(PostgreSQL)             │            (Prices/Stock)
                         │
                         ▼
                    WooCommerce
                    (REST API)
```

---

## Product Name Strategy

WooPrice intentionally separates display names from WooCommerce names.

### Display Name Source

Column A is always considered the authoritative source.

```text
Spreadsheet Column A
        ↓
Displayed Product Name
```

### Rules

* Product names are always loaded from Column A.
* WooCommerce names never overwrite spreadsheet names.
* Product matching uses Product ID and Variation ID.
* WooCommerce names may be stored only for debugging or reference purposes.

This allows users to maintain:

* Localized product names
* Supplier-specific names
* Internal naming standards
* Custom catalog structures

without affecting WooCommerce synchronization.

---

## Smart Cache System

### First Fetch

```text
User clicks Fetch
        ↓
Load all products from WooCommerce
        ↓
Store locally
        ↓
Build variation mappings
        ↓
Return products to UI
```

### Normal Operation

```text
User opens product page
        ↓
Read products from cache
        ↓
Display instantly
        ↓
Background sync starts
        ↓
Only changed products updated
```

---

## Synchronization Strategy

### Full Synchronization

Used for:

* Initial installation
* Cache rebuild
* Recovery operations

Example:

```http
GET /wp-json/wc/v3/products
GET /wp-json/wc/v3/products/{parent_id}/variations
```

### Incremental Synchronization

Used during normal operation.

Example:

```http
GET /wp-json/wc/v3/products?modified_after={timestamp}
```

Only modified products are refreshed.

---

## Technology Stack

**Backend**

* Python
* FastAPI

**Database**

* PostgreSQL (recommended)
* SQLite (small deployments)

**Caching / Jobs**

* Redis (optional)

**Frontend**

* HTML
* CSS
* JavaScript

**Integration**

* WooCommerce REST API
* Excel
* OnlyOffice

**Deployment**

* Docker
* Docker Compose

---

## Docker Deployment

Start:

```bash
docker compose up -d
```

Stop:

```bash
docker compose down
```

Rebuild:

```bash
docker compose up -d --build
```

View logs:

```bash
docker compose logs -f
```

---

## Configuration

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

### Required variables

| Variable | Description |
|----------|-------------|
| `NEXTCLOUD_URL` | Nextcloud server URL |
| `NEXTCLOUD_USER` | Nextcloud username for WebDAV |
| `NEXTCLOUD_PASSWORD` | Nextcloud password |
| `NEXTCLOUD_FILE_PATH` | WebDAV path to the Excel price list |
| `WC_URL` | WooCommerce store URL |
| `WC_KEY` | WooCommerce consumer key |
| `WC_SECRET` | WooCommerce consumer secret |
| `JWT_SECRET` | Random secret ≥ 32 bytes — generate with `python -c "import secrets; print(secrets.token_hex(48))"` |

### Access control variables (Phase 0)

| Variable | Description |
|----------|-------------|
| `SUPER_ADMIN_USERS` | Comma-separated Nextcloud usernames that are always super-admin. Bypass the `app_users` DB table entirely. Can log in even if `app_users` is empty. |
| `BOOTSTRAP_APP_ADMINS` | Comma-separated usernames seeded as admins in `app_users` on first startup. Idempotent — never overwrites existing rows. |
| `BOOTSTRAP_APP_USERS` | Comma-separated usernames seeded as operators (non-admin) in `app_users` on first startup. |

**Minimum production access control configuration:**

```env
SUPER_ADMIN_USERS=woo,admin
BOOTSTRAP_APP_ADMINS=woo,admin
BOOTSTRAP_APP_USERS=az1328,farshadkh,soheil
```

### How access control works

```
Login attempt
    │
    ├─ Is username in SUPER_ADMIN_USERS?
    │      └─ YES → Nextcloud verify → issue admin token (pv=0)
    │                 (app_users table is never consulted)
    │
    └─ NO → Nextcloud verify → look up app_users
               ├─ Not found or is_active=false → HTTP 403 denied
               └─ Found and active → issue token with permission_version
                   └─ Every subsequent request checks pv == app_user.permission_version
                       └─ Mismatch → HTTP 401 token revoked
```

---

## Project Structure

```text
wooprice/
│
├── app/
├── static/
│   └── fonts/
│       ├── IRANYekanXVF.woff
│       ├── IRANYekanX-Regular.woff
│       └── IRANYekanX-Bold.woff
│
├── templates/
├── docker-compose.yml
├── requirements.txt
└── README.md
```

---

## Performance Goals

WooPrice is designed to support large WooCommerce stores.

Goals:

* Instant product loading
* Minimal API traffic
* Reduced server load
* Efficient variation management
* Fast bulk updates
* Scalable architecture

---

## Roadmap

### Planned

* Scheduled synchronization
* WooCommerce webhooks
* Product analytics
* Search indexing
* Multi-store support
* Advanced reporting
* Audit logs
* Role-based access control
* Change history
* Inventory synchronization

### Future

* Marketplace integrations
* Multi-warehouse support
* AI-assisted product management
* Advanced pricing rules
* Import/export automation

---

## License

Private project.

Copyright © Nima Sadria.

All rights reserved.
