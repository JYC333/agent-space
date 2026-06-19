# Module Development Guide

> How to add or change backend modules. Current module inventory lives in
> [`MODULES.md`](MODULES.md). Architectural invariants live in
> [`../BOUNDARIES.md`](../BOUNDARIES.md).

## What Counts As A Module

There are two backend boundary shapes:

- **Registered HTTP module:** exported from `server/src/modules/<module>/index.ts`
  and listed in `server/src/gateway/routeRegistry.ts`.
- **Support package:** import-only package under `server/src/modules/` with no
  direct route registration (`context`, `runtimeAdapters`, shared repositories, etc.).

`server/src/gateway/routeRegistry.ts` is the source of truth for registered HTTP modules.
Support packages are documented in `MODULES.md`.

## Module Classes

| Class | Meaning |
|---|---|
| `kernel` | Identity, isolation, governance, execution spine. |
| `infra` | Cross-cutting infrastructure and host/runtime integration. |
| `capability` | Code-defined agent skills and self-evolution surfaces. |
| `product` | User-facing domain feature surface. |
| `frontend-support` | Backend read models and aggregation endpoints for UI views. |
| `support-package` | Import-only package without HTTP route registration. |

## Adding A Registered Backend Module

1. Create `server/src/modules/<module_id>/`.
2. Add `index.ts` exporting the module facade and, when routed, a
   `ServerModule`.
3. Add `routes.ts` that registers Fastify routes under `/api/v1/...`.
4. Put domain logic in `service.ts` and persistence in `repository.ts`; keep helpers internal unless they are intentionally
   exported by the package facade.
5. Add request/response schemas in the module or `packages/protocol/src/` when
   the contract is shared with clients.
6. Add a new numbered SQL migration in `server/migrations/` when the
   module owns new tables. Use UUID/string primary keys and include `space_id`
   for space-scoped data.
7. Register the module in `server/src/gateway/routeRegistry.ts`.
8. Add focused tests under `server/test/`.
9. Run or update protocol tests when shared DTOs change.
10. If the module has a web surface, add it under `apps/web/src/modules/<id>/` and register it
    in `apps/web/src/modules/registry.ts` with a lazy entry point.

Routes must live in module route files, not in `server.ts` or a shared API directory.

## Public Facades And Imports

Prefer importing package facades:

```ts
import { createProviderCommandStore } from "../providers";
import { RunRepository } from "../runs";
```

Avoid deep cross-package imports:

```ts
import { InternalHelper } from "../providers/internalHelper"; // avoid in peer modules
```

If a needed facade export is missing, add a narrow export instead of adding a deep-import
allowlist entry. The deep-import allowlist should stay empty by default.

Keep facades narrow so tests and peer modules do not couple to internal helpers.

## Dependency Rules

- Modules should use public facades, ports, registries, or hooks rather than importing peer
  internals.
- Do not create package cycles.
- Kernel modules must not import product modules.
- Cross-module writes to Memory/Knowledge go through proposal/application flows, not direct
  service calls.
- `router` owns intent classification, adapter resolution, and `needs_cli`.
- `runs` owns execution lifecycle, run state/events/finalization/output/artifacts.
- `runtimes` own adapter execution and use injected ports for run evidence/process handles.
- `providers` own model invocation and provider credentials.
- `tasks` own task-board behavior, task-run product linkage, and task evaluation.
- `proposals` own approval/apply orchestration and the applier registry; target modules
  own proposal business mutations. Client-facing proposal review/read/apply
  orchestration is owned by the server for registered appliers, and
  unregistered proposal types fail closed until their owning module migrates.

`ProposalApplyService` and the proposal repository live under
`server/src/modules/proposals/`, matching their logical ownership.

## Extension Points

| Need | How to extend |
|---|---|
| HTTP route | Add or update `routes.ts` and register the module in `routeRegistry.ts`. |
| Periodic work | Keep tick behavior in the owning module; register `ScheduledTask` in lifespan with `SchedulerRegistry`. |
| Durable async job | Add a handler in the owning module and register it with the server job worker registry. |
| Per-space initialization | Register the hook through the server module/service path; hooks run in the caller transaction and must not commit. |
| Post-run side effect | Register a run-finalized hook with `PostRunFinalizationService` integration. |
| Proposal apply behavior | Put mutation logic in the target module and register it with the server proposal applier registry. |
| Runtime adapter | Register adapter/spec in `server/src/modules/runtimeAdapters`; adapters return `RuntimeAdapterResult` and use server runtime services. |
| Model API runtime | Use `model_api` for no-tools provider-backed execution; it calls server providers and does not use CLI credentials, terminal, local-host, or sandbox capabilities. |

