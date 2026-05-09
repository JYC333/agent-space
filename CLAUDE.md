# agent-space — Claude Code Guide

## Project summary

Space-based, multi-user, agent-first memory system. Supports personal, family, and team spaces
within a single deployment instance. FastAPI backend with SQLite, React frontend.

## Directory layout

```
~/agent-space/          ← source code repo (this directory; never store runtime data here)
  core/                   Agent system kernel (memory, context, capabilities, API)
  frontend/               React/Vite web frontend + PWA (desktop deferred)
  deployments/            Deployment templates
  docs/                   Architecture documentation
  scripts/                Utility scripts (start.sh)

~/aspace/               ← local Agent Space data root (AGENT_SPACE_HOME, default: ~/aspace)
  config/                 App configuration (cli-credentials.yaml, …)
  secrets/                CLI credential profiles
  db/                     SQLite database
  storage/                Uploads, exports
  logs/                   App + agent run logs
  cache/                  Quota cache, runtime-homes
  runtime/                Transient runtime state
  workspaces/             Managed workspace repos  (<workspace_id>/repo)
  sandboxes/              Per-run agent sandboxes  (<run_id> or <ws_id>/<run_id>)
  artifacts/              Run artifacts, diffs, patches, reports
```

The source repo must **not** contain runtime data, user workspaces, sandboxes,
secrets, db files, or logs. All app-managed runtime data lives under `~/aspace`
(or wherever `AGENT_SPACE_HOME` points). Directories are created automatically
on first startup.

## Starting the system

```bash
./scripts/start.sh          # Docker Compose — backend + frontend
./scripts/start.sh --local  # bare processes, no Docker
./scripts/start.sh --build  # Docker Compose with image rebuild
```

On first run, `start.sh` creates `~/aspace/` and copies `.env.example` to
`~/aspace/config/.env`. Edit that file to set `ANTHROPIC_API_KEY`, then re-run.
The `.env` file is never stored in the repo.

## Running the backend only

```bash
cd core/backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

API docs: http://localhost:8000/docs

## Running tests

```bash
cd core/backend
pytest tests/ -v --tb=short
```

## Key concepts

- **Space** — top-level container (personal / family / team). All data is scoped by `space_id`.
- **User** — a person; may belong to multiple spaces.
- **Workspace** — a project or knowledge area within a space.
- **Memory** — scoped long-term information; written only through the proposal → approval workflow.
- **Capability** — code-defined skill registered via `capability.yaml` manifest.
- **Sandbox** — temporary isolated execution environment for agent runs.

## Key files

- `core/backend/app/config.py` — `AppPaths` class + `Settings`; all runtime paths derive from `AGENT_SPACE_HOME`
- `core/backend/app/models.py` — SQLAlchemy ORM (Space, Memory, Session, Task, etc.)
- `core/backend/app/modules/registry.py` — backend module loader (which features are active)
- `core/backend/app/memory/store.py` — MemoryStore CRUD
- `core/backend/app/memory/context_builder.py` — context package assembly (requires space_id)
- `core/backend/app/memory/proposals.py` — proposal accept/reject workflow
- `core/backend/app/memory/reflector.py` — session → memory proposals
- `core/backend/app/agents/runner.py` — agent run orchestration
- `core/backend/app/capabilities/registry.py` — capability loader
- `frontend/src/modules/registry.js` — frontend module loader (nav + lazy routes)

## Environment variables

```
AGENT_SPACE_HOME=~/aspace    # local data root; all sub-paths derive from this
ANTHROPIC_API_KEY=
DEFAULT_MODEL=claude-sonnet-4-6
REFLECTOR_MODE=placeholder   # or llm
DEFAULT_SPACE_ID=personal
DEFAULT_USER_ID=default_user

# Advanced overrides (rarely needed — defaults derive from AGENT_SPACE_HOME)
# DATABASE_URL=sqlite:////home/you/aspace/db/agent_space.sqlite
# WORKSPACE_ROOT=~/aspace/workspaces
# SANDBOX_ROOT=~/aspace/sandboxes
```

## Adding a new feature module

**Backend:**
1. Create `core/backend/app/<module_id>/api.py` with `router = APIRouter(...)`
2. Add a `Module(...)` entry to `core/backend/app/modules/registry.py`

**Frontend:**
1. Create `frontend/src/modules/<module_id>/<PageName>.jsx`
2. Add an entry to `frontend/src/modules/registry.js` (use `React.lazy`)

## Adding a new capability

1. Create `core/capabilities/<your-id>/capability.yaml`
2. `POST /api/v1/capabilities/reload` or restart the server

## Adding a new agent adapter

1. Subclass `AgentAdapter` in `core/backend/app/agents/`
2. Implement `adapter_type`, `is_available()`, and `run()`
3. Register in `_ADAPTER_REGISTRY` in `runner.py`
