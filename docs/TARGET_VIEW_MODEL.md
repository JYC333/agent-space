# Target View Model

This document defines the seven concepts that form the space/ownership/visibility model.
Implementation status is noted for each concept.

---

## 1. Space

**Definition:** The primary collaboration and permission boundary. Every data record belongs to
exactly one space.

**Responsible for:**
- Scoping all queries and mutations (space_id filter is always first).
- Defining who may read, write, and manage data within it.
- Hosting workspaces, agents, sessions, runs, proposals, and memories.

**Must not:**
- Be treated as the complete "worldview" for a user (users may belong to many spaces).
- Grant access to data in other spaces.
- Be confused with a user identity or a user preference view.

**Current implementation status:** Existing and enforced. `Space` ORM model, `space_id` foreign
keys, and `MemoryRetriever` cross-space hard-filter are all active. Space type constraints
(`personal | household | team`) are enforced at the DB level.

---

## 2. Owner

**Definition:** The user or space entity that has primary stewardship over a data record.

**Responsible for:**
- `MemoryEntry.owner_user_id` — who authored / is responsible for a memory.
- Write-layer defaults: if a user creates private memory, they become the owner automatically.
- Determining whether a user may edit or delete a record (ownership ≠ visibility alone).

**Must not:**
- Be conflated with space membership role (`owner` role in `SpaceMembership` is a different concept).
- Be used as the sole access-control gate — visibility and scope also apply.
- Be inferred from `subject_user_id`; these fields have distinct semantics.

**Current implementation status:** Partial. `owner_user_id` column exists on `MemoryEntry`.
`MemoryStore.create()` assigns `owner_user_id` for private memories. `can_read_memory()` uses
`owner_user_id` as the primary gate for private and highly-restricted visibility. Full
ownership semantics for non-memory objects (runs, sessions, tasks) are not yet standardized.

---

## 3. Visibility

**Definition:** The declared audience for a memory or data record — who may read it.

**Responsible for:**
- Controlling read access at all layers (read_auth, retriever, context builder, API).
- Driving summary-only redaction for `summary_only` visibility.
- Distinguishing user-private from space-shared from workspace-scoped data.

**Must not:**
- Replace space membership checks (visibility applies within a space; space membership governs
  whether a user can access the space at all).
- Be stored without a corresponding `owner_user_id` when `visibility=private`.
- Allow `private` to be written to a non-personal space (rejected at write layer).

**Values (current):** `private | space_shared | workspace_shared | selected_users | summary_only |
restricted | public_template`

**Current implementation status:** Existing and enforced at read time (`can_read_memory()` in
`memory/read_auth.py`). Write-layer enforcement for `private` placement in personal spaces
only is active in `MemoryStore.create()`. Selected-user list semantics are partially
implemented (stored but not enforced beyond can_read_memory).

---

## 4. PersonalView

**Definition:** A cross-space aggregation perspective from a single user's viewpoint — their
personal feed, their memories across all their spaces, their participation records.

**Responsible for:**
- Aggregating data the user owns or has participated in, regardless of which space it lives in.
- Providing a "my world" lens without copying data out of its home space.
- Surfacing personal-space private memories alongside opted-in views of shared-space content.

**Must not:**
- Copy shared-space raw content into the user's personal space.
- Be confused with the personal *space* (PersonalView is a read aggregation; personal space is
  a write boundary).
- Bypass per-space visibility and access checks when presenting aggregated results.

**Current implementation status:** Future / not implemented. The frontend `SpaceContext`
currently tracks one active space at a time. There is no cross-space aggregation API or UI.
See `docs/FUTURE_ROADMAP.md`.

---

## 5. ExecutionContext

**Definition:** The per-run explicit scope that controls which memories and tools an agent run
may access.

**Responsible for:**
- Passing `user_id` (from `Run.instructed_by_user_id`) and `space_id` into `ContextBuilder`.
- Determining whether private memories are included (only when user_id matches owner_user_id).
- Scoping which workspaces, sandboxes, and credentials the run may use.

**Must not:**
- Allow cross-space memory reads (run reads only from `run.space_id`).
- Include another user's private memories regardless of which space the run operates in.
- Be widened without an explicit, documented authorization mechanism.

**Current implementation status:** Partial. `ContextSnapshotPopulator` resolves
`user_id = run.instructed_by_user_id or "system"` and passes it to `ContextBuilder`.
Private-memory gating via `user_id` is enforced in `MemoryRetriever`. A run in a shared
space cannot reach personal-space private memories by default — `PersonalMemoryGrant` is
the explicit authorization path when needed. See `docs/PERSONAL_MEMORY_GRANT.md`.

