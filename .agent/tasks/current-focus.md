# Current Focus

The system is ready for first personal dogfooding. The next work should validate the real
product loop: capture → activity → proposal/review → memory/task → continue working. Fix
only concrete friction discovered during use.

## Priorities

- Use the system with real captures, activities, proposals, runs, and memory/task outputs.
- Collect real friction from the product loop and fix concrete blockers as discovered.
- Frontend/backend type contract alignment (memory proposals, workspace fields, space type).
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
