# WooPrice Beta — Deployment Architecture

**Document:** DEPLOYMENT_ARCHITECTURE.md
**Series:** B1 Architecture Blueprint

---

## Overview

WooPrice Beta deploys as a Docker Compose stack on a single Linux server. All services
run in Docker containers. No Kubernetes, no cloud-specific services, no serverless —
this keeps the Beta deployment operator-grade: simple to install, simple to operate,
simple to audit.

---

## Container Stack

```
┌─────────────────────────────────────────────────────┐
│  Host: Linux server (BETA_DOMAIN:BETA_PORT)          │
│                                                      │
│  ┌──────────────────────────────────────────────┐    │
│  │  nginx (reverse proxy + static frontend)     │    │
│  │  Port: 80 / 443 (host-bound)                 │    │
│  └──────────────┬──────────────────┬────────────┘    │
│                 │                  │                  │
│  ┌──────────────▼──┐  ┌────────────▼──────────────┐  │
│  │  app             │  │  worker                   │  │
│  │  FastAPI + Uvicorn  │  Background job runner     │  │
│  │  Port: 8000 (internal) │ Scheduler polling       │  │
│  └──────────────┬──┘  └────────────┬──────────────┘  │
│                 │                  │                  │
│  ┌──────────────▼──────────────────▼──────────────┐  │
│  │  postgres                                       │  │
│  │  PostgreSQL 15   (Port: 5432 — internal only)   │  │
│  │  Volume: beta_pgdata                            │  │
│  └────────────────────────────────────────────────┘  │
│                                                      │
│  ┌────────────────────────────────────────────────┐  │
│  │  redis                                         │  │
│  │  Redis 7   (Port: 6379 — internal only)        │  │
│  │  Volume: beta_redisdata                        │  │
│  └────────────────────────────────────────────────┘  │
│                                                      │
│  External mounts:                                    │
│    ${BETA_STORAGE_PATH}  →  /data/storage            │
│    ${BETA_BACKUP_PATH}   →  /data/backups            │
└─────────────────────────────────────────────────────┘
```

---

## Docker Compose Services

### `nginx`

- Image: `nginx:1.25-alpine`
- Responsibilities:
  - Serve the React SPA from `/usr/share/nginx/html`
  - Reverse proxy `/api/` to `app:8000`
  - Handle SSL termination (if `BETA_SSL_MODE != off`)
  - Apply security headers (CSP, X-Frame-Options, etc.)
  - Rate limiting (`limit_req` for `/api/auth/login`)
- Exposed ports: `80:80` and `443:443` (on host)
- Internal ports only for all other services

### `app`

- Image: `wooprice-beta:${VERSION}` (built from `Dockerfile.app`)
- Responsibilities:
  - FastAPI application server (Uvicorn, 4 workers)
  - Serves `/api/v1/`, `/api/v2/`, `/api/beta/`, `/api/health`
  - Loads plugins from `${BETA_STORAGE_PATH}/plugins/`
  - Runs database migrations on startup (configurable via `MIGRATE_ON_STARTUP`)
- Internal port: `8000`
- Mounts: `${BETA_STORAGE_PATH}:/data/storage`

### `worker`

- Image: `wooprice-beta:${VERSION}` (same image as `app`; different entrypoint)
- Entrypoint: `python -m app.beta.worker`
- Responsibilities:
  - Scheduler polling (calls A2.8 `list_due_schedules()` every `BETA_SCHEDULER_POLL_SECONDS`)
  - Background job processing (backup, report generation)
- Shares the same volume mounts as `app`
- Does NOT share any database session with `app` — uses its own connection pool

### `postgres`

- Image: `postgres:15-alpine`
- Volume: `beta_pgdata` (Docker named volume — persists across container restarts)
- Internal port only (`5432`)
- Health check: `pg_isready`
- Initialization: `app` runs Alembic migrations on first boot

### `redis`

- Image: `redis:7-alpine`
- Volume: `beta_redisdata` (Docker named volume)
- Internal port only (`6379`)
- Used for: session cache, rate limiting counters, scheduler coordination lock

---

## Network Configuration

All containers run in a single Docker bridge network (`beta_net`). Only Nginx has
host-bound ports. PostgreSQL and Redis are not accessible from outside the Docker
network.

```
beta_net (bridge, internal)
  nginx       ─ external: 80/443
  app         ─ internal: 8000
  worker      ─ no exposed ports
  postgres    ─ internal: 5432
  redis       ─ internal: 6379
```

---

## Volume Strategy

| Volume | Type | Contents | Backup included |
|---|---|---|---|
| `beta_pgdata` | Docker named volume | PostgreSQL data files | Yes (via pg_dump) |
| `beta_redisdata` | Docker named volume | Redis data (sessions, rate limits) | No (ephemeral acceptable) |
| `${BETA_STORAGE_PATH}` | Host bind mount | App files, logs, plugins, config | Yes |
| `${BETA_BACKUP_PATH}` | Host bind mount | Backup archives | Operator-managed |

