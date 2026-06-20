# Memory / Context Runtime

> Source of truth for: MemoryEntry lifecycle, retrieval pipeline, context
> assembly, ContextSnapshot population, ContextDigest cache, proposal apply write
> boundary, session summaries, budget enforcement, and read/policy enforcement
> points.

---

## 1. Core data model

### MemoryEntry

Persistent, approved, scoped knowledge. Key invariants:

| Invariant | Enforcement |
|-----------|-------------|
| `status="active"` only through approved write paths | server proposal apply service; no public direct active-memory mutation |
| Scoped to one space | `space_id` FK; server memory/context repositories enforce hard boundary |
| Private memory only in personal space | Policy hard invariant + memory proposal/apply validation |
| Deleted rows invisible | `deleted_at IS NULL` filter in every retrieval query |

Key columns: `scope_type` (user / workspace / agent / system / capability), `memory_layer` (semantic / episodic / procedural), `visibility`, `status` (proposed / active / archived / superseded), `version`, `fitness_score`, `source_proposal_id`.

### Active memory write boundary

Public API calls never write active memory directly. Active memory mutation goes
through proposal review and the server proposal apply service. There is no public
direct update/delete path for `memory_entries`.

**Allowed active-memory write paths:**

| Path | Entry point | source_proposal_id | source_trust | Notes |
|------|------------|-------------------|--------------|-------|
| Proposal apply | `server/src/modules/proposals/applyService.ts` + memory applier | set | from proposal payload | Normal product write boundary |
| System seed / bootstrap | server seed/migration code | not set | `"internal_system"` | Bootstrap only; must not be called from product or agent paths |

There is no product direct-write memory path. The memory write boundary is structural and is not configurable through persisted Policy rows.

No route, run, condenser, retriever, context builder, activity processor, or agent output path may create active `MemoryEntry` directly.

---

## 2. Read authorization (`server/src/modules/memory/memoryReadAuth.ts`)

```
can_read_memory(entry, user_id, space_id, workspace_id, include_system_scope) -> bool
```

Hard filter applied before any ranking:
- `space_id` match (never cross-space without PersonalMemoryGrant)
- `deleted_at IS NULL`
- `status == "active"`
- Visibility gate (private → owner_user_id match; workspace_shared → workspace_id match; restricted → selected_user_ids)
- Agent permission gate (agent_memory_policy.readable_scopes)

`summary_only_redact_content(entry, viewer_user_id)` — returns True if the viewer may only see summary (PersonalMemoryGrant summary-only mode).

---

## 3. Memory retrieval (`server/src/modules/context/repository.ts`)

Policy-aware retrieval pipeline. The server runtime path implements this in
`server/src/modules/context/repository.ts`.

```
MemoryRetriever(db).retrieve(
    space_id, user_id, workspace_id, agent_id,
    query, agent_memory_policy, max_memories, include_system_scope
) -> RetrievalResult
```

Stages (in order, each filters the already-hard-filtered universe):
1. **Hard filter** — space, deleted_at, status=active, visibility, agent permission
2. **Symbol match** — workspace-scoped, agent-scoped, user identity memories
3. **Graph expansion** — BFS on MemoryRelation, max 2 hops, bounded by space
4. **Keyword fallback** — ILIKE on title/content
5. **Embedding fallback** — stub (delegates to keyword)
6. **Final ranking + truncation** — fitness_score, recency, access_count

Returns `RetrievalResult(memories, active_policies, source_refs, retrieval_trace, token_budget)`.

### Memory read providers

Memory read providers are **read-only** (`get`, `list`, `search`). There are no
write methods (`create`, `update`, `delete`) on the read surface. All
active-memory mutations go through proposal approval and the server proposal apply
boundary.

---

## 4. Context assembly (`server/src/modules/context/prepareService.ts` and `repository.ts`)

Security boundary: `space_id` and `user_id` are required. No cross-space reads.

