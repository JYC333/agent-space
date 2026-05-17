# Policy Enforcement Inventory

Current state as of 2026-05-17. See `docs/POLICY_AND_PRIVACY_BOUNDARIES.md` for the
canonical stable reference. This file provides additional architectural detail for
agents and tools that operate on the `.agent` context tree.

## Legend

| Symbol | Meaning |
|--------|---------|
| ✅ Enforced | Code path actively checks and rejects violations |
| 📄 Documented | Gap is recorded; enforcement deferred |
| ❌ Not enforced | No check exists; behavior is undefined or permissive |

---

## Canonical policy query

**Helper:** `app.policy.access.load_active_policy_rows()` — single query shape for active rows (`enabled`, `status=active`, priority desc, created_at desc, id desc).

**Domain decisions:** `get_active_policy_match()` / `get_active_policy_decision()` — filter in Python via `_row_matches_domain()`.

**PolicyEngine persisted class:** `load_active_policies_for_write_direct()` — same canonical loader + `row_matches_write_direct()`.

Space membership role checks (`app.auth.policy`) remain separate from persisted Policy rows.

---

## Policy decision tracing (`allow_with_log` / deny)

**Mechanism:** Structured logging via `app.policy.trace.record_policy_decision_trace()` (logger `app.policy.trace`).

**Not persistent:** No dedicated policy-audit DB table yet; traces are JSON log lines. Memory content is never included.

**Emitted at enforcement points when:**

| Domain | allow_with_log | deny |
|--------|----------------|------|
| `memory.private_placement` | Safe writes (incl. non-private with active row; private in personal) | Non-personal private (hard invariant + policy deny) |
| `run.user_private_scope` | Same-space instructed-user private included in run retrieval | Same-space private excluded |
| `memory.cross_space_read` | N/A (deferred) | Cross-space attempt blocked (even if policy says allow/allow_with_log) |

Retrieval hard-filter metadata remains in `retrieval_trace_json` on context packages; policy traces are separate log events.

---

## memory.write_direct

**Status:** ✅ Enforced

- `MemoryInternalWriter` → `PolicyEngine.assert_allowed()` with `MEMORY_WRITE_DIRECT` constant.
- Persisted rows matched via canonical loader + `row_matches_write_direct()`.
- Tests: `tests/invariants/test_memory_write_invariants.py`, `tests/unit/test_policy_engine.py`

---

## memory.private_placement

**Status:** ✅ Enforced

- Hard invariant: `visibility=private` only in `Space.type == personal`.
- Enforcement: `MemoryStore.create()` → `check_private_memory_placement()`
- Policy trace on allow_with_log / deny / hard-invariant denial.
- Tests: `tests/invariants/test_private_memory_placement.py`, `tests/invariants/test_policy_enforcement_inventory.py`, `tests/contracts/test_memory_write_governance.py`

---

## run.user_private_scope

**Status:** ✅ Enforced

- Same-space private memory for `owner_user_id == instructed user_id`.
- Active deny excludes same-space private; trace on deny/allow_with_log.
- Cross-space personal private in shared runs: requires `PersonalMemoryGrant`.
- Enforcement: `MemoryRetriever` → `can_read_memory_in_run_context()`
- Tests: `tests/invariants/test_execution_context_private_scope.py`, `tests/invariants/test_policy_enforcement_inventory.py`

---

## memory.cross_space_read

**Status:** 📄 Deferred — deny by default

- Structural `space_id` filter; allow/allow_with_log rows do not enable reads.
- Cross-space block traced when an allow-looking policy exists.
- **SourcePointer** stores provenance metadata only; does **not** activate this domain.
- **PersonalMemoryGrant** is the explicit exception path; see `docs/PERSONAL_MEMORY_GRANT.md`.
- Future: explicit grants + federation + policy (see `docs/FEDERATED_ACCESS_MODEL.md`).
- Tests: `tests/invariants/test_policy_enforcement_inventory.py`,
  `tests/invariants/test_space_isolation.py`,
  `tests/invariants/test_source_pointer_access_boundary.py`

---

## SourcePointer (provenance metadata)

**Status:** ✅ Schema + service + API — **no read grant**

