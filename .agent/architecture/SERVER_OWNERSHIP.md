# Server Ownership

> **Status:** current repository fact, refreshed 2026-06-17. Code remains the
> source of truth. This document records only the active ownership split; it is
> not a migration log.

Rules:

- A command has exactly one authority at a time.
- Server-owned routes are explicitly registered in
  `server/src/gateway/routeRegistry.ts`.
- Unknown `/api/v1/*` routes return the local 404 catch-all.
- Schema migrations are owned by the explicit server migration runner under
  `server/migrations/`.

## Owned Contexts

| Context / surface | Server owns today | Deferred / fail-closed |
|---|---|---|
| Auth / spaces / identity | Session-cookie identity resolution, Google OAuth login/callback/config, `GET /auth/introspect`, `GET /me`, `GET /me/spaces`, `POST /auth/logout`, feature-gated API-key routes, `POST /spaces`, `GET /spaces/{id}`, `GET /spaces/{id}/members`, `POST /spaces/{id}/invitations`, `POST /invitations/{token}/accept`, and deterministic space-created default seeds | DB-persisted API-key storage until the canonical schema adds an `api_keys` table |
| Providers/credentials | Provider reads, commands, invocation, API-key credential pools, CLI credential login/broker/audit, internal provider/credential ports | — |
| Runtime adapters | `RuntimeAdapterSpec` catalog, adapter-type semantics, runtime-tool binding reads, server runtime-host/tool integration | `one_shot_docker` and managed API tool execution |
| Agents | Agent CRUD (`/agents*`), current-version/version list/read/restore, config updates as immutable `agent_versions`, default Assistant ensure/read, Assistant settings, agent-scoped run list/read subresources, catalog-backed agent template list/version reads, and create-from-template | Template catalog persistence remains catalog-file-backed; DB-backed template authoring is not implemented |
| Runs | Run creation via agent subresources, top-level run list/detail/status/trace, activity/artifact/proposal child read surfaces, execute/stop commands, internal execute port, deterministic post-run evaluation/finalization, `agent_run` worker dispatch, run execution evidence writes, native context.prepare consumption, and server worktree/ephemeral sandbox preparation for CLI runs | — |
| Agent group runs | `/agent-groups*` manager-owned room creation/list/detail, natural-language room messages with server-validated structured recipient segments, timeline/trace read models, pause/resume/cancel controls, authorized agent-to-agent delegation through `agent.delegate` and `run.spawn_child`, `agent.wait_for_results` same-room dependency waits, and delegation/wait lifecycle projection back into room messages/run events | Public direct child-run spawning and unmanaged agent-to-agent execution outside a group run |
| Jobs | Generic durable `jobs` queue (`/jobs*`), unified worker registry (`agent_run`, `memory_consolidation`, `daily_capture_report`, `context_digest_refresh`, `session_condense`), stuck-job reclaim, and stale running-run recovery at worker startup | — |
| Scheduler | Scheduler-owned `scheduler_tasks` cursor/state store, in-process scheduler registry, background service startup composition, non-overlapping scheduler task execution, and scheduled ticks for daily capture report, automation, memory access-log retention, memory maintenance, intake extraction polling, Custom Source polling/reclaim, and backup | — |
| Settings | Generic scoped `settings` persistence for low-frequency instance, space, user, and space-user settings via `ScopedSettingsStore`; owning product modules define typed descriptors, authorization, validation, and DTOs | Feature-specific settings tables are not allowed for new low-frequency settings |
| Automations | `/spaces/{id}/automations*`, schedule/manual fire with policy preflight, automation run records, automation schedule rows in scheduler-owned `scheduler_tasks` | — |
| Daily capture report | `/daily-capture-report/*` user settings via scoped settings, manual run, report listing, daily report task rows in scheduler-owned `scheduler_tasks`, scheduler enqueue of `daily_capture_report` jobs | — |
| Backups | `/system/backups` list/manual trigger, scheduled backup ticks, prod backup policy guard, and backup lock/stale-lock handling | — |
| Policy | Sensitive-action enforcement, proposal-apply policy gate, durable policy audit | — |
| Proposals | External proposal review/read routes, accept/reject/egress-approval/rollback commands, proposal-apply orchestration, and the server applier registry for registered memory, knowledge, task follow-up, and code-patch types | Target-module appliers that are not registered; unregistered proposal types fail closed |
| Sessions | Public list/get/create session commands, list/add messages, latest-summary read, condenser preset-prompt reads, summary condense/create writes (`condenseSession`: `llm.v1` via the `session_condense` job with scenario profiles plus per-agent prompt overrides, deterministic `pattern.v1` fallback), and session reflection proposal creation | — |
| Assistant chat | External Personal Assistant chat turn orchestration and queued run creation for server context chat turns | — |
| Context | Native chat-path candidate collection (`modules/context`: memory/knowledge/source/activity reads), frontend context preview build route, budget/dedup loop, selected-item snapshot persistence, full-run context package assembly, context evidence selection/`used_in_context` link recording for existing evidence, memory context-injection logs, `context_snapshots` population, and vendor runtime file rendering to sandboxes | Digest refresh jobs |
| Memory read/write boundary | `/memory` list/get/search, read-access logging, public memory create/update/archive proposal creation, batch activity consolidation via `POST /memory/consolidation/run` | Memory quality/evolution jobs (digest refresh, memory-health solidification, source-monitoring producers) |
| Memory apply | Accepted `memory_create` / `memory_update` / `memory_archive` apply after the proposal-apply policy gate | Personal-memory egress-context placement, active-policy private-placement overlay, workspace/agent-scope digest invalidation |
| Activity | DB-backed `/activity*` capture/list/detail/upload/review/archive, source-pointer list/create/delete, per-activity consolidation, and summary artifact/proposal creation with activity/evidence/intake provenance | LLM summarization quality improvements beyond the current classifier pipeline |
| Intake | DB-backed `/intake*` connector/connection config, manual URL intake, extraction-job audit records, candidate evidence/evidence links, project-scoped workspace source bindings, summary artifact/proposal creation, and in-process extraction polling | External fetch fidelity beyond the current extraction worker |
| Knowledge | DB-backed `/knowledge*` item proposal routes, source/note/entity-link CRUD, note collection CRUD, item/source links, relation proposals, and knowledge proposal appliers | Schema migrations and any deferred background knowledge quality jobs |
| Tasks | DB-backed `/tasks*`, `/boards*`, and `/me/tasks` boards/tasks CRUD, queued Run creation through `task_runs`, task artifacts/proposals reads, task evaluations, and the run-finalization → task-evaluation bridge | Worker execution itself remains owned by Runs/runtime |
| Artifacts | Client-facing `GET /artifacts`, `GET /artifacts/{id}`, `GET /artifacts/{id}/export`, and run-scoped artifact routes, including scoped visibility checks and managed-storage export path guards | — |
| Projects | DB-backed `/projects*` project CRUD, archive, summary, and project-workspace links | — |
| Capabilities / templates | Catalog-backed `/capabilities*` and `/agent-templates*` product routes | Capability/template authoring remains file/catalog controlled |
| Evolution | `/evolution*` target/signal surfaces, strategy assets, selector decisions, experiences, review prompts, real `run_type='evolution'` run creation, and review artifact recording | Automatic apply/deploy/code-merge loops and unregistered proposal appliers |
| Personal memory grants | `/personal-memory-grants*` preview/create/list/revoke/audit for run-scoped summary-only grants | Raw personal-memory egress apply path remains fail-closed |
| Workspaces / sandbox | DB-backed `/workspaces*`, workspace profile list/create/read/update, workspace snapshot-retention settings (`snapshot_retention_days`, `snapshot_max_count`), workspace-console read routes, runtime status/session stubs, PathPolicy, workspace read policy audit, worktree prepare/cleanup, sandbox GC, worktree code_patch collection, accepted `code_patch` proposal apply through `workspace.write_patch` (with pre-apply `code_patch_snapshots` capture), and user-facing rollback via `POST /api/v1/proposals/{id}/rollback` | Workspace-console session execution writes remain feature-not-implemented |
| Deployment | Server-owned `/deployments/jobs*` edge routes, core deployer socket client, and job-type allowlist for `rebuild_agent_space`, `restart_agent_space`, and `health_check` | Deployer remains a separate host/sidecar process; deployment job persistence/proposal flow remains deferred because the current API is a feature-not-implemented stub |

