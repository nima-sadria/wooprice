# BU2 — Authentication & Session Architecture

**Phase:** BU2 — Authentication & Session Foundation  
**Status:** Implementation complete, pending Owner phase exit approval  
**Date:** 2026-06-28  

---

## Overview

BU2 introduces a complete, isolated authentication system for WooPrice Beta.  
All components live under `app/beta/auth/` and are entirely separate from the production authentication system (`app/services/auth.py`).

---

## Architecture

### Token Strategy

| Token type | Format | Lifetime | Storage |
|---|---|---|---|
| Access token | Signed JWT (HS256) | 15 minutes | Client `localStorage` (`wp_token`) |
| Refresh token | Opaque `secrets.token_urlsafe(64)` | 30 days | Hash (SHA-256) in `beta_refresh_tokens` DB table |

**Why opaque refresh tokens instead of JWT refresh tokens:**  
Opaque tokens enable instant server-side revocation (single-row update), expose no information if a stored hash is compromised, and require no token blacklist — the hash is the canonical identity.

**Rotation:** Every `/api/auth/refresh` call revokes the old refresh token and issues a new one. This means a stolen refresh token can only be used once before the legitimate client's next use revokes it.

---

### Module Layout

```
app/beta/auth/
  __init__.py           — package marker
  models.py             — SQLAlchemy ORM: BetaUser, BetaRefreshToken, BetaLoginAudit
  password.py           — Argon2id hashing (argon2-cffi)
  jwt_service.py        — JWT access token creation and validation
  refresh_token.py      — Opaque refresh token generation and SHA-256 hashing
  rate_limiter.py       — In-memory sliding-window rate limiter (5/60s per IP)
  repository.py         — Database access layer (no direct SQL; all via SQLAlchemy ORM)
  dependencies.py       — FastAPI get_current_user dependency
  router.py             — POST /login, /logout, /refresh; GET /me
```

---

### Database Schema

Three Beta-only tables created by `alembic_beta` migrations:

**`beta_users`** (beta_001)
- `id`, `username` (unique), `hashed_password` (Argon2id hash), `role`, `is_active`, `created_at`

**`beta_refresh_tokens`** (beta_002)
- `id`, `user_id` (FK → beta_users.id CASCADE), `token_hash` (SHA-256 hex, 64 chars, unique), `expires_at`, `revoked_at`

**`beta_login_audit`** (beta_003)
- `id`, `username`, `event`, `ip_address`, `created_at`
- Events: `login_success`, `login_failed`, `login_rate_limited`, `logout`, `token_refresh`

**Migration chain:** `beta_001 → beta_002 → beta_003`  
**Target metadata:** `BetaBase` (separate from production `Base`)

---

### Password Hashing

Argon2id via `argon2-cffi`:

```
time_cost=2, memory_cost=65536 (64 MiB), parallelism=2, hash_len=32, salt_len=16
```

---

### Rate Limiting

In-memory sliding-window per IP: **5 attempts / 60 seconds**.  
State is per-process and resets on restart (acceptable for Beta; Redis not required).  
Thread-safe via `threading.Lock`.

---

### API Endpoints

| Method | Path | Auth required | Description |
|---|---|---|---|
| `POST` | `/api/auth/login` | No | Verify credentials, issue access + refresh token pair |
| `POST` | `/api/auth/logout` | Yes (Bearer) | Revoke refresh token, write audit event |
| `POST` | `/api/auth/refresh` | No | Rotate refresh token, issue new access + refresh pair |
| `GET` | `/api/auth/me` | Yes (Bearer) | Return user profile with role and permissions |

---

### Role Permissions

| Permission | admin | viewer |
|---|---|---|
| `can_access_site` | ✓ | ✓ |
| `can_fetch` | ✓ | — |
| `can_view_logs` | ✓ | ✓ |
| `can_view_settings` | ✓ | — |

---

### Admin User Creation

The `wooprice create-admin` CLI subcommand creates the initial admin user.  
This is a required post-install step — the login endpoint returns 401 until at least one admin exists.

```
wooprice create-admin [--username admin] [--env-file /opt/wooprice-beta/.env.beta]
```

Prompts for username (default: `admin`) and password (with confirmation). Fails safely if username already exists.

---

### Frontend Session Management

**Login:** Stores `wp_token` (access) and `wp_refresh_token` (opaque) in `localStorage`.

**Silent refresh on 401:**  
`authFetch()` intercepts 401 responses, calls `attemptTokenRefresh()` (standalone function, not `authFetch` — no recursion), retries the original request with the new token. If refresh also fails, calls `clearAuth()` and redirects to `/login`.

**`refreshUser()` on mount:** If no access token, tries refresh before showing login screen. This silently restores sessions after an access token expiry.

**Tab sync:** `StorageEvent` listener on `wp_token`, `wp_refresh_token`, and `wp_user` keeps multi-tab state consistent.

---

### SPA Routing

`app/beta/app.py` serves two HTML responses:

- `GET /` — Always returns `_LANDING_HTML` (version/environment info, health link)
- `GET /{full_path:path}` — Returns `frontend/dist/index.html` if built; otherwise `_LANDING_HTML`

API routers are registered before the catch-all so `/api/*` routes always take priority.

---

### Isolation Guarantees

- `app/services/auth.py` — not imported anywhere in `app/beta/`
- Production Alembic migrations — not modified
- Production `Base` metadata — not modified
- BU1 installer (`installer/install.sh`) — not modified
- A2 phase modules — not modified

---

### Test Coverage

| Module | Tests | File |
|---|---|---|
| `password.py` | 9 | `tests/beta/auth/test_password.py` |
| `jwt_service.py` | 7 | `tests/beta/auth/test_jwt_service.py` |
| `rate_limiter.py` | 5 | `tests/beta/auth/test_rate_limiter.py` |
| `router.py` | 22 | `tests/beta/auth/test_router.py` |
| `create_admin.py` | 4 | `tests/beta/cli/test_create_admin.py` |
| **Total** | **47** | |

All 47 BU2-specific tests pass. Full Beta suite: **1282 passed, 0 failed**.

---

### Security Properties

- Passwords never stored in plaintext; never echoed in responses or logs
- Raw refresh tokens never persisted; only SHA-256 hash stored
- JWT secret read from `BETA_JWT_SECRET` environment variable at call time
- `WWW-Authenticate: Bearer` header on all 401 responses
- Refresh token rotation on every use
- Audit event written for every login attempt, logout, and token refresh
