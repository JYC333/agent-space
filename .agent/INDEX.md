# Agent Context Index

## 1. Repository Context

agent-space is a space-based, multi-user, agent-first system for personal, family, and small-team
use within a single deployment instance. It has a server backend (PostgreSQL),
a React/Vite frontend (PWA), and a server-authoritative agent execution model: agents run server-side inside isolated
sandboxes, memory is written only through a proposal → approval workflow, and policy and
credentials are enforced centrally. The system is **not** local-first; it supports offline capture
and draft queuing for personal convenience but agent execution, active memory, proposals,
credentials, workspace operations, and deployment remain server-authoritative. See
[architecture/LOCAL_FIRST_COMPATIBILITY.md](architecture/LOCAL_FIRST_COMPATIBILITY.md) for the
durable position on this boundary.

**Source of truth hierarchy:**

1. **Code** — implementation truth; always wins over docs
2. `server/migrations/` — canonical database schema migrations
3. `packages/protocol/src/` — shared public DTOs and wire contracts
4. `server/src/gateway/routeRegistry.ts` — active backend route registry
5. `server/src/modules/` — active backend module implementations
6. `apps/web/src/modules/registry.ts` — active frontend modules and nav items
7. `.agent/BOUNDARIES.md` — architectural invariants; load for any structural change
8. `.agent/decisions/` — accepted architectural decisions

Docs in `.agent/architecture/` describe **current state**, not target-state speculation. Temporary
reports in `.agent/reports/` are not source of truth and should be deleted after consolidation.

---

## 2. Start Here

| What you need | Link |
|---|---|
| Current active focus and short-term priorities | [tasks/current-focus.md](tasks/current-focus.md) |
| Security and access boundary reference | [architecture/SECURITY_AND_ACCESS_BOUNDARIES.md](architecture/SECURITY_AND_ACCESS_BOUNDARIES.md) |
| Test layer and product invariant philosophy | [architecture/TESTING_STRATEGY.md](architecture/TESTING_STRATEGY.md) |
| Local-first compatibility position | [architecture/LOCAL_FIRST_COMPATIBILITY.md](architecture/LOCAL_FIRST_COMPATIBILITY.md) |
| Architectural invariants (load before structural changes) | [BOUNDARIES.md](BOUNDARIES.md) |
| Layer map and cross-cutting concerns | [ARCHITECTURE.md](ARCHITECTURE.md) |
| How to run, test, and build | [COMMANDS.md](COMMANDS.md) |
| Practical gotchas | [WORKING_TIPS.md](WORKING_TIPS.md) |

---

## 3. Architecture Map

### Product Model

| Doc | What it covers |
|---|---|
| [architecture/PRODUCT_AND_BOUNDARIES.md](architecture/PRODUCT_AND_BOUNDARIES.md) | Product identity, current enforcement points, architecture fitness checks |
| [architecture/NON_GOALS_AND_DISABLED_SURFACES.md](architecture/NON_GOALS_AND_DISABLED_SURFACES.md) | Disabled surfaces, allowed surfaces, non-goals |
| [architecture/ROADMAP_AND_FUTURE_RISKS.md](architecture/ROADMAP_AND_FUTURE_RISKS.md) | Capability line roadmap, future risks |
| [architecture/CAPABILITY_WORKFLOW_SKILL_SYSTEM.md](architecture/CAPABILITY_WORKFLOW_SKILL_SYSTEM.md) | Capability definitions, packs, workflows, Open Skill import, runtime skill rendering |
| [architecture/LOCAL_FIRST_COMPATIBILITY.md](architecture/LOCAL_FIRST_COMPATIBILITY.md) | Data classification, offline write rules, sync schema guidelines |

### Security and Access Boundaries

| Doc | What it covers |
|---|---|
| [architecture/SECURITY_AND_ACCESS_BOUNDARIES.md](architecture/SECURITY_AND_ACCESS_BOUNDARIES.md) | Auth boundary, space isolation, object visibility, session/task/activity policy, cross-space exceptions, credential secrecy, dogfooding readiness |
| [architecture/CREDENTIAL_STORAGE.md](architecture/CREDENTIAL_STORAGE.md) | How secrets are stored at rest: ModelProvider API keys (AES-256-GCM + disk master key + `secret_ref`) vs CLI login state; runtime resolution; ADR 0010 channel isolation |
| [architecture/POLICY_ENFORCEMENT_INVENTORY.md](architecture/POLICY_ENFORCEMENT_INVENTORY.md) | All current policy enforcement points; enforcement status per class |

