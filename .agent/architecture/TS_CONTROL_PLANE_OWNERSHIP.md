# TS Control-Plane Ownership

> **Status:** current repository fact, refreshed 2026-06-17. Code remains the
> source of truth. This document records only the active ownership split; it is
> not a migration log.

Rules:

- A command has exactly one authority at a time.
- TS-owned routes are explicitly registered in
  `control-plane/src/gateway/routeRegistry.ts`.
- Unowned `/api/v1/*` routes still fall through to Python through the temporary
  fallback proxy.
- Python/Alembic remains the schema owner.

## TS-Owned Contexts

| Context / surface | TS owns today | Python still owns |
|---|---|---|
| Auth / spaces / identity | Session-cookie identity resolution, Google OAuth login/callback/config, `GET /auth/introspect`, `GET /me`, `GET /me/spaces`, `POST /auth/logout`, feature-gated API-key routes, `POST /spaces`, `GET /spaces/{id}`, `GET /spaces/{id}/members`, `POST /spaces/{id}/invitations`, `POST /invitations/{token}/accept`, and deterministic space-created default seeds | DB-persisted API-key storage until the canonical schema adds an `api_keys` table; schema migrations |
| Providers/credentials | Provider reads, commands, invocation, API-key credential pools, CLI credential login/broker/audit, internal provider/credential ports | Schema migrations |
| Runtime adapters | `RuntimeAdapterSpec` catalog, adapter-type semantics, TS runtime-host/tool integration | Python runtime adapter implementations still used by Python-owned execution paths |
| Agents | Agent CRUD (`/agents*`), current-version/version list/read/restore, config updates as immutable `agent_versions`, default Assistant ensure/read, Assistant settings, and agent-scoped run list/read subresources | Agent templates and create-from-template routes until the template factory is ported |
| Runs | Run creation via agent subresources, top-level run list/detail/status/trace, execute/stop commands, internal execute port, deterministic post-run evaluation/finalization, `agent_run` worker dispatch, run execution evidence writes, native context.prepare consumption, and TS worktree/ephemeral sandbox preparation for CLI runs | Run activity/proposal child read surfaces |
| Jobs / schedulers | Generic durable `jobs` queue (`/jobs*`), unified worker registry (`agent_run`, `memory_consolidation`, `daily_capture_report`), in-process schedulers (daily capture report, automation, memory access-log retention, intake extraction polling, backup), stuck-job reclaim, stale running-run recovery at worker startup, and non-overlapping scheduler task execution | — |
| Automations | `/spaces/{id}/automations*`, schedule/manual fire with policy preflight, automation run records | — |
| Daily capture report | `/daily-capture-report/*` settings, manual run, report listing, scheduler enqueue of `daily_capture_report` jobs | — |
| Backups | `/system/backups` list/manual trigger, scheduled backup ticks, prod backup policy guard, and backup lock/stale-lock handling | — |
| Policy | Sensitive-action enforcement, proposal-apply policy gate, durable policy audit | Python callers use the TS authority through `PolicyPort` |
| Proposals | External proposal review/read routes, accept/reject/egress-approval commands, proposal-apply orchestration, and the TS applier registry for registered memory and knowledge types | Target-module appliers that have not migrated; unregistered proposal types fail closed |
| Sessions | Public list/get/create session commands, list/add messages, latest-summary read | `reflect`, summary condense/create writes |
| Assistant chat | External Personal Assistant chat turn orchestration and queued run creation for TS context chat turns | — (candidate reads are now native TS) |
| Context | Native chat-path candidate collection (`modules/context`: memory/knowledge/source/activity reads), budget/dedup loop, selected-item snapshot persistence, full-run context package assembly, context evidence selection/`used_in_context` link recording for existing evidence, memory context-injection logs, `context_snapshots` population, and vendor runtime file rendering to sandboxes | Digest refresh jobs |
| Memory read/write boundary | `/memory` list/get/search, read-access logging, public memory create/update/archive proposal creation, batch activity consolidation via `POST /memory/consolidation/run` | Memory quality/evolution jobs (digest refresh, evolver, source-monitoring producers) |
| Memory apply | Accepted `memory_create` / `memory_update` / `memory_archive` apply after the TS proposal-apply policy gate | Personal-memory egress-context placement, active-policy private-placement overlay, workspace/agent-scope digest invalidation |
| Activity | DB-backed `/activity*` capture/list/detail/upload/review/archive, per-activity consolidation, and summary artifact/proposal creation with activity/evidence/intake provenance | LLM summarization quality parity with Python classifier pipeline |
| Intake | DB-backed `/intake*` connector/connection config, manual URL intake, extraction-job audit records, candidate evidence/evidence links, workspace intake profiles/bindings, summary artifact/proposal creation, and in-process extraction polling | External fetch fidelity beyond the current TS extraction worker |
| Knowledge | DB-backed `/knowledge*` item proposal routes, source/note/entity-link CRUD, item/source links, relation proposals, and TS knowledge proposal appliers | Schema migrations and any not-yet-ported background knowledge quality jobs |
| Tasks | DB-backed `/tasks*`, `/boards*`, and `/me/tasks` boards/tasks CRUD, queued Run creation through `task_runs`, task artifacts/proposals reads, task evaluations, and the run-finalization → task-evaluation bridge | Worker execution itself remains owned by Runs/runtime |
| Artifacts | Client-facing `GET /artifacts`, `GET /artifacts/{id}`, and `GET /artifacts/{id}/export` routes, including scoped visibility checks and managed-storage export path guards | Artifact production for Python-owned run paths |
| Workspaces / sandbox | DB-backed `/workspaces*`, workspace-console read routes, runtime status/session stubs, PathPolicy, workspace read policy audit, TS worktree prepare/cleanup, sandbox GC, worktree code_patch collection, and accepted `code_patch` proposal apply through `workspace.write_patch` | Workspace-console session execution writes remain feature-not-implemented |
| Deployment | TS-owned `/deployments/jobs*` edge routes, core deployer socket client, and job-type allowlist for `rebuild_agent_space`, `restart_agent_space`, and `health_check` | Deployer remains a separate host/sidecar process; deployment job persistence/proposal flow remains deferred because the current API is a feature-not-implemented stub |

