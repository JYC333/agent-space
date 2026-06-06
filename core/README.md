# core — Agent System Kernel

An agent-first runtime focused on structured, user-controlled long-term memory.

## What this is

`core/` is not a chatbot or a CRUD app. It is a **harness around agents**: it owns memory,
context, proposals, permissions, task board, and run logs while treating CLI tools (Claude,
Codex, etc.) as pure execution engines.

PostgreSQL is the only supported server database.

## Quick start

### Backend

```bash
cd backend
pip install -r requirements.txt
# Instance data root for a direct local run (a concrete mode root, not the dev/test/prod parent):
export AGENT_SPACE_HOME="$HOME/aspace/dev"
uvicorn app.main:app --reload --port 8000   # → http://localhost:8000/docs
```

The backend requires a reachable PostgreSQL database via `DATABASE_URL`
(`postgresql+psycopg://…`). The usual path is `./scripts/start.sh` from the repo root, which
brings up PostgreSQL, the backend, the frontend, and the deployer via Docker Compose.

### Frontend (React web app + PWA)

```bash
cd ../frontend
npm install
npm run dev        # → http://localhost:5173
```

The web app is React + Vite and is installable as a PWA. A `frontend/src-tauri/` directory
exists, but desktop packaging is **deferred and not part of the current product**.

## First milestone flow

1. Create a session
2. Add messages describing preferences and goals
3. Click "Reflect → Proposals" — system generates memory proposals
4. Review and accept/reject proposals
5. Build a context package — it reflects accepted memories

## Running tests

```bash
cd core/backend
pip install -r requirements.txt -r requirements-test.txt
python3 -m pytest tests/unit tests/contracts tests/invariants tests/workflows -v --tb=short
```

`tests/conftest.py` sets an isolated `AGENT_SPACE_HOME` before importing the app and runs the
suite against a throwaway PostgreSQL container, so pytest never opens a real mode database.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | dev/test local PostgreSQL URL | Backend DB (PostgreSQL only; authoritative connection string). Production must set an explicit non-development password. |
| `AGENT_SPACE_HOME` | `~/aspace` | Instance data root for the running environment (`/aspace` in Docker; a mode root locally) |
| `REFLECTOR_MODE` | `pattern` | `pattern` or `llm` |
| `REFLECTOR_MODEL_PROVIDER_ID` | `` | For `llm` reflector mode: the configured ModelProvider row to use. Its API key comes from the provider's encrypted Credential — never an env var (ADR 0010). |
| `VITE_API_URL` | `/api/v1` | Frontend API base URL |

## Project structure

```
core/
├── backend/           FastAPI backend (Python)
│   ├── app/
│   │   ├── memory/        MemoryStore, ContextBuilder, Reflector, Proposals
│   │   ├── runs/          RunExecutionService (canonical run orchestration)
│   │   ├── runtimes/      RuntimeAdapterSpec catalog + adapters
│   │   ├── jobs/          Durable PostgreSQL job queue + worker
│   │   ├── capabilities/  CapabilityRegistry
│   │   ├── backups/       BackupService (pg_dump full-system backup)
│   │   └── modules/       Backend feature-module registry
│   ├── migrations/    Alembic migrations (authoritative schema)
│   └── tests/
├── capabilities/      Capability manifests
├── memory/            Memory scaffold files
└── docs/              Architecture and design docs
```

The frontend lives at the repo root in `../frontend` (React + Vite), not inside `core/`.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design.
See [docs/FUTURE_ROADMAP.md](docs/FUTURE_ROADMAP.md) for the platform strategy.
