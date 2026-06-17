# Current Focus

The system is ready for first personal dogfooding. The next work should validate the real
product loop: capture → activity → proposal/review → memory/task → continue working. Fix
only concrete friction discovered during use.

## Dogfooding Focus

The server is now the only app backend. Current ownership and deferred surfaces
live in [../architecture/SERVER_OWNERSHIP.md](../architecture/SERVER_OWNERSHIP.md).

New product work targets the server. No-prod posture: rollback is
fix-forward / `git revert`.

**Current focus:** dogfood the backend and run a post-cutover audit against
current code facts. Keep route/module docs, frontend contracts, and deferred
fail-closed surfaces aligned with the TypeScript server. Migrations are explicit
ops commands, not automatic service startup behavior.

Do not reopen a broad migration refactor or create competing temporary reports
for inventory/gap analysis. Durable facts belong in `.agent/architecture/` and
module docs; one-off findings under `.agent/reports/` should be deleted after
consolidation.

## Priorities

- Use the system with real captures, activities, proposals, runs, and memory/task outputs.
- Collect real friction from the product loop and fix concrete blockers as discovered.
- Keep `server/src/gateway/routeRegistry.ts`, `server/src/modules/`, and
  `.agent/architecture/MODULES.md` synchronized.
- Frontend/backend type contract alignment (memory proposals, workspace fields, space type).
- Home command center improvements should consume server aggregate read models
  (`/api/v1/me/*`, `/api/v1/home/summary`) instead of fanning out across every
  domain API.
- Keep explicit deferred/fail-closed surfaces visible in source docs so they are
  not misread as cutover failures.
- Source cleanup: remove or update stale Python/control-plane/backend-migration
  references when found, without big-bang rewrites.
- Artifact archive/delete API.
- Activity archive/delete.
- Workspace stale recovery UI.

## Non-Goals (Today)

- Reintroducing singular `/tasks/{id}/run` routes or product Task = Job shortcuts
- Synthetic runtime fallbacks in production execution paths
- Broad automated intake/connectors before Intake/Evidence provenance and proposal boundaries are stable
- Self-evolution before evaluation gates and deployment job persistence exist

## Quick Links

- [../ARCHITECTURE.md](../ARCHITECTURE.md)
- [../BOUNDARIES.md](../BOUNDARIES.md)
- [../COMMANDS.md](../COMMANDS.md)
- [../architecture/FRONTEND_INFORMATION_ARCHITECTURE.md](../architecture/FRONTEND_INFORMATION_ARCHITECTURE.md)
- [../architecture/NON_GOALS_AND_DISABLED_SURFACES.md](../architecture/NON_GOALS_AND_DISABLED_SURFACES.md)
- [../architecture/ROADMAP_AND_FUTURE_RISKS.md](../architecture/ROADMAP_AND_FUTURE_RISKS.md)
