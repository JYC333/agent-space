# Memory / Context Runtime

> Source of truth for: MemoryEntry lifecycle, retrieval pipeline, ContextBuilder,
> ContextSnapshot population, ContextDigest cache, ProposalApplyService write boundary,
> SessionCondenser, budget enforcement, and read_auth / policy enforcement points.

---

## 1. Core data model

### MemoryEntry (`models.py:MemoryEntry`)

Persistent, approved, scoped knowledge. Key invariants:

| Invariant | Enforcement |
|-----------|-------------|
| `status="active"` only through approved write paths | `_INTERNAL_WRITE_AUTHORITY` sentinel in `MemoryStore.create()`; no public update/delete methods |
| Scoped to one space | `space_id` FK; `MemoryRetriever._hard_filter_row()` enforces hard boundary |
| Private memory only in personal space | `check_private_memory_placement()` in `MemoryStore.create()` |
| Deleted rows invisible | `deleted_at IS NULL` filter in every retrieval query |

Key columns: `scope_type` (user / workspace / agent / system / capability), `memory_layer` (semantic / episodic / procedural), `visibility`, `status` (proposed / active / archived / superseded), `version`, `fitness_score`, `source_proposal_id`.

### Active memory write boundary

`MemoryStore.create()` raises `PermissionError` if called without the `_INTERNAL_WRITE_AUTHORITY` sentinel. The only caller that holds the sentinel is `MemoryInternalWriter._persist()`. There is no `MemoryStore.update()` or `MemoryStore.delete()`; all mutation operations after creation go through `MemoryInternalWriter` directly (ORM setattr + flush/commit).

**Allowed active-memory write paths:**

| Path | Entry point | source_proposal_id | source_trust | Notes |
|------|------------|-------------------|--------------|-------|
| Proposal apply | `ProposalApplyService.apply()` → `MemoryInternalWriter.create_from_approved_proposal()` | set | from proposal payload | Normal product write boundary |
| System seed / bootstrap | `MemoryInternalWriter.create_system_seed_memory()` | not set | `"internal_system"` | Bootstrap only; must not be called from product or agent paths |

There is no product direct-write memory path. The memory write boundary is structural and is not configurable through persisted Policy rows.

No route, run, condenser, retriever, context builder, activity processor, or agent output path may create active `MemoryEntry` directly.

---

## 2. Read authorization (`memory/read_auth.py`)

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

## 3. MemoryRetriever (`memory/retriever.py`)

Policy-aware retrieval pipeline. Called from `ContextBuilder` and `ContextSnapshotPopulator`.

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

### MemoryProvider / LocalMemoryProvider (`memory/provider.py`)

`MemoryProvider` is a **read-only** abstract interface (`get`, `list`, `search`). `LocalMemoryProvider` implements it against `MemoryStore`. There are no write methods (`create`, `update`, `delete`) on either class. All active-memory mutations go through `MemoryInternalWriter` via the proposal-approval boundary.

---

## 4. ContextBuilder (`memory/context_builder.py`)

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
5. Loads latest `SessionSummary` for the session when `session_id` is provided (via `SessionCondenser.get_latest()`)
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

## 5. SessionSummary and SessionCondenser (`sessions/condenser.py`)

### Design invariants

- `SessionSummary` is **derived context**, not active memory. It is never a `MemoryEntry`.
- `SessionCondenser.condense()` **never** creates a `Proposal` or `MemoryEntry`.
- Multiple summaries per session are versioned; old ones become `status="superseded"`.
- `version` is unique per session (`uq_session_summaries_session_version` constraint).
- **At most one active summary per session** — enforced by partial unique index `ix_session_summaries_one_active_per_session` on `(session_id) WHERE status = 'active'`.

### SessionSummary (`models.py:SessionSummary`)

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

## 6. ContextCompiler (`memory/context_compiler.py`)

Translates `ContextPackage` → CLI instruction file (CLAUDE.md / AGENTS.md / etc.) in the sandbox directory.

### Section priority and budget enforcement

Sections ordered by priority (lower = more important = last to drop):

| Priority | Section | Mandatory | Per-section cap |
|----------|---------|-----------|----------------|
| 0 | task | **yes** | none |
| 1 | system_policy | no | 16 000 chars |
| 2 | user_context | no | 8 000 chars |
| 3 | project_docs | no | 24 000 chars |
| 4 | workspace | no | 12 000 chars |
| 5 | capability | no | — |
| 6 | agent | no | 8 000 chars |
| 7 | attachments | no | 16 000 chars |
| 8 | episodes | no | 4 000 chars |
| 9 | session | no | 2 000 chars |
| 10 | tools | no | — |
| 11 | sandbox | no | — |
| 12 | validation | no | — |
| 13 | constraints | no | — |
| 14 | output_format | no | — |

**Mandatory sections** are never dropped even when the total budget is exceeded.

**Per-section caps** truncate oversized sections before they enter the budget loop (with a `[truncated]` trailer). Truncation is recorded in `budget_trace`.

**`budget_trace`** (returned in `CompiledContext`): records mandatory sections, capped sections (with original/capped sizes), and dropped sections.

### ContextCompiler.budget_trace vs ContextSnapshotPopulator.token_budget_json

These are **distinct** — do not conflate them:

| Field | Source | Contents |
|-------|--------|---------|
| `CompiledContext.budget_trace` | `ContextCompiler.compile()` | Compiler-level section budget: mandatory / capped / dropped section names and sizes |
| `ContextSnapshot.token_budget_json` | `ContextSnapshotPopulator` | Run-level stable_prefix / dynamic_tail character counts and percentage metrics |