```
ContextBuilder(db).build(
    space_id, user_id,
    workspace_id?, task_type?, capability_id?, session_id?,
    query?, agent_memory_policy?, agent_id?, run_id?,
    context_reason?, attachments?, workspace_path?
) -> ContextPackage
```

Responsibilities:
1. Delegates retrieval to `MemoryRetriever`
2. Records `memory_access_logs` (access_type=context_injection) for every injected memory
3. Resolves context attachments (file, file_range, git_diff, staged_diff, folder_tree, recent_commits)
4. Security-scans attachments via `scan_attachment()` / `scan_content()`
5. Loads latest `SessionSummary` for the session when `session_id` is provided
   through the sessions-owned `SessionSummaryPort`
   (`get_session_summary_port(...).get_latest_for_context(...)`; current
   implementation delegates to `SessionCondenser`)
6. Partitions memories into sections: user_memory, workspace_memory, capability_memory, agent_memory, system_policy, relevant_episodes
7. Produces `ContextPackage` with stable_prefix_refs / dynamic_tail_refs split

`recent_session_summary` is populated from `SessionSummary` rows (derived context, **not** MemoryEntry).

### Session summary source traceability

When a `SessionSummary` is loaded, `ContextBuilder` records:

- A `source_ref` entry appended to **both** `source_refs` and `dynamic_tail_refs`:
  ```json
  {
    "source_type": "session_summary",
    "source_id": "<summary.id>",
    "session_id": "<session_id>",
    "version": <summary.version>,
    "section": "dynamic_tail",
    "derived_context": true
  }
  ```
- A `retrieval_trace["session_summary"]` entry:
  ```json
  {
    "session_summary_used": true,
    "session_summary_id": "<summary.id>",
    "session_summary_version": <version>,
    "session_summary_fallback_reason": null
  }
  ```
  If lookup fails or no active summary exists, `session_summary_used=false` and `session_summary_fallback_reason` is set.

---

## 4a. Chat context — Personal Assistant path (`server/src/modules/agents/chatContextBuilder.ts`)

The existing `ContextBuilder` (§4 above) handles the CLI agent path: it produces a `ContextPackage`
rendered by `ContextCompiler` into an instruction file.  The chat context path is different:

- Input is a `ContextRequest` (not `ContextBuildRequest`)
- Output is a `ContextBundle` (not `ContextPackage`) — a flat list of `ContextBundleItem` records
- Each item carries `item_type`, `item_id`, `title`, `excerpt`, `score`, `reason`, `token_count`
- The bundle is intended to be injected directly into a model call (no instruction-file rendering)
- Result is persisted as `ContextSnapshot` + `ContextSnapshotItem` rows for full auditability

### Context boundary: AgentVersion.context_policy_json

`ChatContextBuilder` reads `AgentVersion.context_policy_json` to determine which source types
are allowed for a given request. **AgentVersion is never mutated** — all per-run selection
decisions are local to `build()` and stored only in `ContextBundle` / `ContextSnapshot`.

`context_policy_json` structure:

```json
{
  "sources": ["memory", "knowledge_item", "workspace", "activity_record"],
  "max_tokens": 4000,
  "max_items": 20
}
```

- `sources` — allowed source types; absent / empty → all types allowed (permissive default)
- `max_tokens` — overrides the per-request budget when set
- `max_items` — overrides the per-request item cap when set

Supported `item_type` values in a `ContextBundle` / `ContextSnapshotItem`:

| item_type | Source table |
|-----------|-------------|
| `memory` | `memory_entries` (via `MemoryRetriever`) |
| `knowledge_item` | `knowledge_items` (item_type ≠ idea) |
| `idea` | `knowledge_items` (item_type = idea) |
| `source` | `sources` (status = processed) |
| `activity_record` | `activity_records` (recent-first) |
| `workspace` | `workspaces` (current workspace metadata) |
| `project` | `projects` (current project metadata) |
| `manual_context` | Caller-supplied explicit context (highest priority) |
| `task`, `run`, `proposal`, `artifact` | Reserved; not yet selected automatically |

