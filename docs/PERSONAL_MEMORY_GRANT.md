# PersonalMemoryGrant

## Purpose

PersonalMemoryGrant is an explicit, narrow, auditable mechanism that allows a user to
authorize a single shared-space run to use a summary of selected personal-space private
memories as reasoning-only context.

The safe default is unchanged: a shared-space run cannot read personal-space private
memory without an explicit grant. PersonalMemoryGrant is the only exception path and
provides no shared persistence of the personal memory content.

```
No grant → no cross-space personal memory read.
```

---

## Data Model

### `personal_memory_grants`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key |
| `granting_user_id` | UUID FK users | Server-assigned from authenticated user; not client-writable |
| `personal_space_id` | UUID FK spaces | Server-assigned from granting user's personal space |
| `target_space_id` | UUID FK spaces | The shared space where the target run executes |
| `target_run_id` | UUID FK runs | Required in MVP; run-scoped grants only |
| `target_agent_id` | UUID FK agents | Always NULL in current MVP; agent-level grants deferred |
| `grant_scope` | TEXT | `run` only in current MVP |
| `access_mode` | TEXT | `summary_only` only in current MVP |
| `memory_filter_json` | JSON | Optional filter specifying namespaces, layers, kinds, max_items |
| `status` | TEXT | `active \| consuming \| used \| revoked \| expired \| failed` |
| `read_expires_at` | TIMESTAMP | Required; grant is invalid after this time |
| `egress_review_expires_at` | TIMESTAMP | Optional deadline for egress review/apply |
| `consume_started_at` | TIMESTAMP | Set when resolver claims the grant atomically |
| `used_at` | TIMESTAMP | Set when grant transitions to `used` |
| `revoked_at` | TIMESTAMP | Set on explicit user revoke |
| `failed_at` | TIMESTAMP | Set on resolver failure after memory was accessed |
| `failure_stage` | TEXT | Diagnostic stage label for failed grants |
| `created_at` | TIMESTAMP | Creation time |

**Uniqueness:** at most one `active` or `consuming` grant per `(target_run_id, granting_user_id)`.

### `personal_memory_grant_events`

Audit log for all grant lifecycle transitions. Contains `grant_id`, `event_type`,
`event_data_json` (safe metadata only, no personal memory content), `created_at`.

### `proposal_approvals`

First-class approval rows required before any egress-review proposal may be applied.
Stores `proposal_id`, `approval_type` (`egress_granting_user`), `approver_user_id`,
`grant_id`, `status` (`approved \| revoked`), approval metadata. No raw memory
content, summaries, or memory IDs.

---

## Grant Lifecycle

```
active → (atomic claim) → consuming → used      [normal path]
active → (explicit user revoke)  → revoked       [user cancels]
active → (expiry)                → expired        [time-based]
consuming → (failure after read) → failed         [terminal]
```

Status transitions are enforced at the service layer. The resolver uses an atomic
conditional UPDATE to claim the grant (`active → consuming`), preventing concurrent
double-consumption. If the claim returns no rows, the grant was already consumed,
revoked, or expired — context build aborts.

After the resolver reads personal memory and produces a summary, the grant transitions
`consuming → used`. If the resolver fails after accessing raw personal memory, the
grant transitions `consuming → failed` (never back to `active`).

---

## API Endpoints

All endpoints are under `/api/v1/personal-memory-grants`.

| Method | Path | Description |
|---|---|---|
| `POST` | `/preview` | Structural eligibility preview without creating a grant |
| `POST` | `/` | Create a grant for a specific run |
| `GET` | `/` | List grants for the authenticated user |
| `POST` | `/{grant_id}/revoke` | Revoke an active or consuming grant |
| `GET` | `/{grant_id}/audit` | Retrieve safe audit events for a grant |

**Server-assigned fields:** `granting_user_id` and `personal_space_id` are derived
server-side from the authenticated session. They are not client-writable
(`extra=forbid` on the request schema).

