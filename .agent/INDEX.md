# Agent Context Index

## What This Project Is

`agent-space` is a space-based, multi-user, agent-first memory and knowledge system.
It manages personal, family, and team spaces in a single deployment instance.
Agents run tasks, generate proposals, and surface context — humans approve what becomes permanent.

## Read This First

1. [ARCHITECTURE.md](ARCHITECTURE.md) — layer map; know where a feature belongs
2. [BOUNDARIES.md](BOUNDARIES.md) — rules that must not be violated
3. [COMMANDS.md](COMMANDS.md) — how to run, test, and build
4. [tasks/current-focus.md](tasks/current-focus.md) — current priorities and non-goals
5. [WORKING_TIPS.md](WORKING_TIPS.md) — practical gotchas discovered during development

## Module Docs

Load only the modules relevant to your task.

| Task area | Module doc |
|---|---|
| Space / user / workspace data model | [modules/space.md](modules/space.md) |
| Agent profiles, adapters, runs | [modules/agents.md](modules/agents.md) |
| Long-term memory | [modules/memory.md](modules/memory.md) |
| Raw input and event capture | [modules/activity.md](modules/activity.md) |
| Activity inbox UI and quick capture | [modules/activity-inbox.md](modules/activity-inbox.md) |
| Policy and permission engine | [modules/policy.md](modules/policy.md) |
| Proposal / approval system | [modules/proposals.md](modules/proposals.md) |
| Capability lifecycle | [modules/capability.md](modules/capability.md) |
| Context assembly and vendor files | [modules/context-compiler.md](modules/context-compiler.md) |
| Sandbox execution | [modules/sandbox.md](modules/sandbox.md) |
| Workspace browser / file UI | [modules/workspace-console.md](modules/workspace-console.md) |
| Personal assistant and capture | [modules/assistant-capture.md](modules/assistant-capture.md) |
| Structured knowledge / wiki | [modules/llm-wiki.md](modules/llm-wiki.md) |
| Spaced repetition / cards | [modules/spaced-repetition.md](modules/spaced-repetition.md) |
| Rich media cards (image occlusion, audio) | [modules/media-cards.md](modules/media-cards.md) |
| Product shell and navigation chrome | [modules/product-shell.md](modules/product-shell.md) |
| Multi-panel frontend layout | [modules/frontend-layout.md](modules/frontend-layout.md) |
| Memory review and governance UI | [modules/memory-review.md](modules/memory-review.md) |
| Server / runtime status UI | [modules/server-status.md](modules/server-status.md) |
| Git diff review and approval UI | [modules/git-diff-review.md](modules/git-diff-review.md) |
| Sync strategy and conflict resolution | [modules/sync-and-conflicts.md](modules/sync-and-conflicts.md) |
| REST API, WebSocket, SSE protocol | [modules/client-server-protocol.md](modules/client-server-protocol.md) |
| Mobile PWA client | [modules/mobile-client.md](modules/mobile-client.md) |

## Decision Records

Load when you need to understand why something is the way it is.

| ADR | Summary |
|---|---|
| [0001](decisions/0001-space-model.md) | Space as product-level isolation boundary |
| [0002](decisions/0002-agent-model.md) | Agent is a separate model from User |
| [0003](decisions/0003-memory-proposal-flow.md) | Agents do not directly write active memory |
| [0004](decisions/0004-context-wrapper.md) | Vendor files are generated adapters, not source of truth |
| [0005](decisions/0005-desktop-runtime.md) | Windows desktop is not a full runtime |
| [0006](decisions/0006-open-source-readiness.md) | Private-first, open-source-ready |
| [0007](decisions/0007-plugin-module-architecture.md) | Plugin module structure for per-deployment feature control |

## Source of Truth

- **Code** — implementation truth; always wins over docs
- **models.py** — canonical data model (`core/backend/app/models.py`)
- **schemas.py** — API contracts (`core/backend/app/schemas.py`)
- **app/modules/registry.py** — which backend modules and routes are active
- **src/modules/registry.js** — which frontend modules and nav items are active
- **.agent/BOUNDARIES.md** — architectural invariants
- **.agent/decisions/** — accepted decisions

## Important Rules for AI Agents

- Do not load all docs for every task. Use the smallest relevant bundle.
- Check [context-bundles.yaml](context-bundles.yaml) for task-type → doc mappings.
- Never write to `instance/` from code in `core/`.
- Never write active memory directly — use proposals.
- Never write vendor context files to the real workspace — write to sandbox only.
- Read BOUNDARIES.md before making structural changes.
- New module routes go in `app/<module>/api.py`, not `app/api/`. Register in `app/modules/registry.py`.
- New frontend pages go in `src/modules/<module>/`, not `src/pages/`. Register in `src/modules/registry.js`.
