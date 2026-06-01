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
cd core/backend
pip install -r requirements.txt -r requirements-test.txt
python3 -m pytest tests/unit tests/contracts tests/invariants tests/workflows -v --tb=short
```

## Key files

- `backend/app/models.py` — SQLAlchemy ORM (Space, Memory, Session, **task board** `Task`/`Board`, Run, etc.)
- `backend/app/memory/store.py` — MemoryStore CRUD
- `backend/app/memory/context_builder.py` — context package (requires space_id + user_id)
- `backend/app/proposals/api.py` — proposal review API
- `backend/app/memory/reflector.py` — session → memory proposals
- `backend/app/runs/execution.py` — RunExecutionService (canonical run orchestration)
- `backend/app/runtimes/specs.py` — RuntimeAdapterSpec catalog
- `backend/app/runtimes/adapters/cli_runtime.py` — GenericCliRuntimeAdapter local CLI execution
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

## Adding a new runtime adapter

1. For a local CLI tool, add a `RuntimeAdapterSpec` in `backend/app/runtimes/specs.py`
2. Use `runtime_kind="local_cli"` and define executable, invocation, credentials, sandbox, usage, and output semantics
3. Do not add a vendor-specific runtime class unless the adapter truly needs native behavior beyond `GenericCliRuntimeAdapter`
4. For a native adapter, subclass `BaseRuntimeAdapter` and register it in `backend/app/runtimes/registry.py`

## Run execution

- `RunExecutionService` (`backend/app/runs/execution.py`) drives queued Runs through **real** runtime adapters resolved from `AgentVersion` / `RuntimeAdapter` rows / `runtime_policy_json` (`default_adapter_type`, `allowed_adapter_types`, `allowed_model_providers`).
- Built-in runtime adapter implementations live under `backend/app/runtimes/` (`echo` for zero-dependency tests, `capability` for capability-based execution). Anthropic/Claude execution uses the `claude_code` RuntimeAdapterSpec through the generic local CLI runtime path.
- Unsupported runtime query / job payload overrides are rejected. `POST .../runs/{id}/execute` may return **410 Gone** when such an override is supplied; the job handler rejects unsupported overrides with `ValueError` (prefix `runtime_removed:`); `RunExecutionService` returns `error_code=runtime_removed` **without** mutating the Run row. There is **no** synthetic adapter fallback when a real adapter fails.
- Text outputs are persisted with `ArtifactPersistenceService` under `artifact_storage_root`; ephemeral work uses `sandbox_root` (worktree isolation for high-risk policy) and is removed after the run while persisted artifact files remain.
