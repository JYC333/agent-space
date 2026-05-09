# Memory Model

## Memory Types

| Type | Description | Examples |
|---|---|---|
| `preference` | Stable behavioral preferences | "I prefer Python", "I like dark mode" |
| `semantic` | Stable factual knowledge | "I am a software engineer", "My company is Acme" |
| `episodic` | Record of what happened | "User completed onboarding on 2025-05-01" |
| `procedural` | How to do something | "My deploy process: push to main → CI auto-deploys" |
| `project` | Project-specific facts | "agent-core uses FastAPI + SQLite" |

## Memory Scopes

Scopes form a hierarchy: `system > tenant > user > workspace > capability > agent`

| Scope | Description |
|---|---|
| `system` | Global rules applying to all tenants |
| `tenant` | Tenant-wide facts and policies |
| `user` | Per-user long-term memory |
| `workspace` | Project/workspace-specific memory |
| `capability` | Memory belonging to a capability |
| `agent` | Ephemeral agent-session memory (direct write allowed) |

## Namespace Design

Namespaces are dot-separated hierarchical identifiers:

```
user.default.preferences
user.default.goals
user.default.profile
workspace.agent-core.project
capability.memory.reflect
agent.coding-agent.behaviour
system.memory_policy
system.context_policy
```

Use namespaces to partition memories within a scope for efficient retrieval.

## Visibility

| Visibility | Who can read |
|---|---|
| `private` | Owner only |
| `shared` | Users sharing the same workspace |
| `public_within_tenant` | All users in the tenant |

## Memory Status Lifecycle

```
proposed → accepted → active
         → rejected  (terminal)
active   → archived
active   → superseded (when a newer version replaces it)
```

## Proposal Workflow

Agents may NOT write long-term memory directly (except `agent` scope).
All writes go through:

```
Session messages
→ MemoryReflector (analyze + generate proposals)
→ memory_proposals table (status: pending)
→ User review (accept / reject)
→ On accept: Memory created (status: active)
→ On reject: Proposal marked rejected, no memory created
```

## Context Builder Logic

The context builder assembles a scoped package:

1. **System policy** — always included (small, high-priority)
2. **User memory** — filtered by tenant + user, sorted by importance + confidence + recency
3. **Workspace memory** — only if workspace_id provided
4. **Capability memory** — only if capability_id provided
5. **Episodic memories** — recent events, capped separately
6. **Query search** — if a query string is provided, keyword-matched memories are merged in

The package is a read-only snapshot. Agents cannot modify it.

## Multi-user Readiness

Every memory record carries:
- `tenant_id` — isolates tenants
- `owner_user_id` — isolates users within a tenant
- `workspace_id` — optional, for workspace-scoped memories

Default single-user values: `tenant_id="personal"`, `user_id="default_user"`.

## Local-first Readiness

- IDs are ULIDs (client-generatable, no server round-trip)
- All records have `created_at`, `updated_at`, `deleted_at` (soft delete)
- `version` field supports optimistic concurrency
- No hard dependency on server-generated IDs
