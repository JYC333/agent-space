# Commands

## Quick Start

```bash
# Start everything (Docker Compose). First run creates ~/.aspace/dev/.env from template.
./ops/scripts/start.sh

# Other profiles
./ops/scripts/start.sh --test
./ops/scripts/start.sh --prod

# Force rebuild images
./ops/scripts/start.sh --build
```

## Backend

```bash
cd backend

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

# Database migrations (Alembic — run from backend/, against a reachable DB)
alembic revision --autogenerate -m "description"
alembic upgrade head
```

For the default Docker Compose setup, Postgres is **not** published to the host, so prefer the
helper which runs Alembic inside the backend container (see below) over bare `alembic`.

Default client-facing API (control-plane): http://localhost:8010
FastAPI docs (backend debug-only): http://localhost:8000/docs

In dev/test Docker Compose, control-plane hot reload is enabled: the service
uses the Dockerfile `dev-runtime` target, bind-mounts `control-plane/src` and
`packages/protocol/src`, runs both TypeScript compilers in watch mode, and
restarts with `node --watch dist/index.js`. Prod still runs compiled JS only.

Canonical backend test command (from repo root):

```bash
cd backend
pip install -r requirements.txt -r requirements-test.txt
python3 -m pytest tests/unit tests/contracts tests/invariants tests/workflows -v --tb=short
```

## Database scripts (run from repo root)

```bash
# Run migrations (Docker-native by default: Alembic runs INSIDE the backend
# container, using the in-network postgres service — reliable even though
# Postgres is not published to the host). When any control-plane TS authority is
# enabled, this also creates/updates the least-privilege control-plane DB role
# after Alembic succeeds. The normal start script also provisions that role
# before starting control-plane.
./ops/scripts/db/migrate.sh [--mode dev|test|prod]

# Host mode: only when DATABASE_URL points to a reachable external Postgres
# (runs a connectivity preflight first, then bare alembic on the host).
DATABASE_URL=postgresql+psycopg://... ./ops/scripts/db/migrate.sh --host [--mode dev|test|prod]

# Pre-migration backup: --mode prod ALWAYS takes a pg_dump custom-format dump to
# $ASPACE_ROOT/<mode>/db/dumps/pre-migrate-<ts>.dump before Alembic runs, and
# aborts if it fails. Opt into the same safety for non-prod modes:
PRE_MIGRATION_BACKUP=1 ./ops/scripts/db/migrate.sh --mode dev
./ops/scripts/db/migrate.sh --mode dev --pre-migration-backup

# Dump database to $ASPACE_ROOT/<mode>/db/dumps/
./ops/scripts/db/dump.sh

# Restore database from a pg_dump custom-format archive
./ops/scripts/db/restore.sh <path/to/dump.dump> [--mode dev|test|prod]

# Drop + recreate + migrate (destructive; reuses the Docker-native migrate path,
# including automatic control-plane DB role provisioning when TS authority is enabled)
./ops/scripts/db/reset-postgres.sh [--mode dev|test|prod]

# Open a psql shell
./ops/scripts/db/shell.sh [--mode dev|test|prod]
```

## Backup and restore (run from repo root)

```bash
# Full-system backup with app services stopped (PostgreSQL snapshot + files + manifest).
# Stop frontend/control-plane/backend/deployer first; postgres must remain running.
# When the backend is running, the BackupService API is canonical:
#   POST /api/v1/system/backups/manual
./ops/scripts/system/backup.sh [--mode dev|test|prod] [--include-logs] [--force-running]

# Full-system restore (database + files) from one archive.
# Stop frontend/control-plane/backend/deployer first; postgres must remain running.
./ops/scripts/system/restore.sh <archive.tar.gz> [--mode dev|test|prod] [--force] [--force-running]
```

See [docs/BACKUP_AND_RESTORE.md](../docs/BACKUP_AND_RESTORE.md) for the full model.

`tests/conftest.py` sets an isolated `AGENT_SPACE_HOME` before importing the app, so the suite cannot touch a real mode DB. Use `AGENT_SPACE_PYTEST_USE_REAL_HOME=1` only for explicit manual debugging.

## Frontend

```bash
cd apps/web

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

## Runtime CLI tools

Vendor CLIs are installed as instance runtime tools, not into Docker images.
Use the control-plane API after the stack is running:

```bash
curl -X POST http://localhost:8010/api/v1/runtime-tools/claude_code/install \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"version":"latest"}'

curl -X POST http://localhost:8010/api/v1/runtime-tools/codex_cli/install \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"version":"latest"}'

curl http://localhost:8010/api/v1/runtime-tools \
  -H "Authorization: Bearer <token>"
```

Tools are written under `$AGENT_SPACE_HOME/runtime-tools`; npm cache is under
`$AGENT_SPACE_HOME/cache/npm`.

## Docker

```bash
# Start all services (dev mode — default)
docker compose -f ops/compose/docker-compose.dev.yml up

# Rebuild and restart
docker compose -f ops/compose/docker-compose.dev.yml up --build

# Recreate a single service
docker compose -f ops/compose/docker-compose.dev.yml up backend --force-recreate

