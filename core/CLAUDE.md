# core — Claude Code Guide

## What this is

The `core/` directory is the agent system kernel. It contains the memory system,
context builder, capability registry, session, **task board**, agent run models, and API.
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

Canonical backend tests live under ``tests/unit``, ``tests/contracts``,
``tests/invariants``, and ``tests/workflows``. ``tests/conftest.py`` sets an
isolated ``AGENT_SPACE_HOME`` before importing the app.

```bash
cd core/backend && python3 -m pytest tests/unit tests/contracts tests/invariants tests/workflows -v --tb=short
```

## Key files

- `backend/app/models.py` — SQLAlchemy ORM (Space, Memory, Session, **task board** `Task`/`Board`, Run, etc.)
- `backend/app/memory/store.py` — MemoryStore CRUD
- `backend/app/memory/context_builder.py` — context package (requires space_id + user_id)
- `backend/app/proposals/api.py` — proposal review API
- `backend/app/memory/reflector.py` — session → memory proposals
- `backend/app/agents/runner.py` — agent run orchestration
- `backend/app/capabilities/registry.py` — capability loader
- `backend/app/main.py` — FastAPI app entry point

## Environment variables

```
AGENT_SPACE_HOME=~/aspace    # data root; DB, workspaces, sandboxes, secrets all live here
ANTHROPIC_API_KEY=
DEFAULT_MODEL=claude-sonnet-4-6
REFLECTOR_MODE=pattern   # or llm
DEFAULT_SPACE_ID=personal
DEFAULT_USER_ID=default_user
```

## Key concepts

- **space_id** — every data record is scoped to a space. The context builder enforces this boundary.
- **Visibility** — `private` | `space_shared` | `workspace_shared` | `restricted` | `public_template`
- **Proposal workflow** — durable memory and code mutations require proposals and user approval.

## Adding a new capability

1. Create `capabilities/<your-id>/capability.yaml` with required fields (id, name, version, description)
2. `POST /api/v1/capabilities/reload` or restart the server

## Adding a new agent adapter

1. Subclass `AgentAdapter` in `backend/app/agents/`
2. Implement `adapter_type`, `is_available()`, and `run()`
3. Register in `_ADAPTER_REGISTRY` in `runner.py`

## Run execution (Phase 11)

- `RunExecutionService` (`backend/app/runs/execution.py`) drives queued Runs through **real** runtime adapters resolved from `AgentVersion` / `RuntimeAdapter` rows / `runtime_policy_json` (`default_adapter_type`, `allowed_adapter_types`, `allowed_model_providers`).
- Built-in runtime adapter implementations live under `backend/app/runtimes/` (`echo` for zero-dependency tests, `anthropic_messages` for the Messages API — configure `ANTHROPIC_API_KEY` or adapter `config_json`; secrets are never written to logs).
- Obsolete **runtime query / job payload overrides** from removed in-process tooling are not executed. `POST .../runs/{id}/execute` may return **410 Gone** when such an override is supplied; the job handler rejects obsolete overrides with `ValueError` (prefix `runtime_removed:`); `RunExecutionService` returns `error_code=runtime_removed` **without** mutating the Run row. There is **no** synthetic adapter fallback when a real adapter fails.
- Text outputs are persisted with `ArtifactPersistenceService` under `artifact_storage_root`; ephemeral work uses `sandbox_root` (worktree isolation for high-risk policy) and is removed after the run while persisted artifact files remain.
