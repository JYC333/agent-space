# TS Control-Plane Ownership

> **Status:** current repository fact, refreshed 2026-06-15. Code remains the
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
| Providers/credentials | Provider reads, commands, invocation, API-key credential pools, CLI credential login/broker/audit, internal provider/credential ports | Auth/membership introspection; schema migrations |
| Runs | Execute/stop commands, internal execute port, `agent_run` worker, run execution evidence writes | Run creation, read/finalization surfaces, artifacts, non-`agent_run` jobs, `context.prepare` |
| Policy | Sensitive-action enforcement, proposal-apply policy gate, durable policy audit | Python callers use the TS authority through `PolicyPort` |
| Proposals | External proposal review/read routes | Non-memory apply business logic and target-module appliers that have not migrated |
| Sessions | Public list/get/create session commands, list/add messages, latest-summary read | `reflect`, summary condense/create writes |
| Assistant chat | External Personal Assistant chat turn orchestration | Candidate reads and run creation cross explicit Python ports |
| Chat context | Chat-path budget/dedup loop, selected-item snapshot persistence | Full run `ContextBuilder`, `ContextSnapshotPopulator`, `ContextCompiler`, context injection logs |
| Memory read/write boundary | `/memory` list/get/search, read-access logging, public memory create/update/archive proposal creation | Memory quality/evolution jobs |
| Memory apply | Accepted `memory_create` / `memory_update` / `memory_archive` apply after Python gate validation | Personal-memory egress guard handling, active-policy private-placement overlay, workspace/agent-scope digest invalidation |

The active control-plane modules are: `system`, `catalog`, `streaming`,
`notifications`, `runtimeTools`, `providers`, `runtimeHost`, `runs`, `policy`,
`proposals`, `sessions`, `agents`, `memory`, and `frontendSupport`.

## Python-Owned Boundaries

These are intentional Python authority today:

- auth/membership and identity introspection;
- schema migrations and DDL;
- run creation/read/finalization surfaces;
- artifact storage/export and artifact egress guards;
- full run context preparation and vendor context-file rendering;
- non-`agent_run` jobs and schedulers;
- session reflection and summary creation;
- memory consolidation, source-monitoring producers, digest refresh, evolver,
  and quality loops;
- non-memory proposal target appliers;
- activity, knowledge, tasks, workspace write flows, and deployment.

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
`ops/scripts/lib/local-compose.sh` according to active authority switches. Keep
the detailed grants in code/tests, not in architecture prose.

Focused verification commands are listed in [`../COMMANDS.md`](../COMMANDS.md).

