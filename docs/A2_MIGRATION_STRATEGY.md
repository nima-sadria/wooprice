# WooPrice A2 Migration Strategy

Reference: `docs/A2_ARCHITECTURE.md` Section 15–16.
Implementation stream: A2.1 (Phase 1 — Canonical Product Model and PostgreSQL Foundation).

---

## Current State (before A2.1)

| Dimension | State |
|---|---|
| Database | SQLite via SQLAlchemy; single `wooprice.db` file |
| Product identity | `products_cache` table — WooCommerce IDs are the primary key |
| Channel representation | Monolithic rows; no channel abstraction |
| Migrations | Alembic (`alembic/`) targeting SQLite; `render_as_batch=True` |
| Credentials | WC_KEY / WC_SECRET in environment variables; not stored in DB |
| PostgreSQL | Not present |

The existing SQLite stack (`app/database.py`, `app/models.py`, `alembic/`) is the production
system and must not be touched by A2 work.

---

## Intermediate State (A2.1 — this phase)

A2.1 adds PostgreSQL as a **parallel, additive** system. No existing code is modified.

| Dimension | State |
|---|---|
| SQLite stack | Unchanged — all existing workflows continue running |
| PostgreSQL | New `postgres` service in `docker-compose.yml`; `wooprice_a2` database |
| A2 package | `app/a2/` — completely separate from `app/` |
| A2 migrations | Separate Alembic config (`alembic_a2.ini`, `a2_migrations/`) |
| New tables | `canonical_products`, `channel_listings`, `channel_credentials` |
| Product identity | `canonical_products.sku` is the stable, cross-channel identity key |
| WC IDs | Will live in `channel_listings.external_id` (not yet populated in A2.1) |
| Credentials | `channel_credentials.encrypted_payload` column exists; encryption deferred to Phase 2 |

### A2.1 additive inventory

```
app/a2/__init__.py
app/a2/database.py           — A2Base, create_a2_engine(), get_postgres_url()
app/a2/models.py             — CanonicalProduct, ChannelListing, ChannelCredential
app/a2/repositories/         — CanonicalProductRepository, ChannelListingRepository
app/a2/services/             — CanonicalProductService (minimal scaffolding)
alembic_a2.ini               — Alembic config pointing to a2_migrations/
a2_migrations/               — env.py, script.py.mako, versions/0001_initial_a2_foundation.py
tests/a2/                    — conftest, test_database, test_repositories, test_isolation
```

### Running A2 migrations

```bash
# Requires POSTGRES_URL to be set
POSTGRES_URL=postgresql://wooprice:password@localhost:5432/wooprice_a2 \
  alembic -c alembic_a2.ini upgrade head

# Roll back
POSTGRES_URL=... alembic -c alembic_a2.ini downgrade base
```

### Running A2 tests

```bash
# Skip if PostgreSQL not available (default in CI without PG)
pytest tests/a2/

# With PostgreSQL
POSTGRES_TEST_URL=postgresql://wooprice:wooprice@localhost:5432/wooprice_a2_test \
  pytest tests/a2/
```

---

## Final Target State (post-A2 full implementation)

After all 9 phases are complete and the owner authorises cutover:

| Dimension | State |
|---|---|
| Database | PostgreSQL is the single database; SQLite retired |
| Product identity | `canonical_products` table with UUID primary key |
| Channel representation | `channel_listings` per channel per product |
| WC IDs | `channel_listings.external_id` for channel_type='woocommerce' |
| Existing workflows | Re-expressed as Change Set producers using A2 models |
| Migrations | `a2_migrations/` only; existing `alembic/` archived |

---

## Critical Cutover Rule

**No cutover until ALL of the following are satisfied:**

1. Zero-mismatch reconciliation: every row in `products_cache` has a corresponding
   `canonical_products` + `channel_listings` entry, with matching price and stock values.
2. Full parity test suite passes: all existing Workspace flows (preview, dry run, apply,
   cancel, rollback) produce identical results against both the SQLite and PostgreSQL stacks.
3. Explicit owner approval in a dedicated session.

This rule is defined in `docs/A2_ARCHITECTURE.md` Section 16 and enforced by
`docs/PROJECT_OPERATING_MODEL.md` Section 7 (Phase Exit Criteria).

Violating this rule is a BLOCKER finding for any Codex audit.

---

## Schema Reference

### canonical_products

| Column | Type | Constraints |
|---|---|---|
| id | UUID | PK, default gen_random_uuid() |
| sku | VARCHAR(255) | UNIQUE NOT NULL |
| name | VARCHAR(1000) | NOT NULL |
| status | VARCHAR(50) | NOT NULL, CHECK IN ('active','inactive','draft'), default 'active' |
| created_at | TIMESTAMPTZ | NOT NULL, default NOW() |
| updated_at | TIMESTAMPTZ | NOT NULL, default NOW() |

### channel_listings

| Column | Type | Constraints |
|---|---|---|
| id | UUID | PK, default gen_random_uuid() |
| product_id | UUID | FK → canonical_products.id ON DELETE RESTRICT |
| channel_type | VARCHAR(100) | NOT NULL |
| external_id | VARCHAR(255) | NOT NULL |
| status | VARCHAR(50) | NOT NULL, CHECK IN ('active','inactive','pending'), default 'pending' |
| created_at | TIMESTAMPTZ | NOT NULL |
| updated_at | TIMESTAMPTZ | NOT NULL |

UNIQUE (channel_type, external_id)

### channel_credentials

| Column | Type | Constraints |
|---|---|---|
| id | UUID | PK, default gen_random_uuid() |
| channel_type | VARCHAR(100) | NOT NULL |
| credential_type | VARCHAR(100) | NOT NULL |
| encrypted_payload | BYTEA | nullable — AES-256-GCM (nonce\|\|ciphertext\|\|tag), deferred to Phase 2 |
| created_at | TIMESTAMPTZ | NOT NULL |
| updated_at | TIMESTAMPTZ | NOT NULL |

---

## Reconciliation Formula (for future cutover gate)

```
mismatch_count = |products_cache| - |canonical_products JOIN channel_listings
                  WHERE channel_type = 'woocommerce'
                  AND price_matches AND stock_matches|

cutover_allowed = (mismatch_count == 0) AND parity_tests_pass AND owner_approved
```

Source: `docs/A2_ARCHITECTURE.md` Section 16.
