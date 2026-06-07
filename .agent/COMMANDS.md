# Commands

## Quick Start

```bash
# Start everything (Docker Compose). First run creates ~/.aspace/dev/.env from template.
./scripts/start.sh

# Other profiles
./scripts/start.sh --test
./scripts/start.sh --prod

# Force rebuild images
./scripts/start.sh --build
```

## Backend

```bash
cd core/backend

# Install runtime dependencies
pip install -r requirements.txt
# Install test/dev dependencies
pip install -r requirements-test.txt
# or inside venv:
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-test.txt

# Run (development, with hot reload)
uvicorn app.main:app --reload --port 8000

# Lint  [TODO: add ruff/flake8 config]
# ruff check app/

# Database migrations (Alembic — run from core/backend/, against a reachable DB)
alembic revision --autogenerate -m "description"
alembic upgrade head
```

For the default Docker Compose setup, Postgres is **not** published to the host, so prefer the
helper which runs Alembic inside the backend container (see below) over bare `alembic`.

API docs (interactive): http://localhost:8000/docs

Canonical backend test command (from repo root):

```bash
cd core/backend
pip install -r requirements.txt -r requirements-test.txt
python3 -m pytest tests/unit tests/contracts tests/invariants tests/workflows -v --tb=short
```

## Database scripts (run from repo root)

```bash
# Run migrations (Docker-native by default: Alembic runs INSIDE the backend
# container, using the in-network postgres service — reliable even though
# Postgres is not published to the host).
./scripts/db/migrate.sh [--mode dev|test|prod]

# Host mode: only when DATABASE_URL points to a reachable external Postgres
# (runs a connectivity preflight first, then bare alembic on the host).
DATABASE_URL=postgresql+psycopg://... ./scripts/db/migrate.sh --host [--mode dev|test|prod]

# Pre-migration backup: --mode prod ALWAYS takes a pg_dump custom-format dump to
# $ASPACE_ROOT/<mode>/db/dumps/pre-migrate-<ts>.dump before Alembic runs, and
# aborts if it fails. Opt into the same safety for non-prod modes:
PRE_MIGRATION_BACKUP=1 ./scripts/db/migrate.sh --mode dev
./scripts/db/migrate.sh --mode dev --pre-migration-backup

# Dump database to $ASPACE_ROOT/<mode>/db/dumps/
./scripts/db/dump.sh

# Restore database from a pg_dump custom-format archive
./scripts/db/restore.sh <path/to/dump.dump> [--mode dev|test|prod]

# Drop + recreate + migrate (destructive; reuses the Docker-native migrate path)
./scripts/db/reset-postgres.sh [--mode dev|test|prod]

# Open a psql shell
./scripts/db/shell.sh [--mode dev|test|prod]
```

## Backup and restore (run from repo root)

```bash
# Full-system backup with app services stopped (PostgreSQL snapshot + files + manifest).
# Stop backend/frontend/deployer first; postgres must remain running.
# When the backend is running, the BackupService API is canonical:
#   POST /api/v1/system/backups/manual
./scripts/system/backup.sh [--mode dev|test|prod] [--include-logs] [--force-running]

# Full-system restore (database + files) from one archive.
# Stop backend/frontend/deployer first; postgres must remain running.
./scripts/system/restore.sh <archive.tar.gz> [--mode dev|test|prod] [--force] [--force-running]
```

See [docs/BACKUP_AND_RESTORE.md](../docs/BACKUP_AND_RESTORE.md) for the full model.

`tests/conftest.py` sets an isolated `AGENT_SPACE_HOME` before importing the app, so the suite cannot touch a real mode DB. Use `AGENT_SPACE_PYTEST_USE_REAL_HOME=1` only for explicit manual debugging.

## Frontend

```bash
cd frontend

# Install dependencies
npm ci

# Run (development, with hot reload)
npm run dev
# → http://localhost:5173

# Build for production
npm run build

# Preview production build
npm run preview

# Lint  [TODO: configure eslint]
# npm run lint
```

## Sandbox Image

The sandbox image must be built before running local CLI runtimes such as `claude_code` or `codex_cli`:

```bash
docker build --network=host -t agent-space-sandbox deployments/sandbox/
```

This is done automatically by `./scripts/start.sh` in Docker mode.

## Docker

```bash
# Start all services (dev mode — default)
docker compose -f deployments/local/docker-compose.dev.yml up

# Rebuild and restart
docker compose -f deployments/local/docker-compose.dev.yml up --build

# Recreate a single service
docker compose -f deployments/local/docker-compose.dev.yml up backend --force-recreate

# View logs
docker compose -f deployments/local/docker-compose.dev.yml logs -f backend

# Check PostgreSQL health
docker compose -f deployments/local/docker-compose.dev.yml exec postgres \
  pg_isready -U agent_space -d agent_space
```

## Environment Variables

See `deployments/local/.env.dev.example`, `.env.test.example`, and `.env.prod.example`
for the full list. `scripts/start.sh --prod` rejects empty, placeholder, and
development `POSTGRES_PASSWORD` values. Key vars:

| Variable | Default | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Optional credential-broker API-key file env for `claude_code` |
| `OPENAI_API_KEY` | — | Optional credential-broker API-key file env for `codex_cli` |
| `DATABASE_URL` | postgresql+psycopg://... | Set by docker-compose; PostgreSQL is required |
| `DEFAULT_USER_ID` | `default_user` | Bootstrap owner; the default space is this owner's personal space (a generated UUID, no fixed space id) |
| `REFLECTOR_MODE` | `pattern` | Set to `llm` to enable AI reflection |
| `MAX_CONCURRENT_DOCKER_RUNS` | `3` | Sandbox concurrency cap |