`ContextSnapshot.token_budget_json` is **not** the compiler `budget_trace`. It is the populator's own measurement of stable_prefix vs dynamic_tail allocation. Future work may persist `budget_trace` into `ContextSnapshot` under a nested key (e.g., `compiler_budget_trace`); this is not yet implemented.

---

## 7. ContextDigest and ContextDigestService (`memory/digest_service.py`)

Versioned derived cache of approved Memory + Policy content. **Not a source of truth.**

Supported `digest_type` values: `policy_bundle`, `workspace`, `agent`.

Lifecycle:
1. Not auto-generated. Must be seeded by explicit `generate_*()` call.
2. `generate_*()` — idempotent: same source_hash → return existing digest unchanged.
3. `mark_digest_dirty(...)` — no-op if no active digest. Called by `ProposalApplyService`.
4. Dirty digests remain available for read (stale but useful). Regeneration is explicit.

### ContextDigestRefreshService (`memory/digest_refresh.py`)

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

## 8. ContextSnapshotPopulator (`runs/context_snapshot_populator.py`)

Called immediately before adapter execution. Builds and persists a `ContextSnapshot` row.

Stable prefix strategy:
- Resolves `ContextDigest` rows for space / workspace / agent via `_load_digest_bundle()`
- Falls back to direct `MemoryRetriever` when no digest available (records `fallback_reason` in retrieval_trace)
- SHA-256 hashes stored in `ContextSnapshot.prefix_hash` / `tail_hash`
- Compiler version: `context_digest.v1`

Stores in `ContextSnapshot`:
- `source_refs_json` — all source refs (memory IDs, policy IDs, digest IDs)
- `retrieval_trace_json` — stage-by-stage trace from MemoryRetriever
- `token_budget_json` — run-level stable_prefix / dynamic_tail character metrics (NOT `ContextCompiler.budget_trace`)

---

## 9. ProposalApplyService (`memory/apply_service.py`)

**Primary durable write boundary** for accepted proposals. Supports two additional write paths with explicit provenance controls (see write boundary table in section 1).

Supported proposal types:
- `memory_create` → new active `MemoryEntry` (calls `MemoryInternalWriter.create_from_approved_proposal()`)
- `memory_update` → new version of existing memory, supersedes old
- `memory_archive` → sets `status="archived"` (no hard delete)
- `policy_change` → creates / supersedes `Policy` row
- `code_patch` → delegates to `CodePatchProposalApplier`
- `egress_review` → metadata-only update on `PersonalMemoryGrant`

After applying `memory_create` / `memory_update` / `memory_archive`:
- Calls `ContextDigestService.mark_digest_dirty(...)` for affected workspace/agent/space scope
- Calls `SourceMonitoringService.record_proposal_apply(...)` for provenance tracking

---

## 10. Policy enforcement inventory

| Gate | Location | When |
|------|---------|------|
| Hard memory filter | `MemoryRetriever._hard_filter_row()` | Every retrieval query |
| Read authorization | `memory/read_auth.py:can_read_memory()` | ContextBuilder, direct reads |
| Policy-aware read gate | `policy/enforcement.py:can_read_memory_in_run_context()` | Run context reads |
| Private memory placement | `memory/store.py:check_private_memory_placement()` | MemoryStore.create() |
| Write authority sentinel | `memory/store.py:_INTERNAL_WRITE_AUTHORITY` | `MemoryStore.create()` only |
| Agent memory scope | `agent_memory_policy.readable_scopes` | MemoryRetriever + ContextBuilder |
| Egress approval | `proposals/approvals.py:validate_egress_granting_user_approval()` | PersonalMemoryGrant egress |
| Workspace root validation | `runs/preflight.py:validate_workspace_root_for_execution()` | Before run executes |
| Per-run execution lock | `runs/execution_lock.py:RunExecutionLockService` | RunExecutionService |

---

## 11. Deferred capabilities

- **Automation**: no AutomationTrigger, AutomationSchedule, or AutomationRun models. No automated run creation on schedule or event. See design direction below.
- **Vector/embedding search**: MemoryRetriever embedding stage is a stub that delegates to keyword.
- **Cross-space federation**: PersonalMemoryGrant exists but FederatedAccess / PublishProjection are not yet built.
- **LLM-based condensing**: SessionCondenser is pattern-based (`condenser_version="pattern.v1"`). Future: `condenser_version="llm.v1"`.
- **ContextCompiler budget_trace persistence**: `CompiledContext.budget_trace` is not yet persisted into `ContextSnapshot`. Future work may add it under `token_budget_json["compiler_budget_trace"]`.

---

## 12. Automation design direction

When Automation is built, the skeleton should:

1. **Models**: `AutomationTrigger` (type: manual / schedule / event), `AutomationRun` (FK to Run)
2. **Trigger → Run**: `AutomationService.fire(trigger_id, space_id, user_id)` creates a `Run` with `trigger_origin="automation"`, enqueues it via `DatabaseQueueService`
3. **ContextSnapshot**: populated by existing `ContextSnapshotPopulator` — no changes needed
4. **Output routing**: adapter output → `Artifact` (existing path) + optional `Proposal` (memory_create, via existing `ProposalApplyService`)
5. **Schedule**: cron-style schedule stored in `AutomationTrigger.schedule_json`; a lightweight scheduler job fires `AutomationService.fire()` at the right time
6. **API**: `POST /api/v1/automations` (create), `POST /api/v1/automations/{id}/run` (manual fire), `GET /api/v1/automations/{id}/runs` (history)

This path reuses Run / ContextSnapshot / ProposalApplyService entirely. No new agent workflow abstractions needed.