**Authorization checks at create:**
- Authenticated user must own the personal space.
- Authenticated user must be a member of `target_space_id`.
- `target_run_id` must be in `target_space_id`.
- `granting_user_id` must equal `run.instructed_by_user_id`.
- Rate limits and max active/consuming limits enforced (combined cap of 10 per user).

---

## Runtime Behavior

When `ContextSnapshotPopulator` detects a valid grant for the current run:

1. Atomically claims the grant (`active → consuming`).
2. Reads allowed personal memories from `personal_space_id` using the grant's filter.
3. Generates a `summary_only` digest — no raw memory text is retained.
4. Constructs an ephemeral `personal_context_block` (in memory only, never persisted).
5. Transitions the grant `consuming → used`.
6. Sets `Run.has_personal_grant_context = True` and `Run.personal_grant_context_json`
   with safe metadata only (grant ID, space IDs, memory count, boolean safety flags —
   no memory text, IDs, or generated summary).

The `personal_context_block` is appended to the adapter prompt **in memory only**,
with a reasoning-only warning and delimiters. It is not written to:
- `Run.prompt`
- `AgentVersion.system_prompt`
- `ContextSnapshot.compiled_prefix_text` / `compiled_tail_text`
- `ContextSnapshot.source_refs_json` / `retrieval_trace_json`

If the adapter echoes the exact `personal_context_block` in its output, the persisted
run output redacts that block before storage and materialization.

---

## Egress Guard

The egress guard runs before any persistence of run output to a non-personal target.

**Detection:** `run.has_personal_grant_context == True` OR output metadata contains
grant-derived indicator keys (`derived_from_personal_memory`, `personal_memory_grant_ids`).

**Hard blocks (always BLOCK regardless of other conditions):**
- `raw_private_memory_included` in output metadata → BLOCK
- `target_visibility == "public"` → BLOCK

**Non-personal target:** BLOCK with egress review required.

**Personal target:** ALLOW.

**Non-grant-derived output:** ALLOW (existing behavior unchanged).

On BLOCK, the guard writes a `denied` event to `personal_memory_grant_events` and
(for artifact and memory-proposal materialization) creates a sanitized metadata-only
`egress_review` proposal for the granting user to review.

### Egress Review Proposal

When artifact or memory-proposal materialization is blocked, a sanitized
`egress_review` proposal is created automatically.

**Payload contains only:** `source_run_id`, `target_space_id`, `target_object_type`,
`operation`, `grant_id`, `granting_user_id`, `personal_space_id`, `access_mode`,
`memory_count`, boolean safety flags, `required_approval_type`, `required_approver_user_id`,
semantic review status, a stable `egress_review_dedupe_key` (IDs + operation only, no content).

**Payload never contains:** output text, artifact content, raw memory, generated summary,
`personal_context_block`, memory IDs, source memory titles, artifact payload, public URL.

Dedupe prevents duplicate proposals for the same run + target + type + operation + grant.
The `egress_review_dedupe_key` is matched in Python after a bounded ORM-column query
(no SQLite JSON path operators).

**SourcePointer** remains hard-blocked without an egress_review proposal when grant-derived
indicator keys are present in metadata for non-personal owner spaces.

---

## Proposal Approval Gate

Applying an `egress_review` proposal or any grant-derived proposal to a non-personal
target requires a valid `proposal_approvals` row with:
- `approval_type = egress_granting_user`
- `approver_user_id = PersonalMemoryGrant.granting_user_id`
- `status = approved`

**Only the granting user may provide this approval.** Space admins and owners cannot
approve on behalf of the granting user. Payload metadata flags
(`approved_by_granting_user`, `granting_user_approved`, etc.) are never treated as
proof of approval.

Revoked, failed, or expired grants block apply. `used` grants remain valid for egress
review only for the same source run while the egress review deadline is still valid.

**Applying an egress_review proposal is metadata-only in the current MVP.** Approval
records permission to proceed to the next review step — no shared artifact or memory
is automatically created. A future phase would wire the full shared-content pipeline.

---

## UI Flow

The Run Detail page exposes a Personal context panel after a run has been created.
The panel allows the instructing user to:

- Preview structural grant eligibility (no raw memory shown).
- Create a `summary_only` grant after a run ID exists.
- View safe grant status metadata.
- Revoke active or consuming grants.
- Inspect safe audit events.

The Proposal list/detail page exposes egress review state to the granting user and
allows recording `egress_granting_user` approval when `currentUserId == required_approver_user_id`.

**UI invariants:**
- No raw personal memory text, generated personal summaries, memory IDs, or
  `personal_context_block` is shown in any shared-space UI surface.
- Grant description consistently says "used for reasoning only" — not "sharing personal memory."
- Egress review approval button says "Approve egress review"; supporting text clarifies
  that approval does not create shared content.
- Toast messages say "Egress review approval recorded."
- No multi-user, agent-level, space-level, or public grant UX is present.

---

## Security Invariants

These invariants are enforced at code level and covered by tests. They must never be weakened.

1. **No grant, no cross-space private memory.** A shared-space run without a valid grant cannot read personal-space private memory.
2. **User grants only their own memory.** `granting_user_id` is server-assigned from the authenticated user; a user cannot grant another user's memory.
3. **SourcePointer does not grant access.** A SourcePointer to personal memory does not allow shared-space run access.
4. **Highly restricted memories excluded.** `sensitivity_level = highly_restricted` memories are never readable through a grant.
5. **Grant is run-scoped.** A grant for Run A cannot be reused by Run B.
6. **One-time lifecycle.** `expired`, `revoked`, and `used` grants cannot be reused.
7. **No raw personal memory in shared targets.** Personal memory summaries used as runtime context are not written into team memory, shared artifacts, public artifacts, or SourcePointer metadata without explicit proposal + approval.
8. **Space admin cannot substitute for granting user.** Only `granting_user_id` may record `egress_granting_user` approval.
9. **Payload flags are not proof of approval.** Approval metadata in proposal payloads is never treated as a valid approval gate.
10. **Egress guard fails closed.** Unknown target spaces are treated as non-personal and trigger BLOCK.

---

## Current Limitations

- **Run-scoped only.** Agent-level and space-level grants are deferred.
- **One-time lifecycle.** Long-lived grants are deferred.
- **`summary_only` only.** `retrieval_context` access mode is deferred.
- **Server-derived granting fields.** `granting_user_id` and `personal_space_id` are not client-writable.
- **`schema_version = 1`** required for non-empty `memory_filter_json`.
- **Egress review is metadata-only.** Approved egress review does not automatically create a shared artifact or memory — a future phase is required for the full shared-content pipeline.
- **Semantic leakage detection is manual.** Exact `personal_context_block` echoes are redacted from persisted output, but paraphrased or inferred personal-memory meaning in egress-review proposals must be reviewed manually (`semantic_review_status: "not_performed"`).
- **No public publishing or federation.** `visibility=public` and cross-instance federation are not supported.
- **No multi-user grants.** Only single granting user per grant.
- **No admin grant-stats endpoint.** Aggregate grant statistics for space admins are deferred.

---

## Future Roadmap

See `docs/FUTURE_ROADMAP.md` for deferred items including:
- Full shared-content pipeline from approved egress_review
- Semantic leakage detection / redaction
- Long-lived grants
- Agent-level and space-level grants
- Multi-user grants
- Admin grant-stats endpoint

---

## See Also

- `docs/SPACE_MODEL.md` — space types and private memory definition
- `docs/SOURCE_POINTER.md` — SourcePointer metadata model
- `docs/POLICY_AND_PRIVACY_BOUNDARIES.md` — policy enforcement inventory
- `docs/FUTURE_ROADMAP.md` — future work
- `core/backend/app/personal_memory_grants/` — implementation
- `core/backend/app/proposals/approvals.py` — approval gate
- `core/backend/app/personal_memory_grants/egress_guard.py` — egress guard
- `core/backend/app/personal_memory_grants/egress_review.py` — egress review proposal creation
- `core/backend/tests/invariants/test_personal_memory_egress_guard.py`
- `core/backend/tests/invariants/test_personal_memory_egress_approval_gate.py`
- `core/backend/tests/invariants/test_personal_memory_grant_boundary.py`
