# Modules

> Current module map and ownership facts. Source of truth is still the code:
> `server/src/gateway/routeRegistry.ts`,
> package facades, and boundary tests.

## Repository Roles

| Path | Role |
|---|---|
| `server/` | TypeScript API backend. The gateway module is permanent; unknown API paths return the local 404 catch-all. |
| `server/src/db/schema/` | Drizzle schema authoring source for database table/constraint/index shape. |
| `server/migrations/` | Generated SQL artifacts applied by the server migration runner. In this pre-history phase, `0001_baseline.sql` is the consolidated baseline. |
| `apps/web/` | Web client. It consumes APIs and shared protocol types; it is not a business-rule authority. |
| `catalog/` | Built-in definitions, including agent templates and capabilities. |
| `packages/protocol/` | Shared TypeScript protocol package only. No handlers, persistence, routing, or authority. |
| `ops/` | Compose files, env templates, and scripts. |
| `deployer/` | Host deployment subsystem behind the deployer boundary. |
| `sandbox/` | First-level sandbox subsystem. Runtime code uses documented interfaces rather than importing internals. |

Current server ownership is summarized in
[`SERVER_OWNERSHIP.md`](SERVER_OWNERSHIP.md).

## Module Kinds

| Kind | Meaning |
|---|---|
| `kernel` | Identity, isolation, governance, execution spine. |
| `infra` | Cross-cutting infrastructure and runtime/host integration. |
| `capability` | Code-defined agent skills and self-evolution surfaces. |
| `product` | User-facing domain feature surface. |
| `frontend-support` | Backend read models and aggregation endpoints for UI views. |
| `support-package` | Import-only package with no HTTP module registration. |

## Module Kinds vs. Official Optional Modules

**ServerModule** (in `gateway/routeRegistry.ts`) is the internal backend code registration unit. All `ServerModule` entries are unconditionally mounted at startup — they are not toggled at the code level.

**PluginHost** activates official plugin package artifacts from `server/dist/official-plugins/<plugin_id>/` after core server modules and before the API catch-all. Source for bundled official plugins lives under `plugins/official/<plugin_id>/`. PluginHost is the startup activation point for official plugin routes, jobs, scheduled tasks, and proposal appliers. Activation is synchronous by contract.

**Official Optional Modules** are a product control-plane layer above `ServerModule` and `PluginHost`. They gate runtime behavior (route responses, job handlers, scheduled tasks, proposal appliers, context contribution) via DB-backed plugin enablement, without per-scope route mounting. See [`OFFICIAL_OPTIONAL_MODULES.md`](OFFICIAL_OPTIONAL_MODULES.md) and ADR 0006.

The `plugins` module (Kind: `kernel`) is the control plane for official optional modules. Built-in official plugin code is activated through `PluginHost` and gated by the plugin guard in route handlers or host-wrapped contribution points.

## Registered HTTP Modules

Core modules are `always_on=True`. Optional product routes are still mounted by PluginHost, but respond with `plugin_disabled` when the plugin is disabled for the space/user.

