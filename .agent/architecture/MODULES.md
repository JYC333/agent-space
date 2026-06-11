# Modules

> Current module map and ownership facts. Source of truth is still the code:
> `backend/app/modules/registry.py`, package `__init__.py` facades, and
> `backend/tests/invariants/test_module_import_boundaries.py`.

## Repository Roles

| Path | Role |
|---|---|
| `backend/` | Current Python FastAPI/PostgreSQL authority. Existing commands, writes, policy, proposals, memory, runs, jobs, schedulers, credentials, provider invocation, and migrations live here. |
| `control-plane/` | Default client-facing TypeScript API entrypoint/control plane. It owns only explicitly registered TS routes; unowned API paths proxy to Python. The gateway module is permanent; the legacy Python proxy is temporary. |
| `apps/web/` | Web client. It consumes APIs and shared protocol types; it is not a business-rule authority. |
| `catalog/` | Built-in definitions, including agent templates and capabilities. |
| `packages/protocol/` | Shared TypeScript protocol package only. No handlers, persistence, routing, or authority. |
| `ops/` | Compose files, env templates, and scripts. |
| `deployer/` | Host deployment subsystem behind the deployer boundary. |
| `sandbox/` | First-level sandbox subsystem. Runtime code uses documented interfaces rather than importing internals. |

No business authority has moved to TypeScript. Backend remains the Python authority for existing routes and writes; existing Python-owned routes continue through the control-plane proxy.

## Module Kinds

| Kind | Meaning |
|---|---|
| `kernel` | Identity, isolation, governance, execution spine. |
| `infra` | Cross-cutting infrastructure and runtime/host integration. |
| `capability` | Code-defined agent skills and self-evolution surfaces. |
| `product` | User-facing domain feature surface. |
| `frontend-support` | Backend read models and aggregation endpoints for UI views. |
| `support-package` | Import-only package under `backend/app/` with no HTTP module registration. |

`backend/app/modules/registry.py` lists registered HTTP modules. Support packages are real
boundaries too, but they are not mounted as modules.

## Registered HTTP Modules

All current registered modules are `always_on=True`.

| Package | Kind | Routes | Public facade | Main ownership / notes |
|---|---|---|---|---|
| `activity` | product | `/activity` | yes | Activity records and input summaries. |
| `agent_templates` | product | `/agent-templates` | empty | Template API over agent template models/services. |
| `agents` | product | `/agents` | empty | Agent profiles, versions, assistant chat/settings, template services; imports `runs` via facade. |
| `artifacts` | product | `/artifacts` | empty | Artifact read/export service. |
| `auth` | kernel | `/auth`, `/me` | yes | Users, auth accounts, sessions, API keys, Google auth. |
| `automation` | product | `/spaces/{space_id}/automations` | empty | Automations, schedule firing, credential preflight. |
| `backups` | infra | `/system/backups` | empty | Full-system backup service and backup tick used by `SchedulerRegistry`. |
| `capabilities` | capability | `/capabilities` | yes | Capability manifests, versions, overlays, registry/reload. |
| `credentials` | infra | `/credentials/cli` | yes | CLI credential broker/login and credential audit events. |
| `daily_reports` | product | `/daily-capture-report` | empty | Daily capture report settings, scheduler scan, durable job handler. |
| `deployment` | infra | `/deployments` | empty | Deployer client boundary. |
| `evolution` | capability | `/evolution` | empty | Evolution targets/signals and prompt-update proposal applier. |
| `execution_planes` | infra | `/execution-planes` | empty | Execution plane reads/resolution and default per-space seeding hook. |
| `home` | frontend-support | `/home` | empty | Home summary aggregation; imports `memory` and `proposals` via facades. |
| `intake` | product | `/intake` | empty | Source connections, intake items, extraction evidence, trust helpers. |
| `jobs` | infra | `/jobs` | empty | Durable job queue, worker, registry-dispatched handlers. |
| `knowledge` | product | `/knowledge`, `/notes` | empty | Knowledge items, notes, sources, read model, space seed hook, proposal appliers. |
| `me` | frontend-support | `/me` | empty | Personal view API. |
| `memory` | kernel | `/memory`, `/context` | yes, lazy | Memory entries, context build/compile, retrieval, reflection, source monitoring, proposal service placement exception. |
| `personal_memory_grants` | kernel | `/personal-memory-grants` | empty | Personal memory grants, egress guard/review/resolution. |
| `projects` | product | `/projects` | yes | Projects and project-workspace links. |
| `proposals` | kernel | `/proposals` | yes | Proposal API/read model/status lifecycle, approvals, applier registry. |
| `providers` | infra | `/providers` | yes | Model providers, provider catalog/validation, litellm invocation facade. |
| `runs` | kernel | `/runs` | yes, lazy | Run lifecycle, execution, events, finalization, runtime bridge, outputs/artifacts. |
| `runtime_adapters` | infra | `/runtime-adapters` | empty | Runtime adapter database records. |
| `runtime_tool_bindings` | infra | `/runtime-tool-bindings` | empty | Runtime tool binding records/services. |
| `sessions` | product | `/sessions` | empty | Conversation sessions, messages, condenser. |
| `source_pointers` | product | `/source-pointers` | empty | Source pointer creation/validation. |
| `spaces` | kernel | `/spaces`, `/invitations` | hook registry | Spaces, memberships, invitations, space-created hook dispatch. |
| `tasks` | product | `/tasks`, `/boards` | empty | Boards, tasks, task-run links, task evaluation, run-finalized hook. |
| `workspace_console` | frontend-support | `/workspace-console` | empty | Workspace console API. |
| `workspace_profiles` | product | `/workspace-profiles` | empty | Workspace profile service. |
| `workspaces` | product | `/workspaces` | empty | Workspace records and system-core workspace logic. |