Current ownership aliases to avoid migration-drift mistakes:

- `catalog` owns catalog-backed `/capabilities*` and `/server/catalog*` surfaces;
  there is no standalone `capabilities` route module.
- `providers` owns provider credentials and the `/credentials/cli*` broker/audit
  surfaces; there is no standalone `credentials` route module.
- `frontendSupport` owns `/home/summary` and `/me/{summary,timeline,pending}`;
  there are no standalone `home` or `me` route modules.
- `workspaces` owns the current `/workspace-console*` read/status routes; there
  is no standalone workspace-console route module.

The active route-registered server modules are: `system`, `auth`,
`spaces`, `catalog`, `capabilities`, `streaming`, `notifications`, `runtimeTools`,
`networkProfiles`, `providers`, `runtime_tool_bindings`, `runtimeHost`, `runs`,
`artifacts`, `projects`, `policy`, `proposals`, `sessions`, `agentTemplates`, `agents`,
`personalMemoryGrants`, `memory`, `context`, `contextOps`, `askSpace`, `activity`,
`source_pointers`, `intake`, `knowledge`, `agentGroups`, `evolution`, `tasks`, `workspace_profiles`,
`workspaces`, `jobs`, `automations`, `dailyReports`, `backups`, `deployment`,
`frontendSupport`, and `plugins`.
`runtimeAdapters` is a first-class code-only domain consumed by `runs`,
`runtimeHost`, and `runtimeTools`.

## Deferred Boundaries

These are intentional deferred/fail-closed gaps today, not evidence that the
TypeScript backend cutover failed:

- DB-persisted API-key storage; the API-key routes return the canonical
  feature-gated response while the schema has no `api_keys` table;
- memory digest refresh, memory-health solidification, source-monitoring producers, and quality loops;
- non-memory/non-knowledge/non-task/non-code-patch proposal target appliers;
- deployer host/sidecar process internals and deferred deployment job persistence.

## Guards

Fail-closed behavior lives in server route/service boundaries and explicit 501
responses for deferred surfaces.

## Operational Notes

In bundled compose modes, server connects with the Postgres owner/app
role derived from `POSTGRES_*`; `ops/scripts/lib/local-compose.sh` generates
`SERVER_DATABASE_URL` and the internal token, but does not create a
separate per-table app role.

Server DB connections and transactions are centralized in
`server/src/db/`. The server migration runner and SQL files under
`server/migrations/` are the runtime schema authority. They are explicit
ops commands invoked by `ops/scripts/start.sh` before app services start; they
are not wired into the server service process startup.

Focused verification commands are listed in [`../COMMANDS.md`](../COMMANDS.md).
