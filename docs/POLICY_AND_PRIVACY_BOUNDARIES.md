# Policy and Privacy Boundaries

This document describes the current policy enforcement model, privacy boundaries, and
PersonalMemoryGrant enforcement points. It is the authoritative reference for what is
enforced today and what is deferred.

---

## Policy Infrastructure

### Canonical policy query

**Helper:** `app.policy.access.load_active_policy_rows()` — single query shape for
active rows (`enabled`, `status=active`, priority desc, created_at desc, id desc).

**Domain decisions:** `get_active_policy_match()` / `get_active_policy_decision()` —
filter in Python via `_row_matches_domain()`.

**PolicyEngine persisted class:** `load_active_policies_for_write_direct()` — same
canonical loader + `row_matches_write_direct()`.

Space membership role checks (`app.auth.policy`) remain separate from persisted Policy rows.

### Policy decision tracing

**Mechanism:** Structured logging via `app.policy.trace.record_policy_decision_trace()`
(logger `app.policy.trace`).

**Not persistent:** No dedicated policy-audit DB table; traces are JSON log lines.
Memory content is never included in traces.

Traces are emitted at enforcement points for:

| Domain | `allow_with_log` | `deny` |
|--------|------------------|--------|
| `memory.private_placement` | Safe writes (non-private with active row; private in personal) | Non-personal private (hard invariant + policy deny) |
| `run.user_private_scope` | Same-space instructed-user private included in retrieval | Same-space private excluded |
| `memory.cross_space_read` | N/A (deferred) | Cross-space attempt blocked even if policy says allow |

Retrieval hard-filter metadata is in `retrieval_trace_json` on context packages;
policy traces are separate log events.

---

## Enforced Policy Domains

### `memory.write_direct`

**Status:** Enforced

- `MemoryInternalWriter` → `PolicyEngine.assert_allowed()` with `MEMORY_WRITE_DIRECT` constant.
- Persisted rows matched via canonical loader + `row_matches_write_direct()`.
- Tests: `tests/invariants/test_memory_write_invariants.py`, `tests/unit/test_policy_engine.py`

### `memory.private_placement`

**Status:** Enforced

- Hard invariant: `visibility=private` only in `Space.type == personal`.
- Enforcement: `MemoryStore.create()` → `check_private_memory_placement()`
- Policy trace on allow_with_log / deny / hard-invariant denial.
- Tests: `tests/invariants/test_private_memory_placement.py`,
  `tests/invariants/test_policy_enforcement_inventory.py`,
  `tests/contracts/test_memory_write_governance.py`

### `run.user_private_scope`

**Status:** Enforced

- Same-space private memory for `owner_user_id == instructed user_id`.
- Active deny excludes same-space private; trace on deny/allow_with_log.
- Cross-space personal private in shared runs: not supported (requires PersonalMemoryGrant).
- Enforcement: `MemoryRetriever` → `can_read_memory_in_run_context()`
- Tests: `tests/invariants/test_execution_context_private_scope.py`,
  `tests/invariants/test_policy_enforcement_inventory.py`

### `memory.cross_space_read`

**Status:** Deferred — deny by default

- Structural `space_id` filter; allow/allow_with_log policy rows do not enable reads.
- Cross-space block traced when an allow-looking policy exists.
- SourcePointer stores provenance metadata only; it does not activate this domain.
- PersonalMemoryGrant is the explicit exception path (see below).
- Future: explicit grants + federation + policy (see `docs/FEDERATED_ACCESS_MODEL.md`).
- Tests: `tests/invariants/test_policy_enforcement_inventory.py`,
  `tests/invariants/test_space_isolation.py`,
  `tests/invariants/test_source_pointer_access_boundary.py`

---

## SourcePointer (Provenance Metadata)

**Status:** Implemented — no read grant

- Table `source_pointers`; service `app.source_pointers.service`; HTTP `app.source_pointers.api`.
- `access_mode` in (`read`, `subscribe`, `federated`) — intent labels only; DB check constraint.
- API membership: create requires member of owner + source space; list/get require owner-space
  membership; delete requires admin/owner in owner space.
- `granted_by_user_id` server-assigned on create (not in request body; `extra=forbid`).
- `metadata_json` rejects content-bearing keys recursively and enforces bounded safe metadata.
- Does not activate `memory.cross_space_read`; does not bypass `can_read_memory` or federation.
- Tests: `tests/contracts/test_source_pointer_api.py`,
  `tests/unit/test_source_pointer_service.py`,
  `tests/invariants/test_source_pointer_access_boundary.py`,
  `tests/unit/test_canonical_schema.py`

---

## PersonalMemoryGrant Enforcement Boundaries

PersonalMemoryGrant is the MVP for allowing a shared-space run to use personal-space
private memory as reasoning-only context. The current MVP is complete.

### Grant API and Lifecycle (`app.personal_memory_grants`)

- Preview, create, list, revoke, audit endpoints active.
- `granting_user_id` and `personal_space_id` server-derived; not client-writable.
- Rate limits and max active/consuming cap (10 combined) enforced at service layer.

### Resolver and ContextSnapshotPopulator (`app.personal_memory_grants.resolver`)

- Grant lifecycle enforced via atomic conditional UPDATE (`active → consuming`).
- Shared `ContextSnapshot` stores only non-content grant metadata.
- `personal_context_block` is ephemeral — built in memory, never persisted.
- `Run.has_personal_grant_context` and `Run.personal_grant_context_json` store safe
  metadata only (grant ID, space IDs, memory count, boolean safety flags).

### Egress Guard (`app.personal_memory_grants.egress_guard`)

