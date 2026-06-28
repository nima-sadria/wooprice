# WooPrice Beta — Server Installation Guide

**Target host path:** `/opt/wooprice-beta`
**App port:** `8085`
**Profile:** `BETA`
**Reverse proxy:** Nginx Proxy Manager (external — not managed by this stack)

---

## Prerequisites

- Linux server (Ubuntu 22.04 LTS recommended)
- Docker Engine 24+ and Docker Compose plugin (`docker compose`)
- Git access to the WooPrice repository
- Nginx Proxy Manager already running on the host (handles TLS and domain routing)
- Inbound TCP port 8085 accessible from NPM host (or same host)

---

## 1. Clone the repository

```bash
sudo mkdir -p /opt/wooprice-beta
sudo chown $USER:$USER /opt/wooprice-beta
git clone <repo-url> /opt/wooprice-beta
cd /opt/wooprice-beta
```

---

## 2. Create the environment file

```bash
cp .env.beta.example .env.beta
nano .env.beta   # or vi, your choice
```

Fill in all required fields. Never leave a `CHANGE_ME_` placeholder.

**Generate secrets:**

```bash
# For BETA_JWT_SECRET (96 hex chars → 64+ char requirement met)
python3 -c "import secrets; print(secrets.token_hex(48))"

# For BETA_REST_API_SECRET (64 hex chars → 32+ char requirement met)
python3 -c "import secrets; print(secrets.token_hex(32))"

# For BETA_POSTGRES_PASSWORD (32 hex chars)
python3 -c "import secrets; print(secrets.token_hex(16))"
```

**Key fields to configure:**

| Field | Example |
|---|---|
| `BETA_DOMAIN` | `beta.yourdomain.com` |
| `BETA_POSTGRES_PASSWORD` | (generated above) |
| `BETA_JWT_SECRET` | (generated above, ≥64 chars) |
| `BETA_REST_API_SECRET` | (generated above, ≥32 chars) |
| `BETA_NEXTCLOUD_URL` | `https://cloud.yourdomain.com` |
| `BETA_NEXTCLOUD_USERNAME` | your Nextcloud username |
| `BETA_NEXTCLOUD_PASSWORD` | your Nextcloud password |
| `BETA_WOOCOMMERCE_URL` | `https://shop.yourdomain.com` |
| `BETA_WOOCOMMERCE_KEY` | `ck_...` |
| `BETA_WOOCOMMERCE_SECRET` | `cs_...` |
| `BETA_ADMIN_EMAIL` | `admin@yourdomain.com` |

> `BETA_DATABASE_URL` must reference the `postgres` service hostname exactly:
> `postgresql://wooprice_beta:<PASSWORD>@postgres:5432/wooprice_beta`

---

## 3. Create host directories

```bash
cd /opt/wooprice-beta
mkdir -p storage backups logs
```

These directories are bind-mounted into the container at `/data/storage`, `/data/backups`, and `/data/logs`.

---

## 4. Validate the compose configuration

```bash
docker compose -f docker-compose.beta.yml config
```

This must succeed with no errors before proceeding. Warnings about version are acceptable.

---

## 5. Build and start

```bash
docker compose -f docker-compose.beta.yml up -d --build
```

Expected output:
```
[+] Building ...  ✓
[+] Running 2/2
 ✔ Container wooprice-beta-postgres-1  Healthy
 ✔ Container wooprice-beta-app-1       Started
```

---

## 6. Run database migrations

```bash
docker compose -f docker-compose.beta.yml exec app \
    alembic -c alembic_beta.ini upgrade head
```

Expected output when no Beta migrations exist yet:
```
INFO  [alembic.runtime.migration] Context impl PostgreSQLImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
```
(No migration files = no-op, which is correct for the initial deployment.)

---

## 7. Verify the deployment

### Container status
```bash
docker compose -f docker-compose.beta.yml ps
```
Both `app` and `postgres` must show `Up` and `healthy`.

### Health endpoint
```bash
curl -s http://localhost:8085/api/health | python3 -m json.tool
```
Expected response:
```json
{
    "status": "ok",
    "env": "beta",
    "version": "0.1.0-dev"
}
```

### CLI diagnostics (if wooprice CLI is available on the host)
```bash
wooprice diagnostics --env-file /opt/wooprice-beta/.env.beta
wooprice diagnostics run --env-file /opt/wooprice-beta/.env.beta
```

---

## 8. Configure Nginx Proxy Manager

In NPM, create a Proxy Host:
- **Domain Names:** `beta.yourdomain.com`
- **Scheme:** `http`
- **Forward Hostname / IP:** `localhost` (or Docker host IP)
- **Forward Port:** `8085`
- **Enable:** WebSocket Support ✓
- **SSL:** Request / attach your certificate

No Nginx container is included in this stack — NPM handles all TLS termination.

---

## Operational commands

```bash
# View logs
docker compose -f docker-compose.beta.yml logs -f app

# Restart app only (after config change)
docker compose -f docker-compose.beta.yml restart app

# Stop everything
docker compose -f docker-compose.beta.yml down

# Stop and remove volumes (DESTRUCTIVE — destroys database)
docker compose -f docker-compose.beta.yml down -v

# Pull latest code and rebuild
git pull
docker compose -f docker-compose.beta.yml up -d --build
```

---

## Secrets management

- `.env.beta` is gitignored — never commit it
- `.env.beta.example` is the committed template with placeholder values
- All secrets are set in `.env.beta` only; never passed as CLI arguments
- `wooprice configure get <FIELD>` shows the current value with secrets redacted
- `wooprice configure set <FIELD> <VALUE>` edits editable fields (rejects secrets)

---

## Phase status

| Component | Status |
|---|---|
| Health endpoint (`/api/health`) | Active |
| CLI diagnostics | Active |
| CLI configure get/set | Active |
| REST API v2 | Stubs only (active in B5+) |
| Authentication | B7 |
| UI | B5+ |
| Docker Runtime management | B6 |
| Database migrations (Beta schema) | B4 |