Named volumes are managed by Docker and persist across `docker compose down`. They are
removed only by `docker compose down --volumes` (which must never be run without a
confirmed backup).

---

## Startup Order

Docker Compose `depends_on` with health checks enforces this startup order:

```
postgres (healthy)
  ↓
redis (healthy)
  ↓
app (runs migrations if MIGRATE_ON_STARTUP=true, then starts Uvicorn)
  ↓
worker (starts polling after app is healthy)
  ↓
nginx (starts reverse proxy after app is healthy)
```

`MIGRATE_ON_STARTUP` defaults to `true`. For production-style environments
(B16+ planning), migrations may be decoupled from startup.

---

## Dockerfile Strategy

### `Dockerfile.app`

```dockerfile
FROM python:3.12-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /install /usr/local
COPY app/ ./app/
COPY alembic_a2/ ./alembic_a2/
COPY alembic_beta/ ./alembic_beta/
COPY alembic_a2.ini alembic_beta.ini ./
COPY cli/ ./cli/
ENV PYTHONUNBUFFERED=1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

Multi-stage build keeps the final image small. No build tools in the final image.
No secrets in the image — all secrets come from the Docker environment (`.env`).

### `Dockerfile.frontend`

```dockerfile
FROM node:20-alpine AS builder
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM nginx:1.25-alpine
COPY --from=builder /build/dist /usr/share/nginx/html
COPY installer/templates/nginx.conf /etc/nginx/conf.d/default.conf
```

The frontend image is built separately during `install.sh` (or by CI in B4). The
built SPA is baked into the Nginx image — no Node runtime in the final image.

---

## Environment Variable Injection

All secrets are passed to containers via Docker Compose `env_file: .env`. The `.env`
file is on the host (mode 600), never inside any Docker image. Docker Compose reads
it and injects the variables into the container environment at startup.

No secrets appear in `docker-compose.beta.yml` — only `${VARIABLE_NAME}` placeholders.

---

## Health Probes

Each container declares a Docker health check:

| Service | Health check command | Interval |
|---|---|---|
| `postgres` | `pg_isready -U ${BETA_POSTGRES_USER}` | 10s |
| `redis` | `redis-cli ping` | 10s |
| `app` | `curl -f http://localhost:8000/api/health` | 15s |
| `worker` | `python -c "from app.beta.worker import healthcheck; healthcheck()"` | 30s |
| `nginx` | `curl -f http://localhost/api/health` | 15s |

`wooprice health all` runs these checks via the API and reports results in the CLI.

---

## Resource Limits

Default Docker resource limits (configurable via `docker-compose.beta.yml`):

| Service | CPU limit | Memory limit |
|---|---|---|
| `nginx` | 0.5 | 128 MB |
| `app` | 2.0 | 512 MB |
| `worker` | 1.0 | 256 MB |
| `postgres` | 2.0 | 1 GB |
| `redis` | 0.5 | 128 MB |

Limits can be adjusted by the operator via `wooprice configure` (stored in managed config;
regenerated into `docker-compose.beta.yml` by `docker compose up --force-recreate`).

---

## Logging Strategy

Application containers write structured JSON logs to stdout. Docker captures stdout
and routes it to:

1. `docker compose logs` (for operator tailing)
2. File log driver → `${BETA_STORAGE_PATH}/logs/` (configured in Docker Compose log options)

Log rotation is handled by Docker's `json-file` log driver with `max-size: 100m`
and `max-file: 5`, plus application-level rotation for files in `BETA_STORAGE_PATH/logs/`.

---

## Update Process

```
wooprice update apply --version X.Y.Z
  ↓
1. Check active schedules (warn if any)
2. Auto-create backup (wooprice backup create --label pre-update-X.Y.Z)
3. Pull new Docker images (docker compose pull)
4. Stop worker service
5. Run migrations (docker compose run --rm app alembic upgrade head)
6. Restart all services (docker compose up -d)
7. Run health check (wooprice health all)
8. If health check fails → automatic rollback from pre-update backup
```

The rollback is automatic on health check failure. The operator is notified of the
outcome and the full update log is written to `BETA_STORAGE_PATH/logs/update.log`.

---

## Backup and Recovery

See [INSTALLER_ARCHITECTURE.md](INSTALLER_ARCHITECTURE.md) for the backup create/restore
flow. Key points for deployment:

- Backups are always created before any update or migration
- `pg_dump` runs inside the `postgres` container via `docker compose exec`
- Backup archives are written to `${BETA_BACKUP_PATH}` on the host (outside Docker volumes)
- Restoring from backup stops the `app` and `worker` services, restores data, then restarts

---

## What Is Never Done

- No production database URL in any Beta Docker Compose file or container
- No `--privileged` containers
- No host networking mode (all internal communication via Docker bridge network)
- No secrets in Docker image build args or layer cache
- No Nginx port 80 redirect to HTTPS unless `BETA_SSL_MODE` is configured for it
- No containers run as root user (all containers use a non-root user in the final stage)
