# Modules

> Current module map and ownership facts. Source of truth is still the code:
> `control-plane/src/gateway/routeRegistry.ts`,
> `backend/app/modules/registry.py`, package `__init__.py` facades, and
> boundary tests.

## Repository Roles

| Path | Role |
|---|---|
| `backend/` | Python FastAPI/PostgreSQL service. Schema migrations, Python-owned product contexts, and routes not explicitly moved to TS live here. |
| `control-plane/` | Default client-facing TypeScript API entrypoint/control plane. It owns explicitly registered TS routes listed in `TS_CONTROL_PLANE_OWNERSHIP.md`; unowned API paths proxy to Python. The gateway module is permanent; the Python fallback proxy is temporary. |
| `apps/web/` | Web client. It consumes APIs and shared protocol types; it is not a business-rule authority. |
| `catalog/` | Built-in definitions, including agent templates and capabilities. |
| `packages/protocol/` | Shared TypeScript protocol package only. No handlers, persistence, routing, or authority. |
| `ops/` | Compose files, env templates, and scripts. |
| `deployer/` | Host deployment subsystem behind the deployer boundary. |
| `sandbox/` | First-level sandbox subsystem. Runtime code uses documented interfaces rather than importing internals. |

Current TS/Python ownership is summarized in
[`TS_CONTROL_PLANE_OWNERSHIP.md`](TS_CONTROL_PLANE_OWNERSHIP.md). Backend remains
the Python authority for unowned routes and writes; Python-owned routes continue
through the control-plane fallback proxy.

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
| `artifacts` | product | `/artifacts` | empty | Client-facing artifact list/get/export is TS-owned in the control plane; the Python module remains reference/fallback for Python-owned run paths. |
| `auth` | kernel | `/auth`, `/me` | yes | Users, auth accounts, sessions, API keys, Google auth. |
| `automation` | product | `/spaces/{space_id}/automations` | empty | TS-owned in the control plane: automations, schedule firing, credential preflight. |
| `backups` | infra | `/system/backups` | empty | TS-owned in the control plane: full-system backup service and backup tick used by the TS scheduler registry. |
| `capabilities` | capability | `/capabilities` | yes | Capability manifests, versions, overlays, registry/reload. |
| `credentials` | infra | `/credentials/cli` | yes | CLI credential broker/login and credential audit events. |
| `daily_reports` | product | `/daily-capture-report` | empty | TS-owned in the control plane: daily capture report settings, scheduler scan, durable job handler. |
| `deployment` | infra | `/deployments` | empty | Deployer client boundary. |
| `evolution` | capability | `/evolution` | empty | Evolution targets/signals and prompt-update proposal applier. |
| `execution_planes` | infra | `/execution-planes` | empty | Execution plane reads/resolution and default per-space seeding hook. |
| `home` | frontend-support | `/home` | empty | Home summary aggregation; imports `memory` and `proposals` via facades. |
| `intake` | product | `/intake` | empty | Source connections, intake items, extraction evidence, trust helpers. |
| `jobs` | infra | `/jobs` | empty | TS-owned in the control plane: durable job queue, worker, registry-dispatched handlers. |
| `knowledge` | product | `/knowledge`, `/notes` | empty | Knowledge items, notes, sources, read model, space seed hook, proposal appliers. |
| `me` | frontend-support | `/me` | empty | Personal view API. |
| `memory` | kernel | `/memory`, `/context` | yes, lazy | Memory entries, context build/compile, retrieval, reflection, source monitoring, proposal service placement exception. |
| `personal_memory_grants` | kernel | `/personal-memory-grants` | empty | Personal memory grants, egress guard/review/resolution. |
| `projects` | product | `/projects` | yes | Projects and project-workspace links. |
| `proposals` | kernel | `/proposals` | yes | Proposal approval/apply orchestration, approvals, and applier registry. Client-facing proposal review/read/apply orchestration is TS-owned for registered appliers; unregistered proposal types fail closed. |
| `providers` | infra | `/providers` | yes | Model providers, provider catalog/validation, litellm invocation facade. |
| `runs` | kernel | `/runs` | yes, lazy | Run lifecycle, execution, events, finalization, runtime bridge, outputs/artifacts. |
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
| Periodic tasks | control-plane `modules/jobs/SchedulerRegistry` | Control-plane startup registers `ScheduledTask`; owning TS modules keep tick behavior. |
| Durable job handlers | control-plane `modules/jobs/JobHandlerRegistry` | TS worker runtime registers allowlisted handlers (`agent_run`, `memory_consolidation`, `daily_capture_report`); unregistered types fail fast. |
| Space-created initialization | `app.spaces.SpaceCreatedHookRegistry` | Module declares `space_created_hooks="<submodule>"`; hook runs in caller transaction and must not commit. |
| Run-finalized side effects | `app.runs.lifecycle_hooks.RunFinalizedHookRegistry` | Module declares `run_finalized_hooks="<submodule>"`; used for task evaluation bridge. |
| Proposal application | `app.proposals.applier_registry.ProposalApplierRegistry` | Module declares `proposal_appliers="<submodule>"`; target modules own mutation logic. |
| Routing decisions | `app.router.RouterService` | Single owner for intent classification, adapter resolution, and `needs_cli`. |
| Runtime execution | control-plane `runs` / `app.runtimes` | Run create, execute/stop, top-level read/status/trace, post-run finalization/evaluation, the internal execute port, `agent_run` dispatch (control-plane worker loop), and runtime context preparation are fixed TS-owned. Python `app.runtimes` remains for unowned Python paths during migration. |
| Model invocation | control-plane `providers` / `runtimeHost` | TS-owned run orchestration calls the TS runtime-host/provider broker for `model_api` and `ts_agent_host` no-tool runs. Python provider facades remain for unowned Python routes. |

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
- TS-owned runs do not call Python hook registries directly; finalization and
  task-board side effects use the explicit Python `finalization.finalize` port.
- Python `runs` does not import `tasks`; task-board side effects use
  run-finalized hooks.
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
