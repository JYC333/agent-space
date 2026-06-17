# ADR 0007: Plugin Module Architecture

## Status
**Accepted** — 2026-05-06; current implementation refreshed after the 2026-06 server cutover.

## Context

As the system grows it will target multiple deployment profiles:
- **Personal** — all features enabled (memory, knowledge, cards, media cards, activity inbox)
- **Team** — memory, knowledge, agents, workspaces; cards optional
- **Enterprise** — memory, agents, workspaces; no cards, no media cards

Before the codebase grew too large, we needed a structure that makes adding and excluding features mechanical — not a surgical restructuring.

The pre-0007 layout had:
- Backend routes registered from a central composition point rather than a module registry.
- Frontend pages in a flat `src/pages/`; routes hardcoded in `App.tsx`.

This made it impossible to exclude a module at build time without deleting files.

## Decision

**Each feature is a self-contained module.** Modules live in named directories at the same level. The server gateway, config, DB helpers, and protocol contracts are shared infrastructure and are never optional.

### Backend layout

```
server/src/
  config.ts
  db/
  gateway/
    routeRegistry.ts       ← active backend module registry
  modules/
    auth/
      index.ts
      routes.ts
    memory/
      index.ts
      routes.ts
      repository.ts
    agents/
      index.ts
      routes.ts
      repository.ts
    sessions/
      index.ts
      routes.ts
    tasks/
      index.ts
      routes.ts
    catalog/
      index.ts
      routes.ts
      service.ts
```

Each module exposes a `ServerModule` from `index.ts`; HTTP routes live in
`routes.ts`. Modules are registered through
`server/src/gateway/routeRegistry.ts`. `server.ts` remains the
composition root and does not register module routes directly.

Optional or planned modules may exist as frontend stubs, but backend routes are
only active when the server module is explicitly registered.

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
- `server.ts` stays a composition root, not a hardcoded feature list.
- Tests import module services/repositories directly or exercise the public route boundary.

**Accepted constraints:**
- Disabled backend modules must not be added to `SERVER_MODULES`.
- If a domain needs cross-module behavior, it should use an explicit service,
  repository, internal route, or protocol boundary rather than importing an
  unrelated route module.
- Future packaging can split modules mechanically because each module has a
  directory boundary and explicit registry entry.

## Cross-module imports (allowed exceptions)

The following cross-module references express real domain relationships and are
allowed as explicit exceptions documented here:

- `tasks` uses the runs domain to create queued Runs and `TaskRun` links. **Task is not modeled as Job** and this path does not enqueue product tasks as `agent_run` jobs.
- `sessions` reflection creates proposals through the memory/proposal boundary.
- `agents` chat and run creation use the context, runs, sessions, and provider/runtime boundaries.

**Removed:** the singular `POST /tasks/{id}/run` Job enqueue path and `job_type="product_task"` are gone. Tasks enqueue through `POST /api/v1/tasks/{id}/runs`, queued Run creation, and `TaskRun` links instead.

These dependencies express real domain relationships. They must be documented here and may not grow without an ADR update.

## Related

- [0001](0001-space-model.md) — space isolation affects all modules
- [0006](0006-open-source-readiness.md) — module structure enables selective open-sourcing per module
