# WooPrice Beta — Development Guide

**Document:** DEVELOPMENT_GUIDE.md
**Series:** B1 Architecture Blueprint

---

## Overview

This document describes the local development setup, coding standards, testing approach,
and contribution workflow for WooPrice Beta.

**Important:** WooPrice Beta is in active development. The A2 Platform Core (`app/a2/`)
is frozen — do not modify it for Beta concerns. All new work belongs in `app/beta/`.

---

## Local Development Setup

### Prerequisites

- Python 3.12+
- Node.js 20+ and npm
- Docker Desktop (or Docker Engine + Compose plugin on Linux)
- Git
- `openssl` (usually pre-installed on Linux/macOS)

### First-time setup

```bash
# 1. Clone the repository
git clone <repo-url> wooprice-beta
cd wooprice-beta

# 2. Create Python virtual environment
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# 3. Install Python dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt  # dev-only tools: pytest, mypy, ruff, etc.

# 4. Install frontend dependencies
cd frontend && npm ci && cd ..

# 5. Start the dev stack (Docker Compose in dev mode)
./scripts/dev_start.sh
```

### Dev stack (`scripts/dev_start.sh`)

The dev stack starts PostgreSQL and Redis via Docker Compose but runs the Python
application directly on the host (not in a container) for fast iteration:

```bash
# Start only the infrastructure containers
docker compose -f docker-compose.dev.yml up -d postgres redis

# Run migrations
alembic -c alembic_a2.ini upgrade head
alembic -c alembic_beta.ini upgrade head

# Start the FastAPI app with hot reload
uvicorn app.main:app --reload --port 8000

# Start the frontend dev server (separate terminal)
cd frontend && npm run dev
```

In dev mode, the frontend dev server proxies `/api/` to `http://localhost:8000`.
The `[DEV ENVIRONMENT]` label appears in the UI.

### Environment for local dev

Copy `.env.example` to `.env.dev` and fill in the values for your local dev environment.
All test store URLs, test Nextcloud, and test WooCommerce credentials go here.
Never put production credentials here.

```bash
cp .env.example .env.dev
# Edit .env.dev with your dev values
export $(cat .env.dev | xargs)  # or use a tool like direnv
```

---

## Project Layout Quick Reference

```
app/a2/          — A2 Platform Core (FROZEN — do not modify)
app/beta/        — All Beta-specific backend code (your work goes here)
cli/             — wooprice CLI (Python + Typer)
frontend/src/    — React SPA (TypeScript + Tailwind)
alembic_a2/      — A2 migrations (FROZEN)
alembic_beta/    — Beta migrations (add new files here)
tests/a2/        — A2 tests (FROZEN — do not modify)
tests/beta/      — Beta tests (your tests go here)
docs/beta/       — Architecture blueprint documents (this series)
```

---

## Coding Standards

### Python

- **Style:** `ruff` for linting and formatting (configured in `pyproject.toml`)
- **Type hints:** Required on all public functions; `mypy` strict mode
- **Imports:** Absolute imports only; no `from app.a2 import *`
- **Docstrings:** One-line max; only when the why is non-obvious; no multi-paragraph blocks
- **Comments:** None unless explaining a non-obvious constraint or workaround
- **Error handling:** Only at system boundaries; trust SQLAlchemy and Pydantic guarantees internally
- **Database access:** Always through the repository layer; no raw SQL with user input
- **No magic strings:** Use Python enums or constants for category/status values

### TypeScript / React

- **Style:** `eslint` + `prettier` (configured in `.eslintrc` and `.prettierrc`)
- **Type hints:** Strict TypeScript (`"strict": true` in `tsconfig.json`); no `any`
- **Component structure:** One component per file; named exports only; no default export for pages
- **State:** Local state first; Context only when state is needed by 3+ components at different levels
- **API calls:** Only through `api/client.ts`; never raw `fetch` or `axios` directly in components
- **Feature gates:** All feature-flagged content must be wrapped in `<FeatureGate>`
- **Environment label:** Never read `BETA_ENV` in the frontend — use `config.env_label` from API response

### SQL / Migrations

- **Migration files:** One concern per migration; never two unrelated schema changes in one file
- **Naming:** `beta_NNN_description.py` (e.g., `beta_001_initial_schema.py`)
- **Reversible:** All migrations must implement `downgrade()` correctly
- **A2 migrations:** Never add to `alembic_a2/versions/` — A2 is frozen

---

## Testing

### Python tests

Tests use pytest with SQLite in-memory databases (StaticPool) for unit tests and the
real dev PostgreSQL for integration tests.

```bash
# Run all tests
./scripts/test.sh

# Run only unit tests (no integration)
pytest tests/ -m "not integration"

# Run only Beta tests
pytest tests/beta/

# Run A2 tests (should always pass — never modify these)
pytest tests/a2/

# Run with coverage
pytest tests/ --cov=app --cov-report=term-missing
```

### Test patterns

**Unit test pattern (same as A2):**

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.beta.users.models import BetaBase
from app.beta.users.repository import UserRepository