### Selection priority

```
1. manual_context       (score=1.0, always first)
2. workspace metadata   (score=0.9, current workspace only)
3. project metadata     (score=0.9, current project only)
4. approved memory      (score=0.8, via server memory/context repositories)
5. knowledge_item/idea  (score=0.7, recent-first + keyword filter)
6. source               (score=0.6, processed, recent-first)
7. activity_record      (score=0.5, recent-first)
```

Deduplication by `(item_type, item_id)` is applied across all sources. Token budget and
max_items caps stop collection once either limit is reached (`truncated=True`).

### API

```ts
const collector = new ChatContextCandidateCollector(repo);
const candidates = await collector.fetchCandidates(request);
const bundle = buildChatContext(candidates);

await contextSnapshotRepository.persistChatSnapshot({
  contextSnapshotId,
  spaceId,
  tokenEstimate: bundle.token_count,
  requestJson,
  items: bundle.items,
});
```

Snapshot persistence owns its SQL statement boundaries; callers own larger
workflow orchestration.

### ContextSnapshot additions

`context_snapshots` now carries three new nullable columns:
- `agent_id` — FK to `agents.id` (derived from `AgentVersion.agent_id` by the builder)
- `session_id` — FK to `sessions.id` (from `ContextRequest.session_id`)
- `run_id` — FK to `runs.id` (from `ContextRequest.run_id`; avoids circular FK via ALTER TABLE)
- `request_json` — serialised `ContextRequest` for full audit reproducibility

All three FKs use `use_alter=True` because `context_snapshots` is created before the
referenced tables in the baseline migration.

### Not implemented (future scope)

- Embeddings / vector search (no numpy, faiss, pgvector)
- Graph traversal beyond what MemoryRetriever already provides
- Source chunking pipeline
- Full workspace file search
- Frontend context picker UI

---

## 5. SessionSummary and Session Condensing

Context assembly consumes the context-safe `SessionSummaryForContext` DTO from
the sessions module. Summary condense/create writes are deferred; context code
must continue to consume the DTO boundary instead of reaching into session
internals.

### Design invariants

- `SessionSummary` is **derived context**, not active memory. It is never a `MemoryEntry`.
- `SessionCondenser.condense()` **never** creates a `Proposal` or `MemoryEntry`.
- Multiple summaries per session are versioned; old ones become `status="superseded"`.
- `version` is unique per session (`uq_session_summaries_session_version` constraint).
- **At most one active summary per session** — enforced by partial unique index `ix_session_summaries_one_active_per_session` on `(session_id) WHERE status = 'active'`.

### SessionSummary (`session_summaries`)

| Column | Purpose |
|--------|---------|
| `session_id` | FK to Session |
| `space_id` | Scope boundary |
| `user_id` | Who was in the session |
| `version` | Monotonic per session; unique per (session_id, version) |
| `status` | `active` or `superseded` |
| `summary_text` | Condensed plaintext |
| `source_message_count` | How many messages were condensed |
| `source_first_message_id` | First message id in the condensed range |
| `source_last_message_id` | Last message id — watermark for incremental condensing |
| `summary_json` | Structured metadata: role_counts, top_keywords, source_range, condenser_version |
| `token_estimate_before` | Approximate token count of source messages (chars ÷ 4) |
| `token_estimate_after` | Approximate token count of summary_text (chars ÷ 4) |
| `condenser_version` | `pattern.v1` (pattern-based; LLM condensing is deferred) |

**Indexes:** `(session_id, status)`, `(space_id, session_id, status)`, partial unique `(session_id) WHERE status = 'active'`.

### SessionCondenser

```
SessionCondenser(db).condense(session_id, space_id) -> SessionSummary
SessionCondenser(db).get_latest(session_id, space_id) -> SessionSummary | None
```

