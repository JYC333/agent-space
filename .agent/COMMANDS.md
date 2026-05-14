# Commands

## Quick Start

```bash
# Start everything (Docker Compose). First run creates ~/aspace/dev/.env from template.
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

# Install dependencies
pip install -r requirements.txt
# or inside venv:
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# Run (development, with hot reload)
uvicorn app.main:app --reload --port 8000

# Lint  [TODO: add ruff/flake8 config]
# ruff check app/

# Database migrations  [TODO: Alembic not yet initialised]
# alembic revision --autogenerate -m "description"
# alembic upgrade head
```

API docs (interactive): http://localhost:8000/docs

Canonical backend test command from repo root:

```bash
cd core/backend && python3 -m pytest tests/unit tests/contracts tests/invariants tests/workflows -v --tb=short
```

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

The sandbox image must be built before running `claude_cli` or `codex_cli` adapters:

```bash
docker build --network=host -t agent-space-sandbox deployments/sandbox/
```

This is done automatically by `./scripts/start.sh` in Docker mode.

## Docker

```bash
# Start all services
docker compose -f deployments/local/docker-compose.yml up

# Rebuild and restart
docker compose -f deployments/local/docker-compose.yml up --build

# Recreate a single service
docker compose -f deployments/local/docker-compose.yml up backend --force-recreate

# View logs
docker compose -f deployments/local/docker-compose.yml logs -f backend
```

## Environment Variables

See `deployments/local/.env.example` for the full list. Key vars:

| Variable | Default | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Required for claude_cli adapter |
| `OPENAI_API_KEY` | — | Required for codex_cli adapter |
| `DATABASE_URL` | sqlite:// | Set by docker-compose |
| `DEFAULT_SPACE_ID` | `personal` | |
| `DEFAULT_USER_ID` | `default_user` | |
| `REFLECTOR_MODE` | `pattern` | Set to `llm` to enable AI reflection |
| `MAX_CONCURRENT_SANDBOX_RUNS` | `3` | Sandbox concurrency cap |
