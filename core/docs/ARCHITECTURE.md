# Architecture

## Core flow

```
User input
→ Session
→ Context Builder     (retrieves relevant memories)
→ Agent / Capability  (executes with context)
→ Tool / CLI call     (optional)
→ Episodic recording  (run logged)
→ Memory Reflection   (proposals generated)
→ User Approval       (accept / reject)
→ Active Long-term Memory
→ Future Context Injection
```

## Service boundaries

| Service | Responsibility |
|---|---|
| `MemoryStore` | CRUD and query for long-term memories |
| `MemoryProposalService` | Proposal lifecycle (create, accept, reject) |
| `MemoryReflector` | Analyze sessions, generate proposals |
| `ContextBuilder` | Assemble scoped context packages for agents |
| `CapabilityRegistry` | Load, validate, and register capabilities |
| `SessionService` | Manage sessions and messages |
| `TaskService` | Track units of agent work |
| `AgentRunService` | Execute agent runs via registered adapters |

## Database schema (key tables)

- `memories` — long-term memory store (multi-scope, multi-tenant)
- `memory_proposals` — pending/accepted/rejected proposals
- `sessions` + `messages` + `session_summaries` — short-term conversational state
- `capabilities` — registered capability manifests
- `tasks` + `agent_runs` + `tool_calls` + `artifacts` — run logging
- `approvals` — general-purpose approval records

## Multi-tenancy

All core tables include `tenant_id`, `owner_user_id`, and optionally `workspace_id`.
Default single-user values: `tenant_id="personal"`, `user_id="default_user"`.

## ID strategy

All IDs are ULIDs (lexicographically sortable, client-generatable).
This enables local-first clients to create records without a server round-trip.

## API

All routes are under `/api/v1/`.
See `/docs` (Swagger UI) for the full interactive API reference.
