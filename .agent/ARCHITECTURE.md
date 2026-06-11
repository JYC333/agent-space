# Architecture

## Layer Map

```
┌─────────────────────────────────────────────────────┐
│  13. Mobile Client Layer  [PLANNED]                  │
│     PWA, offline queue, swipe review                │
│     apps/web/src/ (mobile layout variants)          │
├─────────────────────────────────────────────────────┤
│  12. Product UI / Shell Layer  [PLANNED]             │
│     Shell, NavRail, CommandPalette, PanelLayout     │
│     Activity Inbox, Memory Review, Knowledge, Cards │
│     apps/web/src/                                   │
├─────────────────────────────────────────────────────┤
│  11. Workspace Console Layer                         │
│     File browser, git diff review, run logs,        │
│     artifact review, diff approval UI               │
├─────────────────────────────────────────────────────┤
│  10. Runtime Adapter / Sandbox Layer                 │
│     RuntimeAdapterSpec, GenericCliRuntimeAdapter     │
│     ContextCompiler, worktree/sandbox governance     │
│     backend/app/runtimes/ + runs/               │
├─────────────────────────────────────────────────────┤
│  10b. Deployment Layer                               │
│     DeployerClient → Unix socket → host deployer    │
│     DeploymentJob records, whitelisted scripts       │
│     backend/app/deployment/ + deployer/        │
├─────────────────────────────────────────────────────┤
│   9. Proposal / Approval Layer                       │
│     Generalized Proposal, ApprovalEvent, Artifact   │
│     memory_update, code_patch, artifact review      │
│     backend/app/proposals/ + app/artifacts/    │
├─────────────────────────────────────────────────────┤
│   8. Governance / Policy Layer                       │
│     PolicyEngine: allow / deny / require_approval   │
│     backend/app/policy/                        │
├─────────────────────────────────────────────────────┤
│   7. Capability Layer                                │
│     YAML manifests, code, prompts, tests            │
│     Lifecycle: draft → testing → enabled            │
│     catalog/capabilities/ + app/capabilities/          │
├─────────────────────────────────────────────────────┤
│   6. Learning Layer  [PLANNED]                       │
│     FlashCards, CardReview, FSRS scheduling         │
│     Media cards (image occlusion, audio cloze)      │
│     backend/app/cards/                         │
├─────────────────────────────────────────────────────┤
│   5. Knowledge Layer  [PLANNED]                      │
│     KnowledgeItem, KnowledgeItemRelation,           │
│     Source, KnowledgeItemSource                     │
│     Structured, agent-generated, proposal-gated     │
│     backend/app/knowledge/                     │
├─────────────────────────────────────────────────────┤
│   4. Memory Layer                                    │
│     Scoped long-term context (not raw data)         │
│     ContextBuilder, MemoryStore, MemoryEvolver      │
│     backend/app/memory/                        │
├─────────────────────────────────────────────────────┤
│   3. Activity Layer                                  │
│     Raw inputs: user_input, web_capture, file_import │
│     ActivityRecord -> proposals -> memory/knowledge │
│     backend/app/activity/                      │
├─────────────────────────────────────────────────────┤
│   2. User / Agent Layer                              │
│     User (identity, membership)                     │
│     Agent (profile, policy, adapters, runs)         │
│     backend/app/agents/ + models.py            │
├─────────────────────────────────────────────────────┤
│   1. Space Layer                                     │
│     Space, SpaceMembership, WorkspaceMembership     │
│     All data scoped by space_id                     │
│     backend/app/models.py                      │
└─────────────────────────────────────────────────────┘
```

## Key Cross-Cutting Concerns

