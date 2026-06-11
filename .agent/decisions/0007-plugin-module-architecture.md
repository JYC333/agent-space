# ADR 0007: Plugin Module Architecture

## Status
**Accepted** — 2026-05-06

## Context

As the system grows it will target multiple deployment profiles:
- **Personal** — all features enabled (memory, knowledge, cards, media cards, activity inbox)
- **Team** — memory, knowledge, agents, workspaces; cards optional
- **Enterprise** — memory, agents, workspaces; no cards, no media cards

Before the codebase grew too large, we needed a structure that makes adding and excluding features mechanical — not a surgical restructuring.

The pre-0007 layout had:
- Backend: all HTTP routes in a flat `app/api/` directory; routers hardcoded in `main.py`
- Frontend: all pages in a flat `src/pages/`; routes hardcoded in `App.tsx`

This made it impossible to exclude a module at build time without deleting files.

## Decision

**Each feature is a self-contained module.** Modules live in named directories at the same level. Core kernel files (`config.py`, `db.py`, `models.py`, `schemas.py`) stay at `app/` root and are never optional.

### Backend layout

```
app/
  config.py, db.py, models.py, schemas.py   ← kernel (always-on)
  auth/      ← auth module: api.py + api_key.py
  memory/    ← memory module: api.py + context_api.py + store.py + ...
  agents/    ← agents module: api.py + runner.py + adapters + ...
  sessions/  ← sessions module: api.py + service.py
  tasks/     ← tasks module: api.py + service.py
  capabilities/ ← capabilities module: api.py + registry.py + loader.py
  workspace/ ← workspace module (no HTTP routes yet)
  modules/
    registry.py  ← module loader; `main.py` calls register(app) once
```

Each module's HTTP routes live in `<module>/api.py` (and optionally additional `*_api.py` files). Modules are registered via `app/modules/registry.py` — `main.py` no longer imports individual routers.

Optional modules (planned: `cards`) are listed but commented out in the registry until their backends are implemented. Knowledge has a backend module and remains a hidden frontend stub until the browser UI is built.

### Frontend layout

```
src/
  core/
    Shell.tsx       ← persistent app shell with NavRail
  modules/
    registry.ts     ← module manifest + lazy-loaded component map
    memory/         ← MemoriesPage, ProposalsPage, ContextPreviewPage
    agents/         ← AgentsPage (runs + versions)
    sessions/       ← SessionsPage
    capabilities/   ← CapabilitiesPage
    activity/       ← ActivityInboxPage (planned stub)
    knowledge/      <- KnowledgePage (planned stub)
    cards/          ← CardReviewPage (planned stub)
  App.tsx           ← routes generated from MODULE_REGISTRY; React.lazy per module
```

`MODULE_REGISTRY` in `apps/web/src/modules/registry.ts` is the single source of truth for navigation and routing. Each entry uses `React.lazy()` so Vite produces a separate JS chunk per module — unvisited routes are never downloaded.

The `planned: true` flag renders nav items as greyed-out with a "soon" badge; the route still exists so clicking it shows a planned stub rather than a 404.

## Consequences

**Good:**
- Adding a new module = create the directory, add one entry to each registry. No other files change.
- Excluding a module at deploy time = comment out the registry entry + (future) strip the directory in CI.
- Frontend modules are separate Vite chunks; disabled routes are never downloaded.
- `main.py` is now a loader, not a hardcoded list — same pattern across all deployments.
- Tests are unaffected; they import from `app.<module>.*`, not `app.api.*`.

**Accepted constraints:**
- Python doesn't tree-shake; disabled backend modules are still loaded into memory at startup. This is ~1–5 MB RSS per module — acceptable for self-hosted deployments.
- True per-module Python packaging (separate `pyproject.toml` per module) is deferred. When distribution requires it, the directory boundary makes the split mechanical: add a `pyproject.toml`, adjust relative imports to absolute, publish as separate wheel.
- Modules must not import from each other — only from the kernel (`app.db`, `app.config`, `app.models`, `app.schemas`, `app.auth`). This is enforced by convention; a lint rule can formalize it later.

## Cross-module imports (allowed exceptions)

The following cross-module references existed before this ADR and are allowed as explicit exceptions documented here:

- `tasks/api.py` imports `app.runs.run_service.RunService` — **task board** `POST /tasks/{id}/runs` creates a queued `Run` and `TaskRun` link; **Task is not modeled as Job** and this path does not enqueue product tasks as `agent_run` jobs.
- `sessions/api.py` imports `app.memory.reflector.MemoryReflector` — session reflect triggers memory proposals

**Removed:** the singular `POST /tasks/{id}/run` Job enqueue path and `job_type="product_task"` are gone. Tasks enqueue through `POST /api/v1/tasks/{id}/runs`, `RunService`, and `TaskRun` links instead.

These dependencies express real domain relationships. They must be documented here and may not grow without an ADR update.

## Related

- [0001](0001-space-model.md) — space isolation affects all modules
- [0006](0006-open-source-readiness.md) — module structure enables selective open-sourcing per module
