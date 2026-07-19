# Protocol Foundation

> **Status:** current repository fact. Source of truth is
> `packages/protocol/`. This package is contracts-only; it moves no backend
> authority by itself.

## Purpose

`packages/protocol` is the shared contract package for DTOs, command
envelopes, events, internal server boundary payloads, and shared contract value
sets.

It exists so server and client consumers validate the same shapes at runtime and compile time
instead of re-deriving API payloads in multiple places.

## Frontend Contract Boundary

`apps/web/src/types/api.ts` still contains local client API types and view-facing
shapes. That is acceptable as an intermediate state, but it is a long-term drift
risk because `packages/protocol` is the shared wire-contract package.

Move or align DTOs into `packages/protocol` when they are stable server/client
wire contracts that benefit from shared Zod validation and compile-time reuse.
Keep web-only screen state, form state, UI rollups, and presentation view models
inside `apps/web`. Do not bulk-move the entire web `types/api.ts` file into
`packages/protocol`; that would turn the protocol package into a frontend UI type
bucket and weaken its contracts-only role.

## What It Owns

- Conservative DTO schemas for existing API shapes.
- Command/event envelope schemas.
- Provider, credential, runtime-host, policy, proposal, runs, memory, and
  session contracts used by server modules.
- Source Provider, Source Connector, Provider–Connector Mapping, and Source
  Channel contracts. Public Source contracts expose Provider and
  Channel configuration; Connector implementation metadata is an Instance
  Admin/catalog concern.
- Common primitives and exported value sets.
- Shared contracts only when the shape is a server/client or internal server
  boundary, not a purely local web view model.
  Provider-specific preset taxonomies and connector UI metadata stay with the
  owning module, not in `packages/protocol`.


Field names use the public API's `snake_case` JSON convention. Types are derived from
Zod schemas, so runtime validators and TypeScript types stay together.

## What It Does Not Own

- No handlers, routes, persistence, transport, or event bus.
- No auth, policy, proposal application, memory writes, runtime execution, or
  credential release decisions.
- No product model invention beyond conservative contracts for existing
  surfaces.

Authority belongs to the route-owning service recorded in
[`SERVER_OWNERSHIP.md`](SERVER_OWNERSHIP.md), not to this
package.

## Verification

Use the package-local commands when protocol contracts change:

```bash
cd packages/protocol
npm run typecheck
npm test
npm run build
```