- **space_id** — every record carries it; the primary isolation boundary
- **Run is the central execution object** — every agent invocation creates a Run; Run produces Activities, Artifacts, and Proposals; Session is conversation-level, Run is execution-level
- **Proposal gate** — memory and code changes require explicit proposal approval before durable mutation
- **Runtime-agnostic core** — Agent is a product-level actor; Runtime Adapter (echo, claude_code, codex_cli, opencode, model_api, ...) is a replaceable execution backend; Model Provider (Anthropic, OpenAI, litellm) is the underlying LLM. These three are distinct. Tool-using / filesystem Claude work goes through the `claude_code` CLI RuntimeAdapterSpec. Per ADR 0010 the governing invariant is **credential channel isolation** — an Anthropic API key must never enter a Claude Code CLI subprocess env; the in-process encrypted API channel (reflector, `/providers/chat`, `model_api`) passes the key as a litellm parameter (never via env) and may serve any provider including Anthropic.
- **Sandbox enforcement** — file-access local CLI runtimes (`claude_code`, `codex_cli`) require `risk_level=high` in `runtime_policy_json`; the execution service validates this before the adapter starts and fails the run with a clear config error if it is not set. `risk_level=high` maps to `required_sandbox_level=worktree`; the agent works in a detached git worktree, never directly in the real workspace. See `modules/sandbox.md`.
- **ContextCompiler** — vendor files (CLAUDE.md, AGENTS.md, SOUL.md) are compiled artefacts written to the sandbox, never source of truth; security scanning, token budgets, and `.agent/` progressive loading enforced at compile time
- **ContextSnapshot** — frozen ContextPackage saved at run-start; immutable; stored in `context_snapshots` for audit
- **ContextAttachment** — structured context references (file, git_diff, memory_entry, etc.) resolved and scanned by ContextBuilder
- **MemoryProvider** — abstract interface for memory backends; `LocalMemoryProvider` is the only enabled provider in MVP
- **Module registry** — `app/modules/registry.py` (backend) and `apps/web/src/modules/registry.ts` (frontend) are the single sources of truth for which features are active; see [ADR 0007](decisions/0007-plugin-module-architecture.md)
- **Client-server protocol** — REST (current) + WebSocket events + SSE streaming (planned)
- **Partial offline support** — mobile captures and card reviews can queue offline and sync on reconnect; agent execution, memory writes, and proposal apply remain server-authoritative; see [architecture/LOCAL_FIRST_COMPATIBILITY.md](architecture/LOCAL_FIRST_COMPATIBILITY.md)
- **Run resilience fields** — status includes `degraded`; mode includes `live|dry_run`; temporal fields are explicit; artifacts are exportable; proposals have urgency/deadline
- **Home summary API** — Home UI consumes lightweight summaries only; no full ContextPackage

## Where Does a New Feature Belong?

| Feature type | Layer | Module path |
|---|---|---|
| New data entity tied to a space | Layer 1–2 | `app/models.py` |
| New agent capability or tool | Layer 7 | `catalog/capabilities/<id>/` |
| New AI-driven analysis or transformation | Layers 7–9 | capability + proposal modules |
| New permission rule | Layer 8 | `app/policy/` |
| New memory scope or type | Layer 4 | `app/memory/` |
| New raw capture source | Layer 3 | `app/activity/` (planned) |
| New structured knowledge type | Layer 5 | `app/knowledge/` |
| New review card type | Layer 6 | `app/cards/` (planned) |
| New UI view (web) | Layer 12 | `apps/web/src/modules/<name>/` |
| New UI view (mobile-primary) | Layer 13 | `apps/web/src/modules/<name>/` mobile variants |
| New runtime adapter (CLI or SDK) | Layer 10 | `app/runtimes/` — see `modules/runtime-adapters.md` |
| Workspace file operation | Layer 11 | `app/workspace/` |
| New optional feature module | All | add to `app/modules/registry.py` + `apps/web/src/modules/registry.ts` |

## Runtime Targets (MVP)

- **Runtime**: Linux / WSL2 / server (Docker Compose)
- **UI**: Browser (React SPA) — also serves as PWA
- **Mobile**: PWA (same codebase, mobile layout variants)
- **Desktop**: Deferred — see [decisions/0005](decisions/0005-desktop-runtime.md)
