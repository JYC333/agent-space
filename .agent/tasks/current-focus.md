# Current Focus

The system is ready for personal, family/shared-space, and team/workspace dogfooding.
All durable-data API routes are authenticated and space-scoped. Session, task, activity,
and agent boundaries have full test coverage (1127 tests passing). See
[architecture/SECURITY_AND_ACCESS_BOUNDARIES.md](architecture/SECURITY_AND_ACCESS_BOUNDARIES.md)
for the current security boundary reference.

## Priorities

- Incident collection and feedback from real dogfooding use
- Frontend/backend type contract alignment (memory proposals, workspace fields, space type)
- Artifact archive/delete API
- Activity archive/delete
- Workspace stale recovery UI
- Additional persisted policy enforcement classes beyond `memory.write_direct`

## Non-Goals (Today)

- Reintroducing singular `/tasks/{id}/run` routes or product Task = Job shortcuts
- Synthetic runtime fallbacks in production execution paths
- Information Horizon ingestion before Activity/Source/Evidence provenance is stable
- Self-evolution before evaluation gates and deployment job persistence exist

## Quick Links

- [../ARCHITECTURE.md](../ARCHITECTURE.md)
- [../BOUNDARIES.md](../BOUNDARIES.md)
- [../COMMANDS.md](../COMMANDS.md)
- [../architecture/NON_GOALS_AND_DISABLED_SURFACES.md](../architecture/NON_GOALS_AND_DISABLED_SURFACES.md)
- [../architecture/ROADMAP_AND_FUTURE_RISKS.md](../architecture/ROADMAP_AND_FUTURE_RISKS.md)