- Table `source_pointers`; service `app.source_pointers.service`; HTTP `app.source_pointers.api`.
- `access_mode` in (`read`, `subscribe`, `federated`) — intent labels only; DB check constraint.
- **API membership:** create requires member of owner + source space; list/get require owner-space
  membership; delete requires admin/owner in owner space.
- `granted_by_user_id` server-assigned on create (not in request body; `extra=forbid` on schema).
- `metadata_json` rejects content-bearing keys recursively (case-insensitive; service layer)
  and enforces bounded safe metadata (16 KiB UTF-8 JSON, depth 8, ≤256 dict/list items,
  key ≤128 chars, string ≤2048 chars; tuple/set/bytes rejected). Pointer rows never store
  source content and do not grant read access.
- Does **not** activate `memory.cross_space_read`; does **not** bypass `can_read_memory` or federation.
- Tests: `tests/contracts/test_source_pointer_api.py`,
  `tests/unit/test_source_pointer_service.py`,
  `tests/invariants/test_source_pointer_access_boundary.py`,
  `tests/unit/test_canonical_schema.py`

---

## Policy table wiring summary

| Domain | Runtime wired | Tracing |
|--------|---------------|---------|
| `memory.write_direct` | PolicyEngine | Not yet (engine uses allow/deny/require_approval only) |
| `memory.private_placement` | Yes | Structured log |
| `run.user_private_scope` | Yes | Structured log |
| `memory.cross_space_read` | Structural deny only | Structured log on blocked cross-space with allow-looking row |

Malformed effects on security-sensitive domains fail safe → **deny** (`get_active_policy_match`).

---

## Space isolation

**Status:** ✅ Enforced at data layer — `tests/invariants/test_space_isolation.py`

---

## Publish / public visibility

**Status:** 📄 Deferred — see `docs/PUBLISH_PROJECTION.md`

- No `visibility=public`; proposal type `publish` not in `_SUPPORTED_ACCEPT_TYPES`.

---

## PersonalMemoryGrant (current MVP complete)

**Status:** MVP complete (2026-05-17). **No further backend scope expansion without a new design.**

- `personal_memory_grants` and `personal_memory_grant_events` tables in baseline migration.
- `memory.cross_space_read` remains `deny-by-default` for normal retrieval path.
- **Grant API** (`app.personal_memory_grants`): preview, create, list, revoke, audit — active.
- **Resolver** (`app.personal_memory_grants.resolver`): grant lifecycle, cross-space read, summary generation — active.
- **ContextSnapshotPopulator**: `personal_context_block` ephemeral; only safe metadata in source_refs — active.
- **Run egress marker** (`Run.has_personal_grant_context`, `Run.personal_grant_context_json`):
  - Set by `ContextSnapshotPopulator.populate()` when resolver successfully produces a personal context block.
  - `personal_grant_context_json` stores only safe metadata: grant ID, space IDs, memory count, boolean safety flags.
  - Never stores raw memory text, generated summary, or memory IDs.
- **Egress guard** (`app.personal_memory_grants.egress_guard`):
  - `check_personal_memory_egress(db, run, target_space_id, …)` — returns `EgressCheckResult(ALLOW | BLOCK)`.
  - Detection: `run.has_personal_grant_context == True` OR output_metadata contains grant-derived indicator keys.
  - Fails closed for unknown target spaces (treated as non-personal → BLOCK).
  - Hard block: `raw_private_memory_included` in metadata → BLOCK.
  - Hard block: `target_visibility == "public"` → BLOCK.
  - Non-personal target → BLOCK with egress_review required.
  - Personal target → ALLOW.
  - Non-grant-derived output → ALLOW (existing behavior unchanged).
  - Writes safe `denied` event to `personal_memory_grant_events` on block.
- **Enforcement points**:
  - `RunOutputMaterializer._artifact_from_spec()`: blocks grant-derived artifact creation in non-personal spaces.
  - `RunOutputMaterializer._memory_update_proposal()`: blocks grant-derived memory proposal creation in non-personal spaces.
  - `ArtifactPersistenceService.persist_text_file()` / `persist_copied_file()`: blocks grant-derived file artifact persistence in non-personal spaces.
  - `MemoryProposalApplier.apply_create()` (defense-in-depth): blocks proposal apply for grant-derived source runs targeting non-personal spaces.
  - `MemoryProposalApplier.apply_update()` (defense-in-depth): mirrors apply_create() guard for update proposals.
  - `create_source_pointer()` (`app.source_pointers.service`): blocks SourcePointer with grant-derived indicator keys for non-personal `owner_space_id`.