The active route-registered control-plane modules are: `system`, `auth`,
`spaces`, `catalog`, `streaming`, `notifications`, `runtimeTools`,
`providers`, `runtimeHost`, `runs`, `policy`, `proposals`, `sessions`,
`agents`, `memory`, `activity`, `intake`, `knowledge`, `tasks`, `workspaces`,
`artifacts`, `jobs`, `automations`, `dailyReports`, `backups`, `deployment`,
and `frontendSupport`.
`runtimeAdapters` is a first-class code-only domain consumed by `runs`,
`runtimeHost`, and `runtimeTools`; `context` is a code-only domain consumed by
`agents` and `runs`.

## Python-Owned Boundaries

These are intentional Python authority today:

- DB-persisted API-key storage; the TS API-key routes return the canonical
  feature-gated response while the schema has no `api_keys` table;
- schema migrations and DDL;
- run activity/proposal child read surfaces;
- artifact production for Python-owned run paths;
- session reflection and summary creation;
- memory digest refresh, evolver, source-monitoring producers, and quality loops;
- non-memory/non-knowledge/non-task/non-code-patch proposal target appliers;
- deployer host/sidecar process internals and deferred deployment job persistence.

## Guards

Old Python command paths fail closed when TS owns the command:

- public session commands: `backend/app/sessions/authority.py`;
- public chat turns and retired combined chat prepare-run port:
  `backend/app/agents/authority.py`;
- public memory read/proposal-create and TS-owned memory apply type detection:
  `backend/app/memory/authority.py`;
- generic Python proposal accept for TS-owned memory proposal types:
  `backend/app/proposals/internal_api.py`.

## Operational Notes

The least-privilege control-plane DB role is provisioned by
`ops/scripts/lib/local-compose.sh`. Fixed TS foundations (auth/spaces,
providers/credentials, policy, sessions, runs, jobs/schedulers, automations,
daily reports, agents, chat, context, memory read/proposal-create/apply/consolidation,
proposals, artifacts, workspaces/sandbox, deployment edge, and leaf domains) always get their required
grants. Keep the detailed grants in code/tests, not in architecture prose.

Control-plane DB connections and transactions are centralized in
`control-plane/src/db/`. The TS migration runner and frozen baseline under
`control-plane/migrations/` exist for parity and future cutover work; they are
not wired into service startup and do not replace Python/Alembic as the current
runtime schema owner.

Focused verification commands are listed in [`../COMMANDS.md`](../COMMANDS.md).
