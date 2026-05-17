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

~/aspace/               ← local data parent (optional: set AGENT_SPACE_HOME to override this parent)
  dev/                  ← default mode root (./scripts/start.sh); bind-mounted as /aspace in Docker
    .env                  created from deployments/local/.env.example on first run
    config/ db/ logs/ …   app-created dirs under this mode tree
  test/ prod/             other modes (--test / --prod)
```

The source repo must **not** contain runtime data, user workspaces, sandboxes,
secrets, db files, or logs. When using `scripts/start.sh`, app-managed runtime data for a profile
lives under **`AGENT_SPACE_HOME/<mode>/`** on the host (defaults: `~/aspace/dev`, etc.). Inside
containers, **`AGENT_SPACE_HOME=/aspace`** always refers to that mounted mode directory.

## Starting the system

```bash
./scripts/start.sh           # Docker Compose — dev (default): backend + frontend + deployer
./scripts/start.sh --test    # isolated test ports; data under ~/aspace/test
./scripts/start.sh --prod
./scripts/start.sh --build   # Docker Compose with image rebuild
```

On first run, `start.sh` creates `~/aspace/<mode>/` and copies `deployments/local/.env.example` to
`~/aspace/<mode>/.env` when missing. Edit that file to set `ANTHROPIC_API_KEY`, then re-run.
The `.env` file is never stored in the repo.

## Running the backend only

Without Docker, set the data root to a **mode directory** so paths match compose:

```bash
cd core/backend
export AGENT_SPACE_HOME="$HOME/aspace/dev"
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

API docs: http://localhost:8000/docs

## Running tests

Canonical backend tests live under ``tests/unit``, ``tests/contracts``,
``tests/invariants``, and ``tests/workflows``. ``tests/conftest.py`` sets an
isolated ``AGENT_SPACE_HOME`` before importing the app.

```bash
cd core/backend && python3 -m pytest tests/unit tests/contracts tests/invariants tests/workflows -v --tb=short
```

## Key concepts

- **Space** — permission and collaboration boundary (personal / family / team). All data is scoped
  by `space_id`. A space is not the complete user worldview — a user may belong to many spaces.
  See `docs/SPACE_MODEL.md`.
- **User** — a person; may belong to multiple spaces.
- **Workspace** — a project or knowledge area within a space.
- **Memory** — scoped long-term information; written only through the proposal → approval workflow.
  Private memory (`visibility=private`) must live in the user's personal space only.
- **Capability** — code-defined skill registered via `capability.yaml` manifest.
- **Sandbox** — ephemeral isolated execution environment for agent runs.
- **PersonalView** — future: cross-space aggregation from a user's perspective (not yet built).
- **ExecutionContext** — per-run scope controlling which memories and tools an agent may access;
  wired today via `Run.instructed_by_user_id` → `ContextBuilder`.

## Space and memory model docs

- `docs/SPACE_MODEL.md` — space types, personal space convention, private memory definition,
  and the anti-pattern of private memory in shared spaces.
- `docs/TARGET_VIEW_MODEL.md` — target concepts: Space, Owner, Visibility, PersonalView,
  ExecutionContext, ParticipationRecord, SourcePointer, PublishProjection.

## Key files

- `core/backend/app/config.py` — `AppPaths` class + `Settings`; all runtime paths derive from `AGENT_SPACE_HOME`
- `core/backend/app/models.py` — SQLAlchemy ORM (Space, Memory, Session, **Task board** `Task`/`Board`/…, Run, Job, etc.)
- `core/backend/app/modules/registry.py` — backend module loader (which features are active)
- `core/backend/app/memory/store.py` — MemoryStore CRUD
- `core/backend/app/memory/context_builder.py` — context package assembly (requires space_id)
- `core/backend/app/proposals/api.py` — proposal review API
- `core/backend/app/memory/reflector.py` — session → memory proposals
- `core/backend/app/agents/runner.py` — agent run orchestration
- `core/backend/app/capabilities/registry.py` — capability loader
- `frontend/src/modules/registry.js` — frontend module loader (nav + lazy routes)

## Environment variables

```
AGENT_SPACE_HOME=~/aspace    # local data root; all sub-paths derive from this
ANTHROPIC_API_KEY=
DEFAULT_MODEL=claude-sonnet-4-6
REFLECTOR_MODE=pattern   # or llm
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
