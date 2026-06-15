# TypeScript Migration Strategy

> **Status:** binding migration rules. Current ownership is recorded in
> [`TS_CONTROL_PLANE_OWNERSHIP.md`](TS_CONTROL_PLANE_OWNERSHIP.md); roadmap and
> future backlog are recorded in
> [`TS_MIGRATION_ROADMAP.md`](TS_MIGRATION_ROADMAP.md).

## Position

The control plane is the default client-facing API entrypoint. Python remains
the authority for every context and command not explicitly moved to a
control-plane module.

This document does not authorize any new ownership move. It defines the rules
for doing one safely.

## Binding Rules

1. **One command, one authority.** A route or command is decided by Python or
   TypeScript, never both. Shadow comparisons are read-only.
2. **Migrate by bounded context or command.** Do not translate files one by one
   across the language boundary.
3. **Add a seam before moving authority.** A context needs a facade, port, or
   explicit internal protocol before a TS implementation can replace it.
4. **Keep credential-channel isolation.** Provider API keys and CLI credentials
   move only through their sanctioned broker channels; no ambient env-key
   fallback.
5. **Keep proposal/activity boundaries.** TS code does not get a side door into
   active memory, knowledge, artifacts, or workspace mutation.
6. **Keep least privilege.** The control-plane DB role gets only the table and
   column permissions needed by TS-owned contexts.
7. **Retire or guard the old path.** When TS owns a command, the Python route is
   removed, guarded fail-closed, or converted into a thin caller of the TS
   authority.

## Context Move Checklist

Before flipping a context or command to TS:

1. Existing Python behavior is covered by focused tests or parity fixtures.
2. The shared wire contract lives in `packages/protocol` when the boundary is
   cross-process or shared by both languages.
3. The TS module is registered explicitly in the control-plane route registry.
4. The DB role grants are scoped to the moved slice only.
5. Env templates and compose files pass the authority switch to both backend and
   control-plane when both need to see it.
6. Python fallback no longer serves the moved route.
7. Docs list the new owner in
   [`TS_CONTROL_PLANE_OWNERSHIP.md`](TS_CONTROL_PLANE_OWNERSHIP.md).

## What Is Not Migration

Future runtime/product capabilities should be tracked as new feature work, not
as migration blockers. Examples include the full context engine, channel
adapters, Always-On triggers, self-hosted TS agent loop, tool scheduler, MCP,
managed API with tools, and the CLI sandbox scope ladder.