## Adding An Official Optional Module

Official optional modules are product feature packages that can be enabled/disabled per
space or per user. Their control-plane descriptor lives in the `plugins` module,
while runtime code for bundled official plugins lives under `plugins/official/<plugin_id>/`,
is compiled into `server/dist/official-plugins/<plugin_id>/`, and is activated by `PluginHost`.

Steps:
1. Add an `OfficialPluginDescriptor` under `server/src/modules/plugins/official/<pluginId>.ts`.
2. Register the descriptor in `server/src/modules/plugins/registry.ts`.
3. If the plugin contributes runtime behavior, create `plugins/official/<plugin-id>/`.
4. Export an `AgentSpacePlugin` whose `activate(ctx)` synchronously registers routes, jobs,
   schedulers, and proposal appliers, then returns `{ activated: true }`.
5. Ensure the plugin package has `plugin.json` and `server/tsconfig.json`; `server/scripts/build-official-plugins.mjs` compiles it into `server/dist/official-plugins/<plugin-id>/`, and `server/src/modules/plugins/builtInPlugins.ts` loads that artifact at startup.
6. In plugin routes, call `ctx.http.pluginGuard(request, reply)` before returning any real content.
   Disabled state returns `{ error_code: "plugin_disabled" }`.
7. Add plugin-owned SQL files under `plugins/official/<plugin-id>/migrations/`,
   load them from the runtime plugin, and expose them through
   `AgentSpacePlugin.migrations`; the installer runs them, not `activate()`.
8. Put plugin-owned frontend pages under `plugins/official/<plugin-id>/web/src/`.
   Plugin frontend source must define the host API it needs and must not import
   `apps/web/src` directly.
9. Add a frontend entry with `source: 'official_plugin'`, `pluginId: '<id>'`, `enabled: false`
   in `apps/web/src/modules/registry.ts`, and lazy-import an app-owned adapter under
   `apps/web/src/plugins/<plugin-id>/`. The adapter imports the plugin page factory
   and injects frontend host APIs. Runtime state is overlaid from backend.
10. Use `useEffectivePlugins()` hook to show/hide UI elements based on backend state.
11. Add core migrations only for control-plane tables shared by all plugins; plugin-owned
    domain tables belong to installer-managed plugin migrations.
12. See `.agent/architecture/OFFICIAL_OPTIONAL_MODULES.md` and ADR 0007 for full context.

Implemented contribution points:
- Routes through `ctx.fastify` plus `ctx.http.pluginGuard()`.
- Job handlers through `ctx.jobs.register()`; the host wraps handlers with enablement checks.
- Scheduled tasks through `ctx.scheduler.register()`; task code must fan out only to enabled scopes.
- Proposal appliers through `ctx.proposals.register()`; the host wraps appliers with enablement checks.

Deferred contribution points:
- Context providers must not contribute when disabled.
- Activity sources and memory proposal generators must preserve the proposal/intake boundary.

Private/personal modules (e.g. dairy) must default to `can_contribute_context: "opt_in"`
and not contribute context unless the user has explicitly enabled it in settings. Editor-owned
plugin documents may write their own domain tables directly; extracting them into Memory,
Knowledge, ContextBuilder, or FlashCards must go through proposal/intake flows.

## Ports

Use a `Protocol`/`ABC` when callers need substitution or tests need a fake. Existing examples:

| Port | File |
|---|---|
| Job worker registry | `server/src/modules/jobs` |
| Provider command/store boundary | `server/src/modules/providers` |
| Runtime adapter services | `server/src/modules/runs` and `runtimeAdapters` |
| Memory repositories/read auth | `server/src/modules/memory` |
| Context preparation | `server/src/modules/context` |
| Policy gateway | `server/src/modules/policy` |

Do not add ports for their own sake. A facade export is enough for a single concrete service
with no substitution need.

## Guardrails

Run these after structural module changes:

```bash
cd server
COREPACK_ENABLE_AUTO_PIN=0 pnpm exec vitest run test/boundaries.test.ts
```

Add or run registry-specific tests when changing scheduler/job/space/run/proposal extension
points. Broaden to workflows/contracts when changing execution, proposal, task, or policy
behavior.
