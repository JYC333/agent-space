# AGENTS.md

Repository instructions for Codex. This file is intentionally short: it routes
Codex to the `.agent/` source-of-truth docs instead of duplicating them.

## Required Context

Before making code or architecture changes:

1. Read [`.agent/INDEX.md`](.agent/INDEX.md).
2. Pick the smallest relevant bundle from
   [`.agent/context-bundles.yaml`](.agent/context-bundles.yaml).
3. Read [`.agent/BOUNDARIES.md`](.agent/BOUNDARIES.md) before structural,
   ownership, security, policy, data-model, or migration changes.
4. Read [`.agent/architecture/TESTING_STRATEGY.md`](.agent/architecture/TESTING_STRATEGY.md)
   before adding or changing tests.
5. Use [`.agent/COMMANDS.md`](.agent/COMMANDS.md) for canonical run, build,
   test, migration, backup, and compose commands.

Do not load every `.agent/` document by default. Load only what the task needs.

## Source Of Truth

Follow this order when docs and code disagree:

1. Code
2. `server/migrations/`
3. `server/src/`
4. `packages/protocol/src/`
5. `apps/web/src/modules/registry.ts`
6. [`.agent/BOUNDARIES.md`](.agent/BOUNDARIES.md)
7. [`.agent/decisions/`](.agent/decisions/)

Docs in `.agent/architecture/` describe current state. When an architecture
change lands, update the relevant `.agent/architecture/` document in the same
change.

## Repo Rules

- Runtime data, user workspaces, sandboxes, secrets, database files, and logs
  must never be stored in the source repo.
- `ASPACE_ROOT` is the host-side parent for mode roots (`dev/`, `test/`,
  `prod/`). `AGENT_SPACE_HOME` is the running app instance root.
- `server/` is the TypeScript backend source root and explicit schema migration
  owner. The Compose service name remains `server`.
- Memory writes go through proposal -> approval; agents do not directly write
  active memory.
- Credentials follow ADR 0010 channel isolation. Do not pass provider API keys
  through ambient env or CLI subprocess env.
- `.agent/reports/` entries are temporary reports, not source of truth.

## Working Pattern

- Read the relevant docs first, then the code.
- Keep changes scoped to the requested module/context.
- Prefer small, purpose-specific modules over large catch-all files. Before
  adding substantial behavior to an already large file, scan nearby file sizes
  and split along existing ownership boundaries when the extraction is low
  risk.
- Add or update focused tests when behavior changes.
- Use the smallest verification command that proves the change; broaden only
  when the blast radius requires it.
