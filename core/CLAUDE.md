# core — Claude Code Guide

## What this is

The `core/` directory is the agent system kernel. It contains the memory system,
context builder, capability registry, session/task/agent run models, and API.
It is designed to be open-sourceable and must not contain real user data or secrets.

All runtime data lives in `~/aspace/` (the `AGENT_SPACE_HOME` data root), not inside this repo.

## Running the backend

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

API docs: http://localhost:8000/docs

## Running tests

```bash
cd backend
pytest tests/ -v --tb=short
```

## Key files

- `backend/app/models.py` — SQLAlchemy ORM (Space, Memory, Session, Task, etc.)
- `backend/app/memory/store.py` — MemoryStore CRUD
- `backend/app/memory/context_builder.py` — context package (requires space_id + user_id)
- `backend/app/memory/proposals.py` — proposal accept/reject workflow
- `backend/app/memory/reflector.py` — session → memory proposals
- `backend/app/agents/runner.py` — agent run orchestration
- `backend/app/capabilities/registry.py` — capability loader
- `backend/app/main.py` — FastAPI app entry point

## Environment variables

```
AGENT_SPACE_HOME=~/aspace    # data root; DB, workspaces, sandboxes, secrets all live here
ANTHROPIC_API_KEY=
DEFAULT_MODEL=claude-sonnet-4-6
REFLECTOR_MODE=placeholder   # or llm
DEFAULT_SPACE_ID=personal
DEFAULT_USER_ID=default_user
```

## Key concepts

- **space_id** — every data record is scoped to a space. The context builder enforces this boundary.
- **Visibility** — `private` | `space_shared` | `workspace_shared` | `restricted` | `public_template`
- **Memory proposal workflow** — agents never write memory directly; all writes go through proposals → user approval.

## Adding a new capability

1. Create `capabilities/<your-id>/capability.yaml` with required fields (id, name, version, description)
2. `POST /api/v1/capabilities/reload` or restart the server

## Adding a new agent adapter

1. Subclass `AgentAdapter` in `backend/app/agents/`
2. Implement `adapter_type`, `is_available()`, and `run()`
3. Register in `_ADAPTER_REGISTRY` in `runner.py`
