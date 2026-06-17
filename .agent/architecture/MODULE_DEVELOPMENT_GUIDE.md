# Module Development Guide

> How to add or change backend modules. Current module inventory lives in
> [`MODULES.md`](MODULES.md). Architectural invariants live in
> [`../BOUNDARIES.md`](../BOUNDARIES.md).

## What Counts As A Module

There are two backend boundary shapes:

- **Registered HTTP module:** listed in `backend/app/modules/registry.py`, usually with
  `backend/app/<module>/api.py`, and mounted under `/api/v1`.
- **Support package:** import-only package under `backend/app/` with no route registration
  (`policy`, `runtimes`, `router`, `scheduler`, `workspace`, etc.).

`backend/app/modules/registry.py` is the source of truth for registered HTTP modules.
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

1. Create `backend/app/<module_id>/`.
2. Add `__init__.py` with the module's narrow public facade.
3. Add `api.py` with `router = APIRouter(prefix="/<thing>", tags=["<thing>"])`.
4. Put domain logic in `service.py`; keep helpers internal unless they are intentionally
   exported by the package facade.
5. Add request/response schemas in the module or in `backend/app/schemas.py`, matching
   existing local patterns.
6. Add ORM classes to `backend/app/models.py` when the module owns new tables. Use UUID/string
   primary keys and include `space_id` for space-scoped data.
7. Add or update the canonical migration according to
   [`DATABASE_AND_TRANSACTIONS.md`](DATABASE_AND_TRANSACTIONS.md). If there is no historical
   data to preserve for a closeout/schema cleanup task, update canonical `0001` directly
   rather than adding an incremental migration.
8. Register the module in `backend/app/modules/registry.py`:

   ```python
   Module("<module_id>", "<Display Name>", "app.<module_id>", always_on=True)
   ```

9. Add focused tests under `backend/tests/{unit,contracts,invariants,workflows}/`.
10. If the module has a web surface, add it under `apps/web/src/modules/<id>/` and register it
    in `apps/web/src/modules/registry.ts` with a lazy entry point.

Routes must live in module route files, not in `main.py` or a shared API directory.

## Public Facades And Imports

Prefer importing package facades:

```python
from app.providers import complete_text
from app.runs import RunService
```

Avoid deep cross-package imports:

```python
from app.providers.invocation import complete_text  # avoid in peer modules
```

If a needed facade export is missing, add a narrow export instead of adding a deep-import
allowlist entry. The deep-import allowlist should stay empty by default.

Lazy facades currently exist for `memory` and `runs` to keep import-time side effects low.

## Dependency Rules

- Python remains the authority for existing business behavior until a specific migration moves
  a bounded context or command.
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
  orchestration is TS-owned in the control plane for registered appliers, and
  unregistered proposal types fail closed until their owning module migrates.

`ProposalService` and `ProposalApplyService` live under `backend/app/proposals/`
(`service.py`, `apply_service.py`), matching their logical ownership (moved from
`backend/app/memory/` on 2026-06-11).

## Extension Points

| Need | How to extend |
|---|---|
| HTTP route | Add `api.py` or extra route module and register it in `Module(..., api_modules=[...])`. |
| Periodic work | Keep tick behavior in the owning module; register `ScheduledTask` in lifespan with `SchedulerRegistry`. |
| Durable async job | Add module handler and expose `register_job_handlers(registry)`; declare `job_handlers="<submodule>"` in `Module(...)`. |
| Per-space initialization | Expose `register_space_created_hooks(registry)`; declare `space_created_hooks="<submodule>"`. Hooks run in the caller transaction and must not commit. |
| Post-run side effect | Expose `register_run_finalized_hooks(registry)`; declare `run_finalized_hooks="<submodule>"`. |
| Proposal apply behavior | Put mutation logic in the target module's `proposal_appliers.py`; expose `register_proposal_appliers(registry)` and declare it in `Module(...)`. |
| Runtime adapter | Register adapter/spec in `app.runtimes`; adapters return `RuntimeAdapterResult` and use `RuntimeExecutionContext` ports. |
| Model API runtime | Use `model_api` for no-tools provider-backed execution; it calls `app.providers` and does not use CLI credentials, terminal, local-host, or sandbox capabilities. |

## Ports

Use a `Protocol`/`ABC` when callers need substitution or tests need a fake. Existing examples:

| Port | File |
|---|---|
| `QueueService` | `jobs/queue.py` |
| `ProviderAdapter` | `providers/registry.py` |
| `BaseRuntimeAdapter` | `runtimes/base.py` |
| `MemoryProvider` | `memory/provider.py` |
| `ContextBuilderPort` | `memory/ports.py` |
| `PolicyPort` | `policy/ports.py` |
| `RuntimeEventSink`, `RuntimeProcessRegistry` | `runtimes/ports.py` |

Do not add ports for their own sake. A facade export is enough for a single concrete service
with no substitution need.

## Guardrails

Run these after structural module changes:

```bash
cd backend
python3 -m pytest tests/invariants/test_module_import_boundaries.py tests/invariants/test_public_facades.py -q
```

Add or run registry-specific tests when changing scheduler/job/space/run/proposal extension
points. Broaden to workflows/contracts when changing execution, proposal, task, or policy
behavior.