---

## 6. ParticipationRecord

**Definition:** A personal ledger entry recording that a user participated in a shared-space
activity (run, proposal, session, etc.) — without copying the raw shared content.

**Responsible for:**
- Giving the user a personal audit trail of their involvement in shared spaces.
- Allowing PersonalView to surface participation without duplicating shared data.
- Storing only a pointer (space_id, object_id, activity type) and the user's personal context.

**Must not:**
- Copy raw shared-space memory or content into a user's personal space.
- Be confused with `ActivityRecord` (ActivityRecord is the shared-space audit log;
  ParticipationRecord is the user's personal ledger of their own actions).
- Bypass the space ownership boundary of the referenced content.

**Current implementation status:** Future / not implemented. No table, model, or API exists.
Deferred until PersonalView concept is stabilized. See `docs/FUTURE_ROADMAP.md`.

---

## 7. SourcePointer / Federated Pointer

**Definition:** A lightweight cross-space reference that points to content in another space
without copying it. The old `context_sources` table was removed from the schema.

**Responsible for:**
- Recording provenance metadata: which object in `owner_space` references which object in
  `source_space` (`source_object_type`, `source_object_id`, `access_mode`).
- Future opt-in flows where explicit grants and policy checks authorize cross-space reads.
- Acting as the future mechanism for Gap 6a resolution (cross-space execution context).

**Must not:**
- Store raw source content, summaries, snapshots, or payloads.
- Grant read access by itself — `access_mode` values (`read`, `subscribe`, `federated`) are
  intent labels only until federation/grants are implemented.
- Activate `memory.cross_space_read` (that domain remains deferred / deny-by-default).
- Be implemented as a JOIN that bypasses `MemoryRetriever` space_id hard filters.

**Current implementation status:** `source_pointers` table, ORM model,
`app.source_pointers.service`, and membership-gated HTTP API (`/api/v1/source-pointers`).
Create/list/get/delete manage pointer metadata only; they do not resolve source content.
`granted_by_user_id` is server-assigned from the authenticated user (not client-writable).
`metadata_json` is bounded safe metadata only: content-bearing keys rejected recursively,
UTF-8 JSON byte cap, max string length, max total dict/list items, JSON-compatible types only.
SourcePointer rows do not grant cross-space reads, do not implement federation, and do not
enable public publishing. `PersonalMemoryGrant` is the separate explicit grant mechanism —
see `docs/PERSONAL_MEMORY_GRANT.md`. Federation and `visibility=public` remain deferred.
See `docs/SOURCE_POINTER.md` and `docs/FEDERATED_ACCESS_MODEL.md`.

**Note on federation:** Multi-deployment federation is explicitly deferred. See
`docs/FEDERATED_ACCESS_MODEL.md`.

---

## 8. PublishProjection

**Definition:** A future mechanism by which a user or space explicitly publishes a memory or
artifact as a public or cross-space template, making it discoverable outside its home space.

**Responsible for:**
- Providing a `source → proposal → public artifact` pipeline so publication is always
  intentional and audit-trailed.
- Supporting `visibility=public_template` as the resulting visibility state.
- Enabling future capability/template sharing across spaces or deployments.

**Must not:**
- Be implemented as a direct visibility flag flip without a proposal step.
- Allow bulk publication without explicit user review.
- Be confused with space_shared visibility (space_shared is intra-space; PublishProjection
  is cross-space or cross-deployment).

**Current implementation status:** Deferred — documented in `docs/PUBLISH_PROJECTION.md`.
The `public_template` visibility value exists in the schema and `can_read_memory()` gates it
behind `include_public_templates=True`, but there is no `visibility=public`, no publish
proposal apply path, and no UI. SourcePointer may later record provenance from published
artifacts back to sources without granting read access.

---

## Summary table

| Concept | Status |
|---|---|
| Space | Existing — enforced |
| Owner | Partial — `owner_user_id` exists; full ownership semantics incomplete |
| Visibility | Existing — read enforcement active; write enforcement for `private` active |
| PersonalView | Future — not implemented; see `docs/FUTURE_ROADMAP.md` |
| ExecutionContext | Partial — `instructed_by_user_id` flow active; cross-space auth via `PersonalMemoryGrant` |
| ParticipationRecord | Future — not implemented; see `docs/FUTURE_ROADMAP.md` |
| SourcePointer / Federated Pointer | Implemented — metadata API + service; reads/federation deferred |
| PublishProjection | Deferred — see `docs/PUBLISH_PROJECTION.md`; no `visibility=public` |