- **Code patch risk labeling** (`RunOutputMaterializer._code_patch_proposal()`): code patch proposals from grant-derived runs are not blocked but carry explicit risk metadata and elevated `risk_level = "high"`.
- **Proposal approval gate**:
  - `proposal_approvals` table stores first-class metadata-only approval rows.
  - MVP approval type: `egress_granting_user`; MVP statuses: `approved`, `revoked`.
  - `app.proposals.approvals` records and validates granting-user approvals. Only `PersonalMemoryGrant.granting_user_id` may record `egress_granting_user`; space admins/owners cannot approve on behalf of the granting user.
  - `ProposalApplyService` requires a valid `proposal_approvals` row before applying `egress_review` proposals or grant-derived proposals to non-personal targets.
  - Payload flags such as `approved_by_granting_user` are never treated as proof of approval.
  - Revoked, failed, or expired grants block apply.
  - `raw_private_memory_included=true`, `personal_summary_persisted=true`, and public target visibility block apply.
- **Runtime adapter injection** (`RunExecutionService._execute_real_adapter_path`):
  - Appends `personal_context_block` to the adapter prompt only in memory, with a reasoning-only warning and delimiters.
  - Does not mutate `Run.prompt`, `AgentVersion.system_prompt`, `ContextSnapshot.*`, `source_refs_json`, or `retrieval_trace_json`.
  - Adds safe `Run.output_json.output_provenance` metadata for grant-derived runs.
  - Redacts the exact transient `personal_context_block` from persisted run output before storage.
  - Direct artifact, memory proposal, produced file, and SourcePointer persistence remains blocked/gated by existing guard paths.
- **Frontend UI flow**:
  - `RunDetailPage` exposes a Personal context panel after a run exists.
  - UI shows no raw personal memory, summaries, memory IDs, or `personal_context_block`.
  - Proposal list/detail surfaces grant-derived egress status; approval button only for `currentUserId == required_approver_user_id`.
  - Space admins/owners get no override UI; `proposal_approvals` rows remain the source of truth.
  - Copy: "used for reasoning only" / "Approve egress review" / "approval does not create shared content."
- **Egress review proposal creation** (`app.personal_memory_grants.egress_review`):
  - `create_egress_review_proposal()` creates a metadata-only `egress_review` proposal when artifact or memory-proposal materialization is blocked.
  - Payload: safe grant/run metadata and boolean safety flags only. No output text, raw memory, summaries, memory IDs.
  - Deterministic dedupe: `egress_review_dedupe_key` (IDs + operation only) stored in payload; matched in Python after bounded ORM-column query.
  - SourcePointer remains hard-blocked without egress_review proposal (not changed).
  - Applying an egress_review proposal is metadata-only in current MVP; no shared artifact/memory created automatically.
- **Concurrency safety**: atomic conditional UPDATE ensures at most one caller claims a grant.
- **Tests**: `tests/invariants/test_personal_memory_egress_guard.py` (22 tests),
  `tests/invariants/test_personal_memory_egress_approval_gate.py` (11 tests),
  `tests/invariants/test_personal_memory_grant_boundary.py` (10 tests, 0 xfail),
  `tests/workflows/test_personal_memory_grant_run_context_workflow.py`,
  `tests/workflows/test_personal_memory_grant_egress_review_workflow.py`,
  `tests/contracts/test_personal_memory_grant_api.py`.

---

## Remaining deferred items

1. Semantic leakage detection for grant-derived output. Exact `personal_context_block` echoes are redacted; paraphrased/inferred personal-memory meaning must be reviewed manually.
2. Shared persistence pipeline from approved egress_review: applying an egress_review proposal is metadata-only. Future phase required for full shared-content apply.
3. Publish proposal apply + redaction pipeline.
4. Federation remote fetch (see `docs/FEDERATED_ACCESS_MODEL.md`).
5. `GET /api/v1/spaces/{space_id}/grant-stats`: space admin aggregate grant statistics endpoint. Deferred. Must return safe aggregate counts only.
6. Consuming-only sub-limit: MVP enforces combined active+consuming cap of 10. Separate consuming-only cap of 3 deferred.
