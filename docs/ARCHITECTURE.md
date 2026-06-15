# Architecture

## Core flow

```
User input
→ Session
→ Context Builder     (retrieves memories, scoped by agent memory policy)
→ AgentService        (validates policy, prepares agent identity)
→ RunService          (creates queued Run rows + snapshots)
→ RunExecutionService (selects adapter, executes, persists outputs)
→ AgentAdapter        (pure execution backend — capability / model_api / claude_code / codex_cli / …)
→ Run record          (output, status, delegation_depth logged)
→ Memory Reflection   (proposals from the MemoryReflector service / memory.reflect capability)
→ User Approval       (accept / reject proposals)
→ Active Long-term Memory
→ Future Context Injection
```

## Service boundaries

| Service | Responsibility |
|---|---|
| `MemoryStore` | CRUD and query for long-term memories |
| `ProposalService` | Proposal lifecycle (create, accept, reject) |
| `MemoryReflector` | Analyze sessions, generate proposals |
| `ContextBuilder` | Assemble scoped context packages — hard `space_id` + `user_id` boundary |
| `CapabilityRegistry` | Load, validate, and register capabilities |
| `SessionService` | Manage sessions and messages |
| `TaskService` | Track units of agent work |
| `AgentService` | Agent CRUD + delegation policy enforcement |
| `RunService` | Create and list queued Runs, link tasks, manage snapshots |
| `RunExecutionService` | Adapter dispatch, sandbox routing, terminal status updates |
| `EvolutionRunService` | Create proposal-first evolution runs, artifacts, and reviewable proposals without direct mutation |

## Agent kernel vs adapter boundary

`AgentService`, `RunService`, and `RunExecutionService` form the execution stack. Together they own agent identity, memory policy, delegation rules, context assembly, and durable run records.

`AgentAdapter` subclasses are pure execution backends. They receive a pre-built
prompt + context snapshot and return a result. They have no DB access, no memory
writes, and no delegation authority.

External frameworks (OpenAI Agents SDK, LangGraph, CrewAI, etc.) are wired in as
additional adapters. No kernel code changes. See `docs/MULTI_AGENT.md` for details.

## Multi-agent delegation

Agents can delegate to other agents. The kernel enforces:
- `can_delegate` flag in `runtime_policy_json`
- `max_delegation_depth` — `delegation_depth` increments with each hop
- Space isolation — all runs in a chain share the same `space_id`

## Database schema (key tables)

- `spaces` + `space_memberships` — top-level isolation boundary
- `memories` — long-term memory store (multi-scope, space-isolated)
- `proposals` — pending/accepted/rejected durable mutation proposals
- `sessions` + `messages` + `session_summaries` — short-term conversational state
- `capabilities` — registered capability manifests
- `agents` — agent profiles, model config, memory policy, runtime policy
- `tasks` + `agent_runs` + `tool_calls` + `artifacts` — run logging
- `approvals` — general-purpose approval records
- `evolution_targets` + `evolution_signals` — product targets and evidence for reviewable evolution

## Evolution Module

Evolution is a first-level product module at `/evolution`. It reads
`/api/v1/evolution` DTOs for overview counts, targets, signals, runs, proposals,
and validation metrics. Triggering an evolution review creates a Run plus
artifacts and a pending Proposal; it does not directly mutate prompts, memory,
capabilities, policies, files, or code.

## Space model

All core tables include `space_id` and `owner_user_id`. Spaces are the hard
isolation boundary: `ContextBuilder` raises `ValueError` if called without a
valid `space_id`. Cross-space memory retrieval is impossible by construction.

Default single-user values: `space_id="personal"`, `user_id="default_user"`.

See `docs/SPACE_MODEL.md` for the full space model.

## ID strategy

All IDs are ULIDs (lexicographically sortable, client-generatable).
This enables local-first clients to create records without a server round-trip.

## API

All routes are under `/api/v1/`.
See `/docs` (Swagger UI) for the full interactive API reference.