- Queries messages filtered by **both** `session_id` and `space_id`.
- Fills all source range fields (`source_first_message_id`, `source_last_message_id`, `source_message_count`).
- Populates `summary_json` with structured metadata (role counts, top keywords, condenser_version, source range).
- Estimates `token_estimate_before` (source chars ÷ 4) and `token_estimate_after` (summary chars ÷ 4).
- Uses pattern-based heuristics (no LLM). Future: LLM-based condensing with `condenser_version="llm.v1"`.

---

## 6. ContextCompiler (`server/src/modules/context/compiler.ts`)

Translates `ContextPackage` → CLI instruction file (CLAUDE.md / AGENTS.md / etc.) in the sandbox directory.

### Section priority and budget enforcement

Sections ordered by priority (lower = more important = last to drop). The
prepared run path uses `stable_prefix` / `dynamic_tail`; the older raw
`ContextPackage` path uses the per-scope sections below.

| Priority | Section | Mandatory | Per-section cap |
|----------|---------|-----------|----------------|
| 0 | task | **yes** | none |
| 1 | stable_prefix | no | — |
| 1 | system_policy | no | 16 000 chars |
| 1 | policy | no | — |
| 2 | user_context | no | 8 000 chars |
| 3 | project_docs | no | 24 000 chars |
| 4 | workspace | no | 12 000 chars |
| 5 | capability | no | — |
| 6 | agent | no | 8 000 chars |
| 7 | attachments | no | 16 000 chars |
| 8 | episodes | no | 4 000 chars |
| 8 | dynamic_tail | no | — |
| 9 | session | no | 2 000 chars |
| 10 | tools | no | — |
| 11 | sandbox | no | — |
| 12 | validation | no | — |
| 13 | constraints | no | — |
| 14 | output_format | no | — |

**Mandatory sections** are never dropped even when the total budget is exceeded.

**Per-section caps** truncate oversized sections before they enter the budget loop (with a `[truncated]` trailer). Truncation is recorded in `budget_trace`.

**`budget_trace`** (returned in `CompiledContext`): records mandatory sections,
capped sections (with original/capped sizes), compacted sections, and dropped
sections.

### ContextCompiler.budget_trace vs ContextSnapshot token_budget_json

These are **distinct** — do not conflate them:

| Field | Source | Contents |
|-------|--------|---------|
| `CompiledContext.budget_trace` | `ContextCompiler.compile()` | Compiler-level section budget: mandatory / capped / dropped section names and sizes |
| `ContextSnapshot.token_budget_json` | `ContextPrepareService` | Run-level stable_prefix / dynamic_tail character counts and percentage metrics |

`ContextSnapshot.token_budget_json` is **not** the compiler `budget_trace`. It is the populator's own measurement of stable_prefix vs dynamic_tail allocation. Future work may persist `budget_trace` into `ContextSnapshot` under a nested key (e.g., `compiler_budget_trace`); this is not yet implemented.

---

## 7. ContextDigest and context digest service (`server/src/modules/context/`)

Versioned derived cache of approved Memory + Policy content. **Not a source of truth.**

Supported `digest_type` values: `policy_bundle`, `workspace`, `agent`.

Lifecycle:
1. Not auto-generated. Must be seeded by explicit `generate_*()` call.
2. `generate_*()` — idempotent: same source_hash → return existing digest unchanged.
3. `mark_*_dirty(...)` — no-op if no active digest. Called by
   `ProposalApplyService` inside the proposal-apply transaction.
4. Generation and dirty-marking take the same per-digest
   `pg_advisory_xact_lock` key (`policy_bundle:<space>`,
   `workspace:<space>:<workspace_id>`, `agent:<space>:<agent_id>`) so a refresh
   cannot reactivate a stale digest after a concurrent change marked it dirty.
