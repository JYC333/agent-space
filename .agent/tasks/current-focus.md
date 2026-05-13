# Current focus

The backend and frontend now share a single Run-centric execution model with Alembic-backed schema, task board linkage, and real runtime adapters behind policy.

## Priorities

- Keep Run/Task/home surfaces aligned with `BOUNDARIES.md`
- Finish persistence gaps that still return HTTP 501 (workspace console sessions, API keys, deployment jobs)
- Expand automated tests around sandbox + adapter failure modes

## Non-goals (today)

- Reintroducing singular `/tasks/{id}/run` routes or product Task = Job shortcuts
- Synthetic runtime fallbacks in production execution paths

## Quick links

- [../ARCHITECTURE.md](../ARCHITECTURE.md)
- [../BOUNDARIES.md](../BOUNDARIES.md)
- [../COMMANDS.md](../COMMANDS.md)
