# Decision 0001: Space as Product-Level Isolation Boundary

## Status
Accepted

## Context
The system needed a top-level isolation model that could serve personal users, households, and small teams from a single deployment. Options considered:
- Personal-only (one user = one installation)
- Tenant model (enterprise multi-tenancy with complex ACLs)
- Space model (product-level containers with flexible membership)

## Decision
Use **Space** as the product-level container instead of personal-only or tenant-only terminology.

A Space:
- Is the primary isolation boundary for all data
- Has a type: `personal`, `household`, or `team`
- Has an owner and members (via SpaceMembership)
- Contains workspaces, agents, memories, sessions, tasks, and runs
- Has its own policy configuration

## Consequences

- All core data records carry `space_id` — required, never optional
- One deployment instance hosts many spaces — do not create one instance per space
- ContextBuilder refuses to build context without an explicit `space_id`
- The term "tenant" is avoided — spaces are product-level, not infra-level
- Users can belong to multiple spaces (via SpaceMembership)
- Workspaces belong to spaces, not users
- Data from space A must never appear in context built for space B