### Backend Domains

| Doc | What it covers |
|---|---|
| [architecture/MODULES.md](architecture/MODULES.md) | Current backend module map, support packages, ownership, registries, facades |
| [architecture/MODULE_DEVELOPMENT_GUIDE.md](architecture/MODULE_DEVELOPMENT_GUIDE.md) | How to add/change backend modules and extension hooks |
| [architecture/DATABASE_AND_TRANSACTIONS.md](architecture/DATABASE_AND_TRANSACTIONS.md) | UnitOfWork, transaction ownership, external call boundary, PostgreSQL rules |
| [architecture/MEMORY_MODEL.md](architecture/MEMORY_MODEL.md) | Memory scopes, visibility, access control |
| [architecture/PROPOSALS.md](architecture/PROPOSALS.md) | Proposal types, lifecycle, apply flow |
| [architecture/TASK_BOARD_MODEL.md](architecture/TASK_BOARD_MODEL.md) | Task, Board, TaskRun, TaskArtifact, TaskProposal ORM |
| [architecture/ARTIFACTS.md](architecture/ARTIFACTS.md) | Artifact lifecycle, storage paths, export |
| [architecture/OPERATIONS_AND_SAFETY.md](architecture/OPERATIONS_AND_SAFETY.md) | Backup, restore, lifecycle states, deployment boundary, stop conditions |

### Runtime / Agents / Runs

| Doc | What it covers |
|---|---|
| [architecture/EXECUTION_MODEL.md](architecture/EXECUTION_MODEL.md) | Run, RunStep, Job, Artifact, Proposal, actor identity, credential resolver |
| [architecture/RUNS_AND_OUTPUTS.md](architecture/RUNS_AND_OUTPUTS.md) | Run outputs, materialization, boundaries |

### Server / Backend

| Doc | What it covers |
|---|---|
| [architecture/PROTOCOL_FOUNDATION.md](architecture/PROTOCOL_FOUNDATION.md) | Contracts-only protocol package |
| [architecture/SERVER_FOUNDATION.md](architecture/SERVER_FOUNDATION.md) | The server service: gateway, route registry, compose wiring |
| [architecture/SERVER_OWNERSHIP.md](architecture/SERVER_OWNERSHIP.md) | Current server ownership and deferred surfaces |
| [architecture/SERVER_MODULE_CONVENTION.md](architecture/SERVER_MODULE_CONVENTION.md) | Server-owned module structure, route registry, error envelope |

### Memory / Activity / Proposal

| Doc | What it covers |
|---|---|
| [architecture/MEMORY_ACTIVITY_PROVENANCE.md](architecture/MEMORY_ACTIVITY_PROVENANCE.md) | Activity-first capture, provenance chain, trust gate, memory write boundaries |
| [architecture/MEMORY_MODEL.md](architecture/MEMORY_MODEL.md) | Memory scopes, visibility, access control |
| [architecture/PROPOSALS.md](architecture/PROPOSALS.md) | Proposal types, lifecycle, apply flow |
| [architecture/MEMORY_EVOLUTION_PLAN.md](architecture/MEMORY_EVOLUTION_PLAN.md) | Planned memory-quality work (gbrain absorption): weighted claims, hybrid retrieval, synthesis + gap loop, consolidation cycle |

### Workspace / Sandbox / Artifact

| Doc | What it covers |
|---|---|
| [architecture/ARTIFACTS.md](architecture/ARTIFACTS.md) | Artifact lifecycle, storage paths, export |
| [architecture/EXECUTION_MODEL.md](architecture/EXECUTION_MODEL.md) | Sandbox selection, worktree vs Docker, PathPolicy |

### Frontend Information Architecture

The frontend module registry (`apps/web/src/modules/registry.ts`) and shell (`apps/web/src/core/Shell.tsx`)
are source of truth for active nav and routes. For UI decisions, see the module docs below:

| Doc | What it covers |
|---|---|
| [architecture/FRONTEND_INFORMATION_ARCHITECTURE.md](architecture/FRONTEND_INFORMATION_ARCHITECTURE.md) | Frontend role, dogfooding loop, home direction, module visibility, empty-state policy |
| [modules/product-shell.md](modules/product-shell.md) | Shell, NavRail, CommandPalette, PanelLayout |
| [modules/frontend-layout.md](modules/frontend-layout.md) | Responsive layout, mobile variants |
| [modules/client-server-protocol.md](modules/client-server-protocol.md) | REST, WebSocket, SSE, offline queue protocol |
| [modules/activity-inbox.md](modules/activity-inbox.md) | Activity inbox UI and quick capture |

### Testing Strategy

| Doc | What it covers |
|---|---|
| [architecture/TESTING_STRATEGY.md](architecture/TESTING_STRATEGY.md) | Test layers, product invariant philosophy, what each layer covers |

---

## 4. Module Map

Load only the module docs relevant to your task.

| Task area | Module doc |
|---|---|
| Space / user / workspace data model | [modules/space.md](modules/space.md) |
| Agent profiles, runs, adapters | [modules/agents.md](modules/agents.md) |
| Long-term memory | [modules/memory.md](modules/memory.md) |
| Raw input and event capture | [modules/activity.md](modules/activity.md) |
| Activity inbox UI and quick capture | [modules/activity-inbox.md](modules/activity-inbox.md) |
| Personal assistant and capture | [modules/assistant-capture.md](modules/assistant-capture.md) |
| Memory review UI | [modules/memory-review.md](modules/memory-review.md) |
| Policy and permission engine | [modules/policy.md](modules/policy.md) |
| Proposal / approval system | [modules/proposals.md](modules/proposals.md) |
| Capability lifecycle | [modules/capability.md](modules/capability.md) |
| Context assembly and vendor files | [modules/context-compiler.md](modules/context-compiler.md) |
| Sandbox execution | [modules/sandbox.md](modules/sandbox.md) |
| Workspace browser / file UI | [modules/workspace-console.md](modules/workspace-console.md) |
| Runtime tools / adapter types | [modules/runtime-adapters.md](modules/runtime-adapters.md) |
| Credentials | [modules/credentials.md](modules/credentials.md) |
| Deployment | [modules/deployment.md](modules/deployment.md) |
| Knowledge Base / knowledge items | [modules/knowledge-base.md](modules/knowledge-base.md) |
| Spaced repetition / cards | [modules/spaced-repetition.md](modules/spaced-repetition.md) |
| Media cards | [modules/media-cards.md](modules/media-cards.md) |
| Sync and conflict model | [modules/sync-and-conflicts.md](modules/sync-and-conflicts.md) |
| Mobile client | [modules/mobile-client.md](modules/mobile-client.md) |
| Server status bar | [modules/server-status.md](modules/server-status.md) |
| Git diff review | [modules/git-diff-review.md](modules/git-diff-review.md) |
| Provider / LLM policy | [modules/provider-policy.md](modules/provider-policy.md) |
| Commercialization | [modules/commercialization.md](modules/commercialization.md) |

---

## 5. Decision Records

| ADR | Summary |
|---|---|
| [0001](decisions/0001-space-model.md) | Space as product-level isolation boundary |
| [0002](decisions/0002-agent-model.md) | Agent is a separate model from User |
| [0003](decisions/0003-memory-proposal-flow.md) | Agents do not directly write active memory |
| [0004](decisions/0004-context-wrapper.md) | Vendor files are generated adapters, not source of truth |
| [0005](decisions/0005-desktop-runtime.md) | Windows desktop is not a full runtime |
| [0006](decisions/0006-open-source-readiness.md) | Private-first, open-source-ready |
| [0007](decisions/0007-plugin-module-architecture.md) | Module architecture (ServerModule registry, MODULE_REGISTRY) and official optional module control plane (PluginHost, dairy) |
| [0008](decisions/0008-multi-cli-mvp.md) | Multi-CLI MVP |
| [0009](decisions/0009-anthropic-cli-only-policy.md) | Anthropic CLI-only policy (superseded by ADR 0010) |
| [0010](decisions/0010-credential-channel-isolation.md) | Credential channel isolation |
| [0011](decisions/0011-capability-workflow-open-skill-system.md) | Capability, Workflow, and Open Skill framework |