5. Dirty digests are loaded for traceability, but are dropped at prepare time and
   never injected. Regeneration is explicit.

Workspace/agent digest generation also verifies the target scope is still
`status='active'` in the same space and locks that row `FOR UPDATE`; explicit
refreshes/jobs fail closed for archived or missing scopes.

### Digest consumption

`ContextPrepareService` uses a digest only when it is usable:

- `policy_bundle`: status is `active`.
- `workspace` / `agent`: the run agent's `readable_scopes` includes the digest
  scope, status is `active`, and every claimed `source_memory_ids_json` id still
  revalidates against live `memory_entries` for the same space/scope, active,
  undeleted, shared visibility, and non-`highly_restricted`.

A digest is dropped when it is dirty, out-of-scope for `readable_scopes`, has
malformed/missing source metadata for non-empty content, or claims any stale or
ineligible source memory. Dropped digest content does not enter
`stable_prefix`, `source_refs_json`, snapshot digest version fields, or digest
memory read logs; the relevant section falls back to direct retrieval / direct
active policies.

### Context digest refresh

Explicit refresh gate. Regenerates a dirty (or stale) digest by calling the appropriate `generate_*()` method.

```
ContextDigestRefreshService(db).refresh(space_id, scope_type, scope_id, digest_type) -> ContextDigest
ContextDigestRefreshService(db).refresh_all_dirty(space_id) -> list[ContextDigest]
```

Never writes `MemoryEntry`, `Proposal`, or `Policy`.

### Digest refresh API validation

`POST /api/v1/context/digests/refresh` — `DigestRefreshRequest` enforces:

- `extra="forbid"`: unknown fields return 422.
- Empty object `{}` refreshes all dirty digests in the space.
- `scope_type` and `digest_type` must be provided together (neither alone).
- `digest_type` must be one of `policy_bundle`, `workspace`, `agent`.
- `digest_type="workspace"` or `"agent"` → `scope_id` required.
- `digest_type="policy_bundle"` + `scope_type="space"` → `scope_id` may be null.

---

## 8. Context Snapshot Population

Called immediately before adapter execution. server `ContextPrepareService` /
`PgRunContextRepository` builds and persists the run's `ContextSnapshot` row.

**Policy gate:** `context.inject_memory` is checked at the start of server context
prepare, before memory retrieval. Cross-space memory injection without a
`PersonalMemoryGrant` fires the hard invariant → DENY. A DENY stops context
population and propagates as a run failure. No memory is retrieved or injected
after a DENY.

Stable prefix strategy:
- Resolves `ContextDigest` rows for space / workspace / agent via
  `loadDigestBundle()`, then filters them through the usable-digest rules above
- Falls back to direct `MemoryRetriever` / direct active policies when a digest
  is missing, dirty, out-of-scope, malformed, or stale
- SHA-256 hashes stored in `ContextSnapshot.prefix_hash` / `tail_hash`
- Compiler version: `context_digest.v1`

Stores in `ContextSnapshot`:
- `source_refs_json` — direct source refs plus usable digest refs only
- `retrieval_trace_json` — stage-by-stage trace from MemoryRetriever plus digest
  fields (`digest_used`, `digest_types`, `digest_versions`, `digest_dropped`,
  `digest_missing_types`, `fallback_to_memory_retriever`)
- `token_budget_json` — run-level stable_prefix / dynamic_tail character metrics (NOT `ContextCompiler.budget_trace`)

---

## 9. ProposalApplyService (`server/src/modules/proposals/applyService.ts`)

**Primary durable write boundary** for accepted proposals. Supports two additional write paths with explicit provenance controls (see write boundary table in section 1).

**Defense-in-depth gate:** `apply()` requires `accept_context` in `{"explicit_user_accept", "internal_seed"}`. Unrecognized `accept_context` without `bypass_source_monitoring=True` raises `ProposalApplyError`. Proposal payloads with approval-proof flags (`approved_by_user`, `approved_by_granting_user`, etc.) are rejected by `HardInvariantGuard._payload_flags_not_approval_proof` before reaching `apply()`.