| Module | Kind | Routes | Public facade | Main ownership / notes |
|---|---|---|---|---|
| `system` | infra | `/health`, `/server/health`, `/server/features`, `/features` | empty | Server health and feature descriptors. |
| `auth` | kernel | `/auth/*`, `/me`, `/me/spaces` | yes | Users, auth accounts, sessions, feature-gated API keys, Google auth. |
| `spaces` | kernel | `/spaces`, `/invitations` | hook registry | Spaces, memberships, invitations, space-created hook dispatch. |
| `catalog` | capability | `/server/catalog*`, `/capabilities*` | yes | Read-only on-disk catalog. Owns legacy catalog-backed capability/template manifest surfaces. |
| `capabilities` | capability | `/capability-definitions*`, `/capability-packs*`, `/workflow-templates*`, `/projects/{projectId}/workflow-profiles*`, `/skill-sources*`, `/skill-packages*` | yes | Capability/workflow/open-skill control plane: canonical definitions, packs, workflow templates, imported skill packages, project workflow profiles, and runtime skill bindings. Does not execute native capabilities. |
| `streaming` | infra | `/runs/{runId}/events/stream` | empty | Run event SSE stream. |
| `notifications` | infra | `/server/notifications/webhooks/*` | empty | Notification webhook egress policy and dispatch boundary. |
| `runtimeTools` | infra | `/runtime-tools*` | empty | Controlled runtime CLI installer/status/catalog. |
| `providers` | infra | `/providers*`, `/credentials/cli*`, `/internal/providers-credentials/*` | yes | Model providers, credential pools, provider invocation, and CLI credential broker/audit. There is no separate credentials route module. |
| `runtime_tool_bindings` | infra | `/runtime-tool-bindings*` | empty | Runtime tool binding reads. |
| `runtimeHost` | infra | `/internal/runtime-host/execute` | empty | Internal runtime-host execution for server-owned model/runtime paths. |
| `usage` | frontend-support | `/usage*` | yes | Token usage ledger and permission-filtered read models for managed API calls, provider-proxy calls, and managed-profile CLI transcript imports. Usage events are registered content resources with owner, visibility, disclosure level, source snapshot, and copied `selected_users` or `space_shared` disclosure grants. User aggregation filters events through the canonical content predicate before grouping; instance operations receive only de-identified totals. Protocol/schema values reserve future manual and cross-instance imports, but no product ingestion endpoint exposes them. Raw prompts, messages, request/response bodies, transcripts, and provider secrets are excluded. |
| `runs` | kernel | `/runs*`, `/internal/runs/execute` | yes, lazy | Run lifecycle, execution, events, finalization, runtime bridge, outputs/artifacts. |
| `artifacts` | product | `/artifacts*` | empty | Client-facing artifact list/get/export and run materialization artifacts. |
| `projects` | product | `/projects*` | yes | Projects and project-workspace links. |
| `project_presets` | product | `/project-presets`, `/projects/{projectId}/preset` | yes | Code-owned Project workflow preset descriptors and creation-time Project shape selection. |
| `project_research` | product | `/projects/{projectId}/research*` | yes | Academic Research preset workflow: research profile approval, workflow/stage/checkpoint state, artifact links, screening criteria, and the literature-matrix/synthesis/integrity read surfaces. Dispatches through existing Runs/Artifacts rather than a parallel execution system. |
| `policy` | kernel | `/internal/policy/*` | yes | Service-authenticated policy enforcement and proposal-apply policy gate. |
| `proposals` | kernel | `/proposals*` | yes | Proposal approval/apply orchestration and applier registry; unsupported proposal types fail closed. |
| `sessions` | product | `/sessions*`, `/internal/sessions/session-summary/get-latest` | empty | Conversation sessions, messages, and latest summary read. |
| `agentTemplates` | product | `/agent-templates*` | empty | Catalog-backed template list/read/create-agent surfaces. |
| `agents` | product | `/agents*` | empty | Agent profiles, versions, assistant chat/settings, template services, agent-scoped run/proposal reads. |
| `prompts` | capability | `/prompts/assets*` | empty | Prompt asset facade over evolvable assets, built-in manifest sync, immutable prompt versions, rendering/preview, evaluation evidence, labeled deployment refs, production promotion proposals, rollback, and runtime resolution. |
| `personalMemoryGrants` | kernel | `/personal-memory-grants*` | empty | Personal memory grant preview/create/list/revoke/audit. |
| `memory` | kernel | `/memory*` | yes, lazy | Memory entries, read logging, search, and memory proposal creation. |
| `context` | kernel | `/context/build` | empty | Frontend context preview/native context build route. |
| `activity` | product | `/activity*` | yes | Activity records, upload, review/archive, consolidation, and summary runs. |
| `publications` | product | `/publications*` | empty | Targeted immutable snapshots, target-Space discovery/import, and revocation. |
| `sources` | product | `/sources*` | empty | Source connections, source items, extraction evidence, trust helpers, summary runs. |
| `knowledge` | product | `/knowledge*`, `/notes/collections*` | empty | Knowledge items, notes, sources, entity links, source links, read model, and proposal appliers. |
| `relations` | product | `/relations*` | yes | People, organizations, identities, affiliations, relation notes, and relation provenance links over shared `space_objects` / `object_relations`. |
| `academic` | product | `/academic*` | yes | Academic paper object extension, paper authorship links, and citation links for Project presets and graph lenses. |
| `graph` | frontend-support | `/graph*` | empty | Read-only `GraphProjection` routes and per-user graph view-state persistence over visible `space_objects` / `object_relations`. |
| `evolution` | capability | `/evolution*` | empty | Evolution targets/signals, strategy assets, selector decisions, experiences, review prompts, validation reads, and review artifacts. |
| `tasks` | product | `/tasks*`, `/boards*`, `/me/tasks` | empty | Boards, tasks, task-run links, task evaluation, run-finalized hook. |
| `workspace_profiles` | product | `/workspace-profiles*` | empty | Workspace profile list/create/read/update. |
| `workspaces` | product | `/workspaces*`, `/workspace-console*` | yes | Workspace records, system-core workspace logic, PathPolicy, sandbox/worktree helpers, and workspace-console read routes. There is no separate workspace-console route module. |
| `jobs` | infra | `/jobs*` | yes | Durable job queue, worker, and registry-dispatched handlers. Re-exports scheduler types for compatibility only; new scheduler code imports `scheduler`. |
| `scheduler` | infra | none | yes | In-process periodic task registry, background service startup composition, and scheduler-owned `scheduler_tasks` cursor/state store. |
| `automations` | product | `/spaces/{spaceId}/automations*` | empty | Server-owned automations, schedule/manual fire, credential preflight, scheduler state in `scheduler_tasks`. |
| `dailyReports` | product | `/daily-capture-report*` | empty | Daily capture report user settings, manual run, scheduler scan, scheduler state in `scheduler_tasks`, durable job handler. |
| `backups` | infra | `/system/backups*` | empty | Server-owned full-system backup service and scheduled backup ticks. |
| `deployment` | infra | `/deployments/jobs*` | empty | Deployer client edge; create/detail currently fail closed with 501. |
| `frontendSupport` | frontend-support | `/home/summary`, `/me/summary`, `/me/timeline`, `/me/pending` | empty | Backend aggregate read models for Home and personal cross-space views. There are no separate `home` or `me` modules. |
| `plugins` | kernel | `/plugins*` | yes | Official optional module control plane: descriptor registry, DB-backed enablement, plugin guard. Must be registered before PluginHost activation. |