## Support Packages

| Package | Kind | Public facade | Main ownership / notes |
|---|---|---|---|
| `actors` | support-package / kernel | empty | Actor identity helpers. |
| `modules` | support-package | empty | Backend module registry and hook registration loader. |
| `participation` | support-package / kernel | yes | Participation recording facade. |
| `policy` | support-package / kernel | yes | Policy gateway, engine, audit, hard invariants, `PolicyPort`. |
| `router` | support-package / kernel | yes | `RouterService`; single owner of intent, adapter, and `needs_cli` classification. |
| `runtimes` | support-package / infra | yes | Runtime adapter contract, specs, credentials, local executor, injected run ports. |
| `scheduler` | support-package / infra | yes | `SchedulerRegistry` and `ScheduledTask`. |
| `secrets` | support-package / infra | namespace | Secret reference encoding. |
| `visibility` | support-package / kernel | empty | Visibility-scoped auth helpers. |
| `workspace` | support-package / infra | empty | Disk path policy and sandbox manager; distinct from registered `workspaces`. |

`memory/consolidation/` is part of the registered `memory` module.

## Extension Registries And Hooks

| Concern | Owner | Registration model |
|---|---|---|
| HTTP routes | `app.modules.registry` | `Module(..., api_modules=[...])`; mounted under `/api/v1`. |
| Periodic tasks | `app.scheduler.SchedulerRegistry` | Lifespan registers `ScheduledTask`; owning modules keep tick behavior. |
| Durable job handlers | `app.jobs.JobHandlerRegistry` | Module declares `job_handlers="<submodule>"`; submodule exposes `register_job_handlers(registry)`. |
| Space-created initialization | `app.spaces.SpaceCreatedHookRegistry` | Module declares `space_created_hooks="<submodule>"`; hook runs in caller transaction and must not commit. |
| Run-finalized side effects | `app.runs.lifecycle_hooks.RunFinalizedHookRegistry` | Module declares `run_finalized_hooks="<submodule>"`; used for task evaluation bridge. |
| Proposal application | `app.proposals.applier_registry.ProposalApplierRegistry` | Module declares `proposal_appliers="<submodule>"`; target modules own mutation logic. |
| Routing decisions | `app.router.RouterService` | Single owner for intent classification, adapter resolution, and `needs_cli`. |
| Runtime execution | `app.runtimes` | Runtime adapters implement `BaseRuntimeAdapter`; `runs` injects runtime ports for events/process handles. |
| Model invocation | `app.providers` | `model_api` runtime adapter calls provider invocation through the provider facade. |

## Current Boundary Status

- Deep cross-package Python import allowlist is empty.
- Static guard detects no current import cycles.
- Current facade-level cross-package edges detected by the guard:
  `agents -> runs`, `home -> memory`, `home -> proposals`, `tasks -> auth`,
  `tasks -> participation`, `tasks -> proposals`, `tasks -> runs`.
- Lazy facades: `memory`, `runs`.
- Router compatibility wrappers are removed; do not recreate `IntentRouter` or `TaskRouter`.
- `runtimes` does not import `runs`; runtime evidence/process registration flows through
  injected ports implemented by `runs`.
- `runs` does not import `tasks`; task-board side effects use run-finalized hooks.
- Proposal apply dispatch goes through `ProposalApplierRegistry`; no hardcoded proposal-type
  apply chain remains.

The former known exception is resolved (2026-06-11): `ProposalService` and
`ProposalApplyService` now live physically under `backend/app/proposals/`
(`service.py`, `apply_service.py`), matching their logical ownership. The
`proposals` facade is hybrid — eager for `applier_registry`/`approvals`/
`read_model`, lazy (PEP 562) for `service`/`apply_service`, which reach into
`memory` only through its lazy facade. Target modules keep owning mutations
through `proposal_appliers.py` registration.

## Guardrails

Run these after structural module changes:

```bash
cd backend
python3 -m pytest tests/invariants/test_module_import_boundaries.py tests/invariants/test_public_facades.py -q
```

For registry-specific changes, also run the focused registry tests under `backend/tests/unit/`
for the affected registry.
