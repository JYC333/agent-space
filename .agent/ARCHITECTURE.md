# Architecture

## Layer Map

```
┌─────────────────────────────────────────────────────┐
│  13. Mobile Client Layer  [PLANNED]                  │
│     PWA, offline queue, swipe review                │
│     frontend/src/ (mobile layout variants)          │
├─────────────────────────────────────────────────────┤
│  12. Product UI / Shell Layer  [PLANNED]             │
│     Shell, NavRail, CommandPalette, PanelLayout     │
│     Activity Inbox, Memory Review, Wiki, Cards UI   │
│     frontend/src/                                   │
├─────────────────────────────────────────────────────┤
│  11. Workspace Console Layer                         │
│     File browser, git diff review, run logs,        │
│     artifact review, diff approval UI               │
├─────────────────────────────────────────────────────┤
│  10. Runtime Adapter / Sandbox Layer                 │
│     SandboxManager, PathPolicy, ContextCompiler      │
│     AgentAdapter subclasses (echo, claude_cli, …)   │
│     core/backend/app/workspace/ + agents/           │
├─────────────────────────────────────────────────────┤
│  10b. Deployment Layer                               │
│     DeployerClient → Unix socket → host deployer    │
│     DeploymentJob records, whitelisted scripts       │
│     core/backend/app/deployment/ + deployer/        │
├─────────────────────────────────────────────────────┤
│   9. Proposal / Approval Layer                       │
│     Generalized Proposal, ApprovalEvent, Artifact   │
│     memory_update, code_patch, artifact review      │
│     core/backend/app/proposals/ + app/artifacts/    │
├─────────────────────────────────────────────────────┤
│   8. Governance / Policy Layer                       │
│     PolicyEngine: allow / deny / require_approval   │
│     core/backend/app/policy/                        │
├─────────────────────────────────────────────────────┤
│   7. Capability Layer                                │
│     YAML manifests, code, prompts, tests            │
│     Lifecycle: draft → testing → enabled            │
│     core/capabilities/ + app/capabilities/          │
├─────────────────────────────────────────────────────┤
│   6. Learning Layer  [PLANNED]                       │
│     FlashCards, CardReview, FSRS scheduling         │
│     Media cards (image occlusion, audio cloze)      │
│     core/backend/app/cards/                         │
├─────────────────────────────────────────────────────┤
│   5. Knowledge / Wiki Layer  [PLANNED]               │
│     KnowledgeItem, KnowledgeRelation               │
│     Structured, agent-generated, proposal-gated     │
│     core/backend/app/knowledge/                     │
├─────────────────────────────────────────────────────┤
│   4. Memory Layer                                    │
│     Scoped long-term context (not raw data)         │
│     ContextBuilder, MemoryStore, MemoryEvolver      │
│     core/backend/app/memory/                        │
├─────────────────────────────────────────────────────┤
│   3. Activity Layer                                  │
│     Raw inputs: user_input, web_capture, file_import │
│     ActivityRecord → proposals → memory/wiki/card   │
│     core/backend/app/activity/                      │
├─────────────────────────────────────────────────────┤
│   2. User / Agent Layer                              │
│     User (identity, membership)                     │
│     Agent (profile, policy, adapters, runs)         │
│     core/backend/app/agents/ + models.py            │
├─────────────────────────────────────────────────────┤
│   1. Space Layer                                     │
│     Space, SpaceMembership, WorkspaceMembership     │
│     All data scoped by space_id                     │
│     core/backend/app/models.py                      │
└─────────────────────────────────────────────────────┘
```

## Key Cross-Cutting Concerns

- **space_id** — every record carries it; the primary isolation boundary
- **Run is the central execution object** — every agent invocation creates a Run; Run produces Activities, Artifacts, and Proposals; Session is conversation-level, Run is execution-level
- **Proposal gate** — memory and code changes require explicit proposal approval before durable mutation
- **Runtime-agnostic core** — Agent is a product-level actor; Runtime Adapter (echo, claude_code, codex_cli, anthropic_api, opencode, …) is a replaceable execution backend; Model Provider (Anthropic, OpenAI, litellm) is the underlying LLM. These three are distinct.
- **Sandbox enforcement** — sandboxed adapters (those in `_SANDBOXED_ADAPTERS`: claude_code, codex_cli, and future coding runtimes) always run sandboxed; risk_level controls the sandbox level (worktree default, Docker for high-risk). See `modules/sandbox.md`.
- **ContextCompiler** — vendor files (CLAUDE.md, AGENTS.md, SOUL.md) are compiled artefacts written to the sandbox, never source of truth; security scanning, token budgets, and `.agent/` progressive loading enforced at compile time
- **ContextSnapshot** — frozen ContextPackage saved at run-start; immutable; stored in `context_snapshots` for audit
- **ContextAttachment** — structured context references (file, git_diff, memory_entry, etc.) resolved and scanned by ContextBuilder
- **MemoryProvider** — abstract interface for memory backends; `LocalMemoryProvider` is the only enabled provider in MVP
- **Module registry** — `app/modules/registry.py` (backend) and `src/modules/registry.js` (frontend) are the single sources of truth for which features are active; see [ADR 0007](decisions/0007-plugin-module-architecture.md)
- **Client-server protocol** — REST (current) + WebSocket events + SSE streaming (planned)
- **Partial offline support** — mobile captures and card reviews can queue offline and sync on reconnect; agent execution, memory writes, and proposal apply remain server-authoritative; see [architecture/LOCAL_FIRST_COMPATIBILITY.md](architecture/LOCAL_FIRST_COMPATIBILITY.md)
- **Run resilience fields** — status includes `degraded`; mode includes `live|dry_run`; temporal fields are explicit; artifacts are exportable; proposals have urgency/deadline
- **Home summary API** — Home UI consumes lightweight summaries only; no full ContextPackage

## Where Does a New Feature Belong?

| Feature type | Layer | Module path |
|---|---|---|
| New data entity tied to a space | Layer 1–2 | `app/models.py` |
| New agent capability or tool | Layer 7 | `core/capabilities/<id>/` |
| New AI-driven analysis or transformation | Layers 7–9 | capability + proposal modules |
| New permission rule | Layer 8 | `app/policy/` |
| New memory scope or type | Layer 4 | `app/memory/` |
| New raw capture source | Layer 3 | `app/activity/` (planned) |
| New structured knowledge type | Layer 5 | `app/knowledge/` (planned) |
| New review card type | Layer 6 | `app/cards/` (planned) |
| New UI view (web) | Layer 12 | `frontend/src/modules/<name>/` |
| New UI view (mobile-primary) | Layer 13 | `frontend/src/modules/<name>/` mobile variants |
| New runtime adapter (CLI or SDK) | Layer 10 | `app/agents/` — see `modules/runtime-adapters.md` |
| Workspace file operation | Layer 11 | `app/workspace/` |
| New optional feature module | All | add to `app/modules/registry.py` + `src/modules/registry.js` |

## Runtime Targets (MVP)

- **Runtime**: Linux / WSL2 / server (Docker Compose)
- **UI**: Browser (React SPA) — also serves as PWA
- **Mobile**: PWA (same codebase, mobile layout variants)
- **Desktop**: Deferred — see [decisions/0005](decisions/0005-desktop-runtime.md)