## Plugin-Hosted HTTP Surfaces

These routes are not `ServerModule` entries. They are mounted by `PluginHost` after `SERVER_MODULES` and before the API catch-all.

| Plugin | Kind | Routes | Main ownership / notes |
|---|---|---|---|
| `diary` | product (official_plugin) | `/diary*` | Personal diary editor, same-day history, reflection job, reminder scheduler. Routes use `ctx.http.pluginGuard()`. Diary entries are editor-owned user documents, not raw ActivityRecord input; memory/context extraction remains opt-in proposal/sources work. |
| `finance_ledger` | product (official_plugin) | `/finance*` | Space-scoped double-entry finance ledger: books, accounts, commodities, directives, postings, prices, and Beancount import/export. Routes use `ctx.http.pluginGuard()`. Proposal appliers are registered through PluginHost and plugin migrations own finance tables. |

## Code-Only Support Surfaces

| Package | Kind | Public facade | Main ownership / notes |
|---|---|---|---|
| `runtimeAdapters` | support-package / infra | yes | Runtime adapter specs/types only. Consumed by `agents`, `automations`, `runtimeTools`, and `runs`; not route-registered. |
| `routeUtils` | support-package / kernel | empty | Shared route helpers for DB pool access, identity resolution, pagination, parsing, and route error handling. |
| `access` | support-package / kernel | empty | Shared resource visibility predicates, common SQL read predicates, and space role helpers. It does not replace PolicyGateway or domain-owned ACLs. |
| `settings` | support-package / infra | yes | Generic scoped settings store for low-frequency instance, space, user, and space-user settings. Product modules own validation and DTOs; new code must not add feature-specific settings tables. |
| `scheduler` | support-package / infra | yes | In-process periodic task registry, scheduler task state store, and background service startup composition. |
| `workspaces/pathPolicy`, `workspaces/sandbox`, `workspaces/codePatch` | module-internal infra | yes via `workspaces` | Workspace path validation, worktree/sandbox preparation, and code-patch collection/apply ports. |