---

## 6. Current Work

The single source of active task context is:

**[tasks/current-focus.md](tasks/current-focus.md)**

Do not create competing task files under `.agent/tasks/` or `.agent/`. Multiple task docs
cause context conflicts for both humans and AI agents. If the focus changes, update
`current-focus.md` in place.

---

## 7. Reports Policy

`.agent/reports/` is for temporary audits and one-off investigations only.

Rules:
- Reports are not source of truth for architecture, policy, or design.
- Once the durable content of a report is consolidated into `.agent/architecture/` or a
  decision record, the report should be deleted.
- AI agents must not load reports as authoritative context.
- Do not reference temporary reports from architecture docs or `context-bundles.yaml`.

Long-term architecture information must live in `.agent/architecture/` or `.agent/decisions/`.

---

## 8. Context Loading Guidance for Agents

Use the smallest relevant bundle from [context-bundles.yaml](context-bundles.yaml). Do not
load all docs for every task.

| Task type | Load |
|---|---|
| Security / access change | `security-access` bundle: `SECURITY_AND_ACCESS_BOUNDARIES.md`, `POLICY_ENFORCEMENT_INVENTORY.md`, `TESTING_STRATEGY.md`, `BOUNDARIES.md` |
| Backend domain change | `backend-domain` bundle: relevant domain doc + `DATABASE_AND_TRANSACTIONS.md` + `BOUNDARIES.md` |
| Frontend / home / UI change | `frontend-product` bundle: `product-shell.md`, `frontend-layout.md`, `client-server-protocol.md`, module doc |
| Testing change | `TESTING_STRATEGY.md` + the specific test file's domain doc |
| Runtime / agent / run change | `runtime-agent` bundle: `EXECUTION_MODEL.md`, `RUNS_AND_OUTPUTS.md`, `agents.md`, `BOUNDARIES.md` |
| Memory / activity / proposal change | `memory-activity-proposal` bundle: `MEMORY_ACTIVITY_PROVENANCE.md`, `MEMORY_MODEL.md`, `PROPOSALS.md` |
| Workspace / artifact / path change | `workspace-artifact` bundle: `ARTIFACTS.md`, `EXECUTION_MODEL.md`, `sandbox.md`, `workspace-console.md` |
| Dogfooding / product slice | `current-focus.md` + `PRODUCT_AND_BOUNDARIES.md` + `NON_GOALS_AND_DISABLED_SURFACES.md` |
| Sync / offline / local-first compatibility | `local-first-compatibility` bundle: `LOCAL_FIRST_COMPATIBILITY.md`, `sync-and-conflicts.md`, `mobile-client.md` |

Additional agent rules:
- Never write to `instance/` from code in `core/`.
- Never write active memory directly — use proposals.
- Never write vendor context files to the real workspace — write to sandbox only.
- Read `BOUNDARIES.md` before making structural changes.
- New backend routes go in `server/src/modules/<module>/routes.ts` and
  the module is registered in `server/src/gateway/routeRegistry.ts`.
- New frontend pages go in `apps/web/src/modules/<module>/`, registered in
  `apps/web/src/modules/registry.ts`.
- Do not treat `.agent/reports/` content as durable source of truth.
- `.agent/architecture/` docs describe **current state**. Do not add target-state aspirations
  without a scoped implementation task.

---

## 9. Vendor Context and Conversion Plan

**Current state:** `CLAUDE.md` and `AGENTS.md` are hand-maintained adapter files that point
AI coding assistants toward the right entry points. They are not canonical architecture docs.

**Intended future model:**

| Source (canonical) | Generated output |
|---|---|
| `.agent/INDEX.md` | Section headers in `CLAUDE.md` / `AGENTS.md` |
| `.agent/context-bundles.yaml` | Task-type context directives in vendor files |
| `.agent/architecture/*.md` | Summarized constraints injected by ContextCompiler |

Generated files (`CLAUDE.md`, `AGENTS.md`, sandbox prompt files, runtime-specific context
files) are **disposable adapter outputs**, not canonical docs. When they conflict with
`.agent/architecture/`, the architecture docs win. See [ADR 0004](decisions/0004-context-wrapper.md).
