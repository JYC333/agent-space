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