Supported proposal types:
- `memory_create` → new active `MemoryEntry` (calls `MemoryInternalWriter.create_from_approved_proposal()`)
- `memory_update` → new version of existing memory, supersedes old
- `memory_archive` → sets `status="archived"` (no hard delete)
- `policy_change` → creates / supersedes `Policy` row
- `code_patch` -> dispatches through `ProposalApplierRegistry` to the memory-owned
  code-patch proposal applier
- `egress_review` → metadata-only update on `PersonalMemoryGrant`

After applying `memory_create` / `memory_update` / `memory_archive`:
- Calls the digest dirty-marker for affected workspace/agent memory scopes
- Calls `SourceMonitoringService.record_proposal_apply(...)` for provenance tracking

After applying `policy_change`:
- Marks only the `policy_bundle` digest dirty. Workspace/agent digests are
  memory-only and never embed policy content.

---

## 10. Policy enforcement inventory

| Gate | Location | When |
|------|---------|------|
| Hard memory filter | `server/src/modules/context/repository.ts` and memory repositories | Every retrieval query |
| Read authorization | `server/src/modules/memory/memoryReadAuth.ts` | Context assembly, direct reads |
| Policy-aware read gate | `server/src/modules/policy/decisionCore.ts` | Run context reads |
| Private memory placement | Policy hard invariant + memory applier | Memory proposal apply |
| Write authority boundary | `server/src/modules/proposals/applyService.ts` | Accepted proposals only |
| Agent memory scope | `agent_memory_policy.readable_scopes` | Context repository |
| Egress approval | `server/src/modules/proposals/applyService.ts` | PersonalMemoryGrant egress |
| Workspace root validation | `server/src/modules/workspaces/pathPolicy.ts` | Before workspace file access |
| Per-run execution lock | run worker/orchestration locking in `server/src/modules/runs/` | Run execution service |
| **context.inject_memory** | `PolicyGateway` in `server/src/modules/context/prepareService.ts` | Before context assembly |
| **context.render_for_runtime** | `PolicyGateway` in `server/src/modules/runs/orchestrationService.ts` | Before adapter execution |
| **proposal.create** | `PolicyGateway.enforce()` in proposals/workspace target modules | Before Proposal row insert |
| **proposal.apply** | `PolicyGateway.enforceProposalApply()` in `server/src/modules/proposals/applyService.ts` | Before accepted proposal side effects |
| ProposalApplyService accept_context | `server/src/modules/proposals/applyService.ts` | Defense-in-depth at apply() entry |

---

## 11. Deferred capabilities

- **Automation triggers**: `Automation` and `AutomationRun` support manual and schedule-triggered fire. Scheduled automations can carry same-space `AutomationCredentialGrant` pre-authorization. No external event trigger is implemented.
- **Vector/embedding search**: MemoryRetriever embedding stage is a stub that delegates to keyword.
- **Cross-space federation**: PersonalMemoryGrant exists but FederatedAccess / PublishProjection are not yet built.
- **LLM-based condensing**: SessionCondenser is pattern-based (`condenser_version="pattern.v1"`). Future: `condenser_version="llm.v1"`.
- **ContextCompiler budget_trace persistence**: `CompiledContext.budget_trace` is not yet persisted into `ContextSnapshot`. Future work may add it under `token_budget_json["compiler_budget_trace"]`.

---

## 12. Automation boundary

`AutomationService.create/update/fire()` use `PolicyGateway.enforce()`. Manual
fire creates a queued `Run(trigger_origin="automation")` and an
`AutomationRun` link; it does not execute the run synchronously or bypass
existing runtime gates.

Automation schema is intentionally folded into canonical 0001 during foundation
hardening. No 0002 migration is expected for this branch.