# View logs
docker compose -f ops/compose/docker-compose.dev.yml logs -f backend

# Check PostgreSQL health
docker compose -f ops/compose/docker-compose.dev.yml exec postgres \
  pg_isready -U agent_space -d agent_space
```

## Environment Variables

See `ops/env/.env.dev.example`, `.env.test.example`, and `.env.prod.example`
for the full list. `ops/scripts/start.sh --prod` rejects empty, placeholder, and
development `POSTGRES_PASSWORD` values. Key vars:

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | postgresql+psycopg://... | Set by docker-compose; PostgreSQL is required |
| `DEFAULT_USER_ID` | `default_user` | Bootstrap owner; the default space is this owner's personal space (a generated UUID, no fixed space id) |
| `REFLECTOR_MODE` | `pattern` | Set to `llm` to enable AI reflection |
| `MAX_CONCURRENT_DOCKER_RUNS` | `3` | Sandbox concurrency cap |
| `CONTROL_PLANE_PROVIDERS_AUTHORITY` | `ts` in env templates | Provider read authority |
| `CONTROL_PLANE_PROVIDERS_CREDENTIALS_AUTHORITY` | `ts` in env templates | Provider command, invocation, and credential-channel authority |
| `CONTROL_PLANE_RUNS_AUTHORITY` | `ts` in env templates | Run execute/stop command authority |
| `CONTROL_PLANE_POLICY_AUTHORITY` | `ts` in env templates | Policy enforcement and durable policy audit authority |
| `CONTROL_PLANE_PROPOSALS_AUTHORITY` | `ts` in env templates | Proposal review/read route authority; mutating review commands dispatch to Python internal proposal ports |
| `CONTROL_PLANE_MEMORY_AUTHORITY` | `ts` in env templates | Memory read and public memory proposal-create authority |
| `CONTROL_PLANE_MEMORY_APPLY_AUTHORITY` | `ts` in env templates | Accepted memory_create/update/archive proposal apply authority |
| `CONTROL_PLANE_DATABASE_URL` | generated by ops scripts | Least-privilege control-plane DB role URL |
| `CONTROL_PLANE_INTERNAL_TOKEN` | generated by ops scripts | Service token for internal TS/Python ports |
| `CONTROL_PLANE_CLI_TOOLS_ROOT` | `$AGENT_SPACE_HOME/runtime-tools` | Instance runtime CLI install root |

## Stage 4 TS runs verification

Focused verification commands from repo root:

```bash
cd packages/protocol
npm run typecheck && npm test && npm run build

cd ../control-plane
npm run typecheck
npx vitest run \
  test/runOrchestrationService.test.ts \
  test/runMaterializationService.test.ts \
  test/runManagedApiAdapter.test.ts \
  test/runVendorCliAdapter.test.ts \
  test/runJobRepository.test.ts \
  test/runRepository.test.ts \
  test/runPythonContextPorts.test.ts \
  test/runsRoutes.test.ts \
  test/runtimeHost.test.ts \
  test/config.test.ts \
  test/features.test.ts \
  test/boundaries.test.ts
npm run build

cd ../backend
./.venv/bin/python -m pytest \
  tests/contracts/test_runs_context_port_api.py \
  tests/unit/test_control_plane_db_role_grants.py \
  tests/unit/test_control_plane_entrypoint.py \
  tests/unit/test_runs_ts_authority_guard.py \
  -v --tb=short
```

Manual stack smoke after a reset/rebuild:

```bash
./ops/scripts/db/reset-postgres.sh --mode dev
./ops/scripts/start.sh --dev --build

# Use a real auth cookie/header from the web session.
curl -X POST http://localhost:8010/api/v1/runs/<run_id>/execute \
  -H "Authorization: Bearer <token>"
curl -X PATCH http://localhost:8010/api/v1/runs/<run_id>/stop \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"reason":"manual smoke"}'
curl http://localhost:8010/api/v1/runs/<run_id>/trace \
  -H "Authorization: Bearer <token>"
curl http://localhost:8010/api/v1/runs/<run_id>/events/stream \
  -H "Authorization: Bearer <token>"
```

## Stage 5 policy/proposals verification

Focused verification commands from repo root:

```bash
cd packages/protocol
npm run typecheck && npm test && npm run build

cd ../control-plane
npm run typecheck
npx vitest run \
  test/policyDecisionCore.test.ts \
  test/policyDecisionParity.test.ts \
  test/policyEnforceService.test.ts \
  test/policyRoutes.test.ts \
  test/proposalsRoutes.test.ts \
  test/config.test.ts \
  test/features.test.ts \
  test/gateway.test.ts \
  test/boundaries.test.ts
npm run build

cd ../backend
./.venv/bin/python -m pytest \
  tests/contracts/test_policy_action_registry.py \
  tests/contracts/test_policy_port.py \
  tests/contracts/test_policy_durable_audit.py \
  tests/unit/test_control_plane_policy_client.py \
  tests/unit/test_proposal_internal_ports.py \
  tests/unit/test_control_plane_db_role_grants.py \
  tests/unit/test_control_plane_entrypoint.py \
  tests/invariants/test_policy_gateway_boundary.py \
  -v --tb=short
```
