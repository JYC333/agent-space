# Module: Space

## Purpose
Product-level isolation boundary. Every piece of data lives inside a space. Enables personal, household, and team deployments from a single instance.

## Owns
- `Space` ORM model (space_id, name, type)
- `SpaceMembership` (user ↔ space relationship, role)
- `Workspace` ORM model (workspace_id, space_id, name, type, path)
- `WorkspaceMembership` (user ↔ workspace relationship)
- All `space_id` scoping enforcement at the data layer

## Does Not Own
- User identity (users are referenced by string ID only — no User ORM model by design)
- Memory content (memory module)
- Agent definitions (agents module)

## Key Models

```
Space: id, name, type (personal|household|team), created_at
SpaceMembership: id, space_id, user_id, role, status
Workspace: id, space_id, created_by, name, description, type, status, path
WorkspaceMembership: id, workspace_id, user_id, role
```

## Main Flows
- On first run, bootstrap seeds the default owner's personal space (a generated UUID, located by owner membership — no fixed/magic space id)
- All API calls include `space_id` (from session / header / default)
- ContextBuilder requires `space_id` and raises if missing

## Invariants
- Every core data record must carry `space_id`
- Data from space A must never appear in context built for space B
- One deployment instance hosts many spaces — never create one instance per space

## Related Files
- `server/migrations/` — Space, SpaceMembership, Workspace, WorkspaceMembership
- `packages/protocol/src/` — shared workspace/space DTOs when exported
- `server/src/config.ts` — bootstrap/default config
- `server/src/modules/spaces/` — default space and membership routes
- `server/src/modules/context/` — context assembly with space boundary enforcement

## Related Decisions
- [0001-space-model.md](../decisions/0001-space-model.md)
