# Memory model and family-space safety

## Principle

A **Space** is a collaboration boundary, not a shared mind. Members of a household or team space work together, but private cognition, restricted facts, and per-user context must remain enforceable at read time.

## What lives in family space memory

- **Space-shared memory** — visibility `space_shared`; readable by any member of the same space unless `sensitivity_level` blocks it.
- **User-owned memory** — `owner_user_id` identifies the human who controls the row for ACL; distinct from who the memory is *about*.
- **Subject-user memory** — `subject_user_id` means who or what the memory is *about* (often another user or the self); must not be conflated with `owner_user_id`.
- **Workspace / project memory** — scoped to a workspace; `workspace_shared` requires a matching `workspace_id` at read time.
- **Selected-user memory** — visibility `selected_users`; readers must appear in `selected_user_ids` (or be the owner).
- **Restricted / highly restricted** — `visibility=restricted` limits readers to the owner plus users listed in `selected_user_ids`. `sensitivity_level=highly_restricted` is owner-only for MVP regardless of visibility (invalid combinations such as `highly_restricted` + `space_shared` are rejected on write).
- **Summary-only memory** — visibility `summary_only`; non-owners in the space see metadata only; full `content` is redacted for them in API and `ContextBuilder`.
- **System-scoped memory** — `scope_type=system`; excluded from normal list/search/get/context bulk loads unless an explicit system path passes `include_system_scope=True` (e.g. the system policy branch in `ContextBuilder`).
- **Public templates** — visibility `public_template`; excluded from normal family reads unless an explicit path sets `include_public_templates=True`.

## Field semantics

| Field | Role |
|-------|------|
| `owner_user_id` | Human who controls the memory and receives owner ACL (may be null for system, workspace, space-level, agent, capability, public-template, or policy-controlled rows). |
| `subject_user_id` | Who or what the memory is about. Never inferred from `owner_user_id`. |
| `scope_type` | Public placement category (`system`, `space`, `user`, `workspace`, `agent`, etc.). Specific object placement uses the dedicated owner/workspace/project/agent columns rather than a generic `scope_id`. |
| `memory_type` | Public memory category used by APIs, digests, and UI grouping. |
| `memory_layer` | Layer in the memory hierarchy (`semantic` or `episodic` in the current baseline). |
| `visibility` | Who may read or see a redacted view (`private`, `space_shared`, `workspace_shared`, `selected_users`, `summary_only`, `restricted`, `public_template`). |
| `sensitivity_level` | How cautiously the row may be used (`normal`, `sensitive`, `restricted`, `highly_restricted`). |
| `selected_user_ids` | JSON list; used with `selected_users` or `restricted` visibility. |
| `created_from_proposal_id` | Canonical accepted-proposal FK for active memory creation. |

## Agents and context

Agents must **not** load all memories in a space. `ContextBuilder` requires `space_id` and `user_id`, applies the same `can_read_memory` rules as the HTTP API, redacts `summary_only` content for non-owners, and writes one `MemoryReadTrace` row per memory injected (`access_type=context_injection`) while updating `access_count` / `last_accessed_at`.

Canonical explicit reads (GET /memory/{id}, search hits) also append `MemoryReadTrace` rows.

## Writes and proposals

Long-lived writes should continue to go through the **proposal → approval** flow where applicable. Proposal payloads carry `owner_user_id`, `subject_user_id`, `visibility`, `sensitivity_level`, and `selected_user_ids` alongside existing fields; acceptance must not conflate approving user, owner, and subject.

When a `memory_create` carries no explicit visibility, the default is **space-type-aware**: a `personal` space defaults to `space_shared` (sole member), while a multi-member `household`/`team` space defaults to `restricted` owner-only (`owner_user_id` = the creating user, empty `selected_user_ids`). This keeps one member's assistant/sources-derived memory private to them; sharing it with the space is an explicit promotion (a `memory_update` to `space_shared`). See [SHARED_SPACE_MEMORY_ISOLATION.md](SHARED_SPACE_MEMORY_ISOLATION.md). The hard placement invariant still holds: `visibility=private` is only permitted in personal spaces.

## Implementation map

- Central rule: `server/src/modules/memory/memoryReadAuth.ts` — `canReadMemory`, `userInSelectedIds`, `summaryOnlyRedactContent`.
- Serialization / redaction: `server/src/modules/memory/repository.ts` — memory row to API output helpers.
- Persistence of reads: `server/src/modules/memory/repository.ts`; table `memory_access_logs` / protocol type `MemoryReadTrace`.

## Future work (TODO)

- Validate `subject_user_id` and `owner_user_id` against space membership when a membership service is available.
- Richer policy for `sensitivity_level` beyond MVP.
- Deduplicate audit logs if the same memory is injected multiple ways in one request (optional product decision).

## Non-goals

No full RBAC, no `MemoryAccessGrant` table, no redesign of the global proposal system, native memory-health evolution loop, frontend, or runtime adapters. Keep read-audit ORM names aligned with the canonical `MemoryReadTrace` model.
