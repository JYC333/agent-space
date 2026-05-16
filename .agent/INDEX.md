# Agent Context Index

## What This Project Is

Agent-Space is a local-first personal/household agent operating system and human-agent collaboration control plane. It manages personal, family, and team spaces in a single deployment. Agents run tasks, generate proposals, and surface context — humans approve what becomes permanent.

## Source of Truth Hierarchy

1. **Code** — implementation truth; always wins over docs.
2. **`models.py`** — canonical data model (`core/backend/app/models.py`).
3. **`schemas.py`** — API contracts (`core/backend/app/schemas.py`).
4. **`app/modules/registry.py`** — which backend modules and routes are active.
5. **`src/modules/registry.js`** — which frontend modules and nav items are active.
6. **`.agent/BOUNDARIES.md`** — architectural invariants (load for any structural change).
7. **`.agent/decisions/`** — accepted architectural decisions.

Docs in `.agent/architecture/` are **current-state architecture references**, not target-state speculation. Do not treat them as implementation specs without a separate scoped implementation task.

## Read First

1. [BOUNDARIES.md](BOUNDARIES.md) — rules that must not be violated
2. [ARCHITECTURE.md](ARCHITECTURE.md) — layer map; know where a feature belongs
3. [COMMANDS.md](COMMANDS.md) — how to run, test, and build
4. [tasks/current-focus.md](tasks/current-focus.md) — current priorities
5. [WORKING_TIPS.md](WORKING_TIPS.md) — practical gotchas

## Architecture References

| Doc | What it covers |
|---|---|
| [architecture/PRODUCT_AND_BOUNDARIES.md](architecture/PRODUCT_AND_BOUNDARIES.md) | Product identity, current enforcement points, architecture fitness checks |
| [architecture/EXECUTION_MODEL.md](architecture/EXECUTION_MODEL.md) | Run, RunStep, Job, Artifact, Proposal, actor identity, credential resolver |
| [architecture/MEMORY_ACTIVITY_PROVENANCE.md](architecture/MEMORY_ACTIVITY_PROVENANCE.md) | Activity-first capture, provenance chain, trust gate, memory write boundaries |
| [architecture/DATABASE_AND_TRANSACTIONS.md](architecture/DATABASE_AND_TRANSACTIONS.md) | UnitOfWork, transaction ownership, external call boundary, SQLite/Postgres rules |
| [architecture/OPERATIONS_AND_SAFETY.md](architecture/OPERATIONS_AND_SAFETY.md) | Backup, restore, lifecycle states, deployment boundary, stop conditions |
| [architecture/NON_GOALS_AND_DISABLED_SURFACES.md](architecture/NON_GOALS_AND_DISABLED_SURFACES.md) | Disabled surfaces, current allowed surfaces, non-goals |
| [architecture/ROADMAP_AND_FUTURE_RISKS.md](architecture/ROADMAP_AND_FUTURE_RISKS.md) | Capability line roadmap, future risks |
| [architecture/MEMORY_MODEL.md](architecture/MEMORY_MODEL.md) | Memory scopes, visibility, access control |
| [architecture/PROPOSALS.md](architecture/PROPOSALS.md) | Proposal types, lifecycle, apply flow |
| [architecture/TASK_BOARD_MODEL.md](architecture/TASK_BOARD_MODEL.md) | Tasks, runs, jobs |
| [architecture/RUNS_AND_OUTPUTS.md](architecture/RUNS_AND_OUTPUTS.md) | Run outputs, materialization, boundaries |
| [architecture/ARTIFACTS.md](architecture/ARTIFACTS.md) | Artifact lifecycle and export |
| [architecture/TESTING_STRATEGY.md](architecture/TESTING_STRATEGY.md) | Test layers and product invariant philosophy |

## Operational Docs

| Doc | What it covers |
|---|---|
| [docs/BACKUP_AND_RESTORE.md](../docs/BACKUP_AND_RESTORE.md) | BackupService, backup.sh, restore.sh, verification |
| [docs/TWO_PERSON_DOGFOODING_RC.md](../docs/TWO_PERSON_DOGFOODING_RC.md) | RC runbook: allowed surfaces, config, smoke tests, rollback |

## Module Docs

Load only the modules relevant to your task.

| Task area | Module doc |
|---|---|
| Space / user / workspace data model | [modules/space.md](modules/space.md) |
| Agent profiles, runs, adapters | [modules/agents.md](modules/agents.md) |
| Activities, artifacts, proposals | [modules/proposals.md](modules/proposals.md) |
| Long-term memory | [modules/memory.md](modules/memory.md) |
| Raw input and event capture | [modules/activity.md](modules/activity.md) |
| Activity inbox UI and quick capture | [modules/activity-inbox.md](modules/activity-inbox.md) |
| Policy and permission engine | [modules/policy.md](modules/policy.md) |
| Proposal / approval system | [modules/proposals.md](modules/proposals.md) |
| Capability lifecycle | [modules/capability.md](modules/capability.md) |
| Context assembly and vendor files | [modules/context-compiler.md](modules/context-compiler.md) |
| Sandbox execution | [modules/sandbox.md](modules/sandbox.md) |
| Workspace browser / file UI | [modules/workspace-console.md](modules/workspace-console.md) |
| Runtime adapters | [modules/runtime-adapters.md](modules/runtime-adapters.md) |
| Credentials | [modules/credentials.md](modules/credentials.md) |
| Deployment | [modules/deployment.md](modules/deployment.md) |
| Personal assistant and capture | [modules/assistant-capture.md](modules/assistant-capture.md) |

## Decision Records

| ADR | Summary |
|---|---|
| [0001](decisions/0001-space-model.md) | Space as product-level isolation boundary |
| [0002](decisions/0002-agent-model.md) | Agent is a separate model from User |
| [0003](decisions/0003-memory-proposal-flow.md) | Agents do not directly write active memory |
| [0004](decisions/0004-context-wrapper.md) | Vendor files are generated adapters, not source of truth |
| [0005](decisions/0005-desktop-runtime.md) | Windows desktop is not a full runtime |
| [0006](decisions/0006-open-source-readiness.md) | Private-first, open-source-ready |
| [0007](decisions/0007-plugin-module-architecture.md) | Plugin module structure for per-deployment feature control |
| [0008](decisions/0008-multi-cli-mvp.md) | Multi-CLI MVP |

## Rules for AI Agents

- Do not load all docs for every task. Use the smallest relevant bundle.
- Check [context-bundles.yaml](context-bundles.yaml) for task-type → doc mappings.
- Never write to `instance/` from code in `core/`.
- Never write active memory directly — use proposals.
- Never write vendor context files to the real workspace — write to sandbox only.
- Read BOUNDARIES.md before making structural changes.
- New module routes go in `app/<module>/api.py`. Register in `app/modules/registry.py`.
- New frontend pages go in `src/modules/<module>/`. Register in `src/modules/registry.js`.
- **Do not reintroduce temporary task docs, milestone files, or audit reports into `.agent/tasks/` or `.agent/reports/`.**
- The `.agent/architecture/` docs describe **current state**. Do not add target-state aspirations without a scoped implementation task.
