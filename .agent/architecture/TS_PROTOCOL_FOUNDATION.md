# TS Protocol Foundation — `packages/protocol`

> **Status:** describes the first TypeScript artifact in the repo, added 2026-06-09.
> Source of truth is the code under `packages/protocol/`. Companion:
> [`TS_MIGRATION_STRATEGY.md`](TS_MIGRATION_STRATEGY.md) (Phase 1).

## Why this package exists

A future TS surface (web, desktop, mobile, a TS gateway, and — much later —
server-side migration modules) will need a **single, framework-free definition of
the data shapes and message contracts** it exchanges with the Python backend.
Without one, each consumer re-derives DTOs and drifts. `packages/protocol` is that
shared definition: one place where a `RunDTO`, a `StartRun` command, or a
`RunStatusChanged` event is described, with both a compile-time type and a runtime
(Zod) validator derived from the same schema.

It is deliberately the *smallest possible* first step. It moves **no** authority.

## What it owns

- **DTOs** — conservative TS shapes mirroring the Python API `*Out` models
  (`SpaceRef`, `UserRef`, `AgentRef`, `WorkspaceRef`, `ProjectRef`, `ActivityDTO`,
  `ProposalDTO`, `RunDTO`, `RunEventDTO`, `ArtifactDTO`, `MemoryDTO`,
  `KnowledgeItemDTO`).
- **Command contracts** — envelope + payload *schemas* for `CreateCapture`,
  `ProcessActivity`, `ApproveProposal`, `RejectProposal`, `StartRun`.
- **Event contracts** — envelope + payload *schemas* for `ActivityCreated`,
  `ProposalCreated`, `ProposalStatusChanged`, `RunStatusChanged`,
  `RunEventAppended`, `ArtifactCreated`, `MemoryChanged`.
- **Primitives** — `Id`, `ISODateTime`, documented value sets (`VISIBILITY_VALUES`,
  `SPACE_TYPE_VALUES`) and a `PROTOCOL_VERSION`.

Field naming mirrors the Python JSON (**snake_case**) so the schemas parse real
API payloads without a translation layer. Coded string fields (status / type /
visibility) are intentionally **permissive** (`z.string()`) so the protocol never
rejects a value the server adds later; known value sets are exported as `const`
arrays + guards for consumers that want them.

The Zod schemas in `src/schemas.ts` are the single source of truth; the DTO types
in `src/dto.ts` are `z.infer`-derived, so type and validator cannot drift.

## What it must NOT own

- **No handlers.** Commands are *contracts*, not executable operations. There is
  no code here that performs a capture, approves a proposal, or starts a run.
- **No event bus.** Events are *contracts*, not a publish/subscribe system. There
  is no emitter, transport, or dispatcher.
- **No transport / no routing to Python.** This package does not call the API,
  open a socket, or know a server URL.
- **No framework, backend, database, or runtime dependencies.** Its only runtime
  dependency is `zod`. A `test/boundaries.test.ts` guard fails CI if any source
  file imports anything other than `zod` or a relative module.
- **No product model invention.** DTOs are conservative subsets of existing
  Python `*Out` models; this package does not define new domain concepts.

## Authority

**Python remains the sole authority** for every command and every write. A command
envelope is a *description of a request*; the backend still authenticates,
authorizes (policy gateway / hard invariants), decides, and applies it. The
`command_id` is a client idempotency hint, not a grant of authority. The protocol
package is **not a backend** — it has no state, no DB, no decisions.

## Package shape

```
packages/protocol/
  package.json        # @agent-space/protocol — deps: zod; dev: typescript, vitest, @types/node
  tsconfig.json       # strict, ES2020, bundler resolution, noEmit (typecheck only)
  vitest.config.ts    # node environment
  src/
    index.ts          # single public entry — re-exports everything
    common.ts         # Id, ISODateTime, value sets, PROTOCOL_VERSION
    schemas.ts        # Zod schemas — source of truth for DTO shapes
    dto.ts            # z.infer DTO types
    commands.ts       # command envelopes (contracts only)
    events.ts         # event envelopes (contracts only)
  test/
    index.test.ts     # import smoke + type-level (expectTypeOf) checks
    schemas.test.ts   # DTO parse / reject validation
    commands.test.ts  # command parse + discriminated-union routing
    events.test.ts    # event parse + discriminated-union routing
    boundaries.test.ts# import-boundary guard (zod + relative only)
```

### Running it

The repo has no root `package.json` / workspace, so the package is self-contained
and uses the repo's existing package manager (**npm**):

```bash
cd packages/protocol
npm install
npm run typecheck   # tsc --noEmit
npm test            # vitest run
```

## Future consumers (not built here)

- **Web frontend** (`apps/web/`) — can adopt these DTOs/types incrementally.
- **Desktop / mobile** — future clients reuse the same contracts.
- **TS gateway** — a future proxy/read-model layer would speak this protocol.
- **Server-side migration modules** — if/when a bounded context migrates, it
  binds to these contracts.

**No local-host, gateway, desktop, mobile, plugin, MCP, or CLI-runner code is part
of this phase.** This package is types and schemas only.
