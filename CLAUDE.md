# agent-space — Claude Code Guide

> **AI agents:** Start from [`.agent/INDEX.md`](.agent/INDEX.md) and load the smallest relevant
> context bundle from [`.agent/context-bundles.yaml`](.agent/context-bundles.yaml).
> This file is a quick-start adapter for Claude Code — `.agent/architecture/` is source of truth.

## Project summary

Space-based, multi-user, agent-first memory system. Supports personal, family, and team spaces
within a single deployment instance. FastAPI backend with PostgreSQL, React frontend.

## Directory layout

```
~/agent-space/          ← source code repo (this directory; never store runtime data here)
  control-plane/          Future official TypeScript backend / control plane
  backend/                Current Python backend, migration-period authority
  catalog/                Built-in system definitions
    agent_templates/      System AgentTemplate factories
    capabilities/         Built-in capability manifests and code
  apps/web/               React/Vite web frontend + PWA (desktop deferred)
  ops/                    Compose files, env templates, and utility scripts
    compose/              docker-compose files for dev/test/prod
    env/                  tracked .env templates; local .env is ignored
    scripts/              start.sh, db/, system/
  sandbox/                Dockerfile for the agent execution sandbox image
  docs/                   Architecture documentation

~/.aspace/               ← ASPACE_ROOT: host-side parent holding the mode roots (override with ASPACE_ROOT)
  dev/                  ← default mode root (./ops/scripts/start.sh); bind-mounted as /aspace in Docker
    .env                  created from ops/env/.env.dev.example on first run
    config/ db/ logs/ …   app-created dirs under this mode tree
  test/ prod/             other modes (--test / --prod)
```

The source repo must **not** contain runtime data, user workspaces, sandboxes,
secrets, db files, or logs. Two environment variables control data layout, and they mean
different things:

- **`ASPACE_ROOT`** (scripts only) — the host-side parent directory that holds the
  `dev/`, `test/`, `prod/` mode roots. Default `~/.aspace`. `ops/scripts/start.sh` derives a
  mode root as `$ASPACE_ROOT/<mode>` and never treats `AGENT_SPACE_HOME` as this parent.
- **`AGENT_SPACE_HOME`** (the running app instance root) — the single data root for the
  currently running environment. In Docker backend containers it is the bind mount
  **`/aspace`**; for a direct local backend run it is a concrete mode root such as
  `$HOME/.aspace/dev`. It is **never** the parent that contains `dev/`/`test/`/`prod/`.

## Starting the system

```bash
./ops/scripts/start.sh           # Docker Compose — dev (default): backend + frontend + deployer
./ops/scripts/start.sh --test    # isolated test ports; data under ~/.aspace/test
./ops/scripts/start.sh --prod
./ops/scripts/start.sh --build   # Docker Compose with image rebuild
```

On first run, `start.sh` creates `~/.aspace/<mode>/` and copies the matching template
(`ops/env/.env.dev.example`, `.env.test.example`, or `.env.prod.example`) to
`~/.aspace/<mode>/.env` when missing. Edit that file to set credentials, then re-run.
For `--prod`, replace the placeholder `POSTGRES_PASSWORD`; startup rejects empty,
placeholder, and development passwords. The `.env` file is never stored in the repo.
All local DB/system scripts use `ops/scripts/lib/local-compose.sh` for the same mode/env
resolution path as `start.sh`: `ASPACE_ROOT`, `MODE_ROOT`, `ENV_FILE`,
`AGENT_SPACE_MODE_ROOT`, compose project/file, and `docker compose --env-file ...`.
Test mode exposes the API on `localhost:8100`, but the backend container still listens
on internal port `8000` and the frontend uses `http://backend:8000`.
PostgreSQL containers have stable names (`agent-space-<mode>-postgres`). Docker-native
migration, DB-only dump/restore/reset, and offline system backup/restore/verify
stop postgres after completion only when that script started it.

## Running the backend only

Without Docker, set the data root to a **mode directory** so paths match compose:

```bash
cd backend
export AGENT_SPACE_HOME="$HOME/.aspace/dev"
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

API docs: http://localhost:8000/docs

## Running tests

Canonical backend tests live under ``tests/unit``, ``tests/contracts``,
``tests/invariants``, and ``tests/workflows``. ``tests/conftest.py`` sets an
isolated ``AGENT_SPACE_HOME`` before importing the app.

```bash
cd backend
pip install -r requirements.txt -r requirements-test.txt
python3 -m pytest tests/unit tests/contracts tests/invariants tests/workflows -v --tb=short
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

- `backend/app/config.py` — `AppPaths` class + `Settings`; all runtime paths derive from `AGENT_SPACE_HOME` (the instance root)
- `backend/app/models.py` — SQLAlchemy ORM (Space, Memory, Session, **Task board** `Task`/`Board`/…, Run, Job, etc.)
- `backend/app/modules/registry.py` — backend module loader (which features are active)
- `backend/app/memory/store.py` — MemoryStore CRUD
- `backend/app/memory/context_builder.py` — context package assembly (requires space_id)
- `backend/app/proposals/api.py` — proposal review API
- `backend/app/memory/reflector.py` — session → memory proposals
- `backend/app/runs/execution.py` — RunExecutionService (canonical run orchestration)
- `backend/app/runtimes/specs.py` — RuntimeAdapterSpec catalog
- `backend/app/runtimes/adapters/cli_runtime.py` — GenericCliRuntimeAdapter local CLI execution
- `backend/app/capabilities/registry.py` — capability loader
- `apps/web/src/modules/registry.js` — frontend module loader (nav + lazy routes)

## Environment variables

```
# Instance data root for the running environment (NOT the dev/test/prod parent).
# Docker backend: /aspace. Direct local backend run: a concrete mode root, e.g. $HOME/.aspace/dev.
AGENT_SPACE_HOME=/aspace
# LLM provider API keys are NOT env/config — users add them in the app (Providers page),
# stored as encrypted ModelProvider Credentials (ADR 0010). The CLI runtime likewise gets
# its key from the credential broker, never from ambient env.
DEFAULT_MODEL=claude-sonnet-4-6
REFLECTOR_MODE=pattern   # or llm (llm mode uses REFLECTOR_MODEL_PROVIDER_ID, not an API key)
DEFAULT_USER_ID=default_user   # bootstrap owner; the default space is this owner's personal space (a generated UUID, not a fixed id)

# DATABASE_URL is the authoritative connection string. PostgreSQL is the only
# supported server database.
# DATABASE_URL=postgresql+psycopg://agent_space:password@localhost:5432/agent_space

# Advanced overrides (rarely needed — defaults derive from AGENT_SPACE_HOME)
# WORKSPACE_ROOT=$AGENT_SPACE_HOME/workspaces
# SANDBOX_ROOT=$AGENT_SPACE_HOME/sandboxes
```

`ops/scripts/` (host side) use `ASPACE_ROOT` (default `~/.aspace`) as the parent that holds
`dev/`, `test/`, `prod/`, derive `MODE_ROOT="$ASPACE_ROOT/<mode>"`, and never source a
mode `.env` as shell code just to read values.

## Adding a new feature module

**Backend:**
1. Create `backend/app/<module_id>/api.py` with `router = APIRouter(...)`
2. Add a `Module(...)` entry to `backend/app/modules/registry.py`

**Frontend:**
1. Create `apps/web/src/modules/<module_id>/<PageName>.jsx`
2. Add an entry to `apps/web/src/modules/registry.js` (use `React.lazy`)

## Adding a new capability

1. Create `catalog/capabilities/<your-id>/capability.yaml`
2. `POST /api/v1/capabilities/reload` or restart the server

## Adding a new runtime adapter

1. For a local CLI tool, add a `RuntimeAdapterSpec` in `backend/app/runtimes/specs.py`
2. Use `runtime_kind="local_cli"` and define executable, invocation, credentials, sandbox, usage, and output semantics
3. Do not add a vendor-specific runtime class unless the adapter truly needs native behavior beyond `GenericCliRuntimeAdapter`
4. For a native adapter, subclass `BaseRuntimeAdapter` and register it in `backend/app/runtimes/registry.py`