`check_personal_memory_egress(db, run, target_space_id, …)` returns `EgressCheckResult(ALLOW | BLOCK)`.

Enforcement points where the egress guard is called:
- `RunOutputMaterializer._artifact_from_spec()` — blocks grant-derived artifact creation in non-personal spaces.
- `RunOutputMaterializer._memory_update_proposal()` — blocks grant-derived memory proposals in non-personal spaces.
- `ArtifactPersistenceService.persist_text_file()` / `persist_copied_file()` — blocks grant-derived file artifact persistence in non-personal spaces.
- `MemoryProposalApplier.apply_create()` — defense-in-depth: blocks proposal apply for grant-derived source runs targeting non-personal spaces.
- `MemoryProposalApplier.apply_update()` — defense-in-depth: mirrors `apply_create()` guard for update proposals.
- `create_source_pointer()` (`app.source_pointers.service`) — blocks SourcePointer with grant-derived indicator keys for non-personal `owner_space_id`.

Hard blocks: `raw_private_memory_included` in metadata → BLOCK; `target_visibility == "public"` → BLOCK.

Fails closed: unknown target spaces are treated as non-personal → BLOCK.

### Code Patch Risk Labeling

Code patch proposals from grant-derived runs are not blocked (human approval required
regardless). Instead, the proposal payload carries explicit risk metadata:
`personal_context_derived=true`, `egress_guard_required=true`, `requires_extra_review=true`,
`raw_private_memory_included=false`, `personal_summary_persisted=false`, plus grant/user IDs.
`risk_level` is elevated from `"low"` to `"high"`.

### Proposal Approval Gate (`app.proposals.approvals`)

- `proposal_approvals` table stores first-class metadata-only approval rows.
- MVP approval type: `egress_granting_user`; statuses: `approved \| revoked`.
- Only `PersonalMemoryGrant.granting_user_id` may record `egress_granting_user`; space
  admins/owners cannot approve on behalf of the granting user.
- `ProposalApplyService` requires a valid `proposal_approvals` row before applying
  `egress_review` proposals or grant-derived proposals to non-personal targets.
- Payload flags (`approved_by_granting_user`, etc.) are never treated as proof of approval.
- Tests: `tests/invariants/test_personal_memory_egress_approval_gate.py`

### Egress Review Proposal Creation (`app.personal_memory_grants.egress_review`)

When artifact or memory-proposal materialization is blocked:
- A sanitized metadata-only `egress_review` proposal is created for the granting user.
- Payload contains no output text, raw memory, generated summary, memory IDs, or personal context.
- Dedupe prevents duplicate proposals for the same run + target + type + operation + grant.
- Tests: `tests/workflows/test_personal_memory_grant_egress_review_workflow.py`

### Runtime Adapter Injection (`RunExecutionService._execute_real_adapter_path`)

- `personal_context_block` appended to adapter prompt in memory only with reasoning-only warning.
- Does not mutate `Run.prompt`, `AgentVersion.system_prompt`, `ContextSnapshot.*`, or `source_refs_json`.
- Exact `personal_context_block` echoes are redacted from persisted run output before storage.
- Output provenance metadata added: `derived_from_personal_memory=true`, boolean safety flags.
- Tests: `tests/workflows/test_personal_memory_grant_runtime_injection_workflow.py`

### Frontend UI

- Run Detail: personal context panel (preview, create, status, revoke, audit).
- Proposal list/detail: egress review state, approval button for granting user only.
- UI shows no raw personal memory, summaries, memory IDs, or `personal_context_block`.
- Copy distinguishes "used for reasoning only" from "will be shared."
- Approval wording: "Approve egress review" — explicitly states approval does not create shared content.

---

## Space Isolation

**Status:** Enforced at data layer — `tests/invariants/test_space_isolation.py`

All queries filter by `space_id` first. `MemoryRetriever` hard-filter prevents cross-space memory reads.

---

## Publish / Public Visibility

**Status:** Deferred — see `docs/PUBLISH_PROJECTION.md`

No `visibility=public`; proposal type `publish` not in `_SUPPORTED_ACCEPT_TYPES`.

---

## Policy Table Wiring Summary

| Domain | Runtime wired | Tracing |
|--------|---------------|---------|
| `memory.write_direct` | PolicyEngine | Not yet (engine uses allow/deny/require_approval only) |
| `memory.private_placement` | Yes | Structured log |
| `run.user_private_scope` | Yes | Structured log |
| `memory.cross_space_read` | Structural deny only | Structured log on blocked cross-space |

Malformed effects on security-sensitive domains fail safe → **deny** (`get_active_policy_match`).

---

## Current Hard Invariants (Never Weaken)

1. `visibility=private` memory only in `Space.type == personal`.
2. No cross-space memory read without a valid PersonalMemoryGrant.
3. SourcePointer does not grant read access.
4. `has_personal_grant_context` egress guard blocks non-personal shared persistence.
5. `personal_context_block` is never persisted in shared storage.
6. Only `granting_user_id` may record `egress_granting_user` approval.
7. Payload metadata is never treated as proof of approval.
8. `raw_private_memory_included=true` and `public` target visibility always BLOCK.
9. Egress guard fails closed on unknown target spaces.

---

## See Also

- `docs/SPACE_MODEL.md` — space types and private memory definition
- `docs/PERSONAL_MEMORY_GRANT.md` — PersonalMemoryGrant data model and lifecycle
- `docs/SOURCE_POINTER.md` — SourcePointer metadata model
- `docs/FUTURE_ROADMAP.md` — deferred enforcement work
- `core/backend/app/policy/` — PolicyEngine and tracing
- `core/backend/app/personal_memory_grants/` — grant service, resolver, egress guard
