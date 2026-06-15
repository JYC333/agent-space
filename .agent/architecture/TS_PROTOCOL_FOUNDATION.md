# TS Protocol Foundation

> **Status:** current repository fact. Source of truth is
> `packages/protocol/`. This package is contracts-only; it moves no backend
> authority by itself.

## Purpose

`packages/protocol` is the shared TypeScript contract package for DTOs, command
envelopes, events, and internal control-plane/Python boundary payloads.

It exists so TS consumers validate the same shapes at runtime and compile time
instead of re-deriving Python API payloads in multiple places.

## What It Owns

- Conservative DTO schemas for existing API shapes.
- Command/event envelope schemas.
- Provider, credential, runtime-host, policy, proposal, runs, memory, and
  session migration contracts used by control-plane modules and Python ports.
- Common primitives and exported value sets.

Field names mirror public Python JSON (`snake_case`). Types are derived from
Zod schemas, so runtime validators and TypeScript types stay together.

## What It Does Not Own

- No handlers, routes, persistence, transport, or event bus.
- No auth, policy, proposal application, memory writes, runtime execution, or
  credential release decisions.
- No product model invention beyond conservative contracts for existing or
  explicitly migrated surfaces.

Authority belongs to the route-owning service recorded in
[`TS_CONTROL_PLANE_OWNERSHIP.md`](TS_CONTROL_PLANE_OWNERSHIP.md), not to this
package.

## Verification

Use the package-local commands when protocol contracts change:

```bash
cd packages/protocol
npm run typecheck
npm test
npm run build
```