@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    BetaBase.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.rollback()
    session.close()
    BetaBase.metadata.drop_all(engine)

class TestUserRepository:
    def test_create_user(self, db_session):
        repo = UserRepository(db_session)
        user = repo.create(email="test@example.com", is_admin=False)
        assert user.email == "test@example.com"
```

**API test pattern:**

```python
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health_endpoint():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["env"] == "beta"
```

### Frontend tests

```bash
cd frontend

# Type check
npx tsc --noEmit

# Lint
npm run lint

# Unit tests (Vitest)
npm test

# Build (final check)
npm run build
```

### Coverage requirements

| Scope | Minimum coverage |
|---|---|
| `app/beta/` (new code) | 80% |
| `app/a2/` (frozen) | maintained at existing level |
| CLI commands (`cli/`) | 70% |

Coverage is checked in CI (B4).

---

## Adding a New API Endpoint

1. Create or add to the relevant router in `app/beta/api/v2/<resource>.py`
2. Define Pydantic request/response schemas in the router file (or a separate `schemas.py`)
3. Add the router to `app/main.py` (`app.include_router(...)`)
4. If the endpoint requires a feature flag, add `Depends(require_feature("FEATURE_*"))`
5. If the endpoint requires a permission, add `Depends(require_permission("..."))`
6. Write tests in `tests/beta/api/v2/test_<resource>.py`
7. Run `./scripts/generate_openapi.sh` to regenerate the OpenAPI spec
8. Run `cd frontend && npm run generate-api-types` to regenerate TypeScript API types

---

## Adding a New Migration

```bash
# Generate a new Beta migration
alembic -c alembic_beta.ini revision --autogenerate -m "description of change"

# Review the generated file in alembic_beta/versions/
# Edit if autogenerate missed anything

# Apply the migration
alembic -c alembic_beta.ini upgrade head

# Verify
alembic -c alembic_beta.ini current
```

Never edit an already-applied migration. Create a new migration to correct a mistake.

---

## Adding a Plugin

1. Create `plugins/examples/<your-plugin>/plugin.json` (use the schema in `plugins/schema/`)
2. Create the Python entry point file
3. Implement the appropriate interface (`SourceAdapterPlugin`, `ChannelAdapterPlugin`, etc.)
4. Write unit tests for the plugin in `tests/beta/plugins/test_<your-plugin>.py`
5. Test manually: `wooprice adapters install --from plugins/examples/<your-plugin>/`

See [PLUGIN_ARCHITECTURE.md](PLUGIN_ARCHITECTURE.md) for interface definitions.

---

## Running Linters

```bash
# Python (ruff)
ruff check app/ cli/ tests/
ruff format app/ cli/ tests/

# Python type checking (mypy)
mypy app/beta/ cli/

# TypeScript + ESLint
cd frontend && npm run lint

# All at once
./scripts/lint.sh
```

Pre-commit hooks run `ruff` and `eslint` automatically on staged files.

---

## Development Workflow

1. Create a feature branch: `git checkout -b feature/B5-xyz`
2. Implement the feature (backend, frontend, tests, migration if needed)
3. Ensure all tests pass: `./scripts/test.sh`
4. Ensure linting passes: `./scripts/lint.sh`
5. Open a PR against `main` (or the active development branch)
6. PR must pass CI (B4) before merge
7. No direct pushes to `main`

### Branch naming

| Type | Pattern | Example |
|---|---|---|
| Phase implementation | `feature/B<N>-short-description` | `feature/B5-product-inspector` |
| Bug fix | `fix/short-description` | `fix/plugin-reload-crash` |
| Documentation | `docs/short-description` | `docs/update-security-arch` |
| Migration only | `migration/beta-NNN-description` | `migration/beta-002-add-schedules` |

---

## Common Development Tasks

### Reset local dev environment

```bash
./scripts/dev_reset.sh
# Drops and recreates the dev database, re-runs all migrations
# Does NOT touch BETA_STORAGE_PATH or BETA_BACKUP_PATH
```

### View structured logs in dev

```bash
# Tail the app log (pretty-printed JSON)
tail -f ${BETA_STORAGE_PATH}/logs/app.log | python -m json.tool

# Or use the CLI
wooprice logs tail --service app
```

### Regenerate OpenAPI types

```bash
./scripts/generate_openapi.sh
# Output: frontend/src/api/openapi.json

cd frontend
npm run generate-api-types
# Output: frontend/src/api/v2/*.ts
```

---

## A2 Platform Core — Frozen Constraint

The `app/a2/` directory is read-only for Beta development. Do not:
- Add new files to `app/a2/`
- Modify existing files in `app/a2/`
- Add new migration files to `alembic_a2/versions/`
- Modify test files in `tests/a2/`

If you need a behavior change in A2 for Beta purposes, implement an adapter or
wrapper in `app/beta/` that calls the A2 service interface. Document the need as
a technical debt item if an A2 change is genuinely required.

**A2 tests must always pass.** Run them regularly: `pytest tests/a2/`. A CI check
enforces this on every PR.