`memory/consolidation/` is part of the registered `memory` module.

## Extension Registries And Hooks

| Concern | Owner | Registration model |
|---|---|---|
| HTTP routes | server `gateway/routeRegistry.ts` + `PluginHost` | `ServerModule` entries mounted under `/api/v1`, then PluginHost mounts official plugin routes, then the catch-all. |
| Periodic tasks | server `modules/scheduler/SchedulerRegistry` | Server startup registers `ScheduledTask`; owning server modules keep tick behavior. |
| Scoped settings | server `modules/settings/ScopedSettingsStore` | Owning modules define typed descriptors and product validation; the settings module owns generic persistence for instance/space/user/space-user settings. |
| Durable job handlers | server `modules/jobs/JobHandlerRegistry` | server worker runtime registers allowlisted handlers (`agent_run`, `memory_consolidation`, `daily_capture_report`); unregistered types fail fast. |
| Official plugin routes/jobs/scheduler/proposal appliers | server `modules/plugins/host` | Built-in official plugins register synchronously through `PluginHostContext`; host wraps job handlers and proposal appliers with enablement checks. |
| Space-created initialization | server space hooks | server modules register space-created hooks; hook runs in caller transaction and must not commit. |
| Run-finalized side effects | server `runs` finalization service | Post-run finalization and task-board side effects are server-owned. |
| Proposal application | server proposal applier registry | Target modules own mutation logic; unsupported types fail closed. |
| Routing decisions | server router service | Single owner for intent classification, adapter resolution, and `needs_cli`. |
| Runtime execution | server `runs` | Run create, execute/stop, top-level read/status/trace, post-run finalization/evaluation, internal execute, `agent_run` dispatch, and runtime context preparation are server-owned. |
| Model invocation | server `providers` / `runtimeHost` | Run orchestration calls the server runtime-host/provider broker for `model_api` and `ts_agent_host` no-tool runs. |

## Current Boundary Status

- The route registry is the HTTP source of truth. Credential, Home, personal-view,
  and workspace-console routes are owned by `providers`, `frontendSupport`, and
  `workspaces` as listed above. The legacy `/capabilities*` manifest surface is
  owned by `catalog`; the capability/workflow/open-skill control plane is owned
  by `capabilities`.
- The server boundary guard restricts bare runtime package imports and forbids
  web, sandbox, deployer, ops, migration-tooling, and ORM internals from
  `server/src`.
- Lazy facades: `memory`, `runs`.
- Router compatibility wrappers are removed; do not recreate `IntentRouter` or `TaskRouter`.
- `runtimeAdapters` is code-only; runtime evidence/process registration flows through
  injected ports implemented by `runs`.
- Runs do not import task-board internals directly; task-board side effects use
  run-finalized hooks/finalization services.
- Proposal apply dispatch goes through `ProposalApplierRegistry`; no hardcoded proposal-type
  apply chain remains.
- Workspace-console session execution writes remain feature-not-implemented; current
  workspace-console routes are read/status surfaces under `workspaces`.
- Frontend Home and personal views consume `frontendSupport`/`/me` aggregate read
  models instead of independently re-implementing proposal/activity/runtime logic.

Target modules keep owning proposal mutations through the server proposal applier
registry; unsupported proposal types fail closed.

## Guardrails

Run these after structural module changes:

```bash
cd server
npm run typecheck
npx vitest run test/boundaries.test.ts
```
