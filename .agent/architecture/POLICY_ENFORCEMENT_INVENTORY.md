# Policy Enforcement Inventory

See `docs/POLICY_AND_PRIVACY_BOUNDARIES.md` for the canonical stable reference.
This file provides additional architectural detail for agents and tools that
operate on the `.agent` context tree.

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

**PolicyEngine** evaluates stateless built-in rules only. It does not load persisted Policy rows. Domain-specific persisted-policy enforcement lives in `policy/enforcement.py`.

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
| `memory.private_placement` | `policy/enforcement.py` | Structured log |
| `run.user_private_scope` | `policy/enforcement.py` | Structured log |
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

## PersonalMemoryGrant

**Status:** Active. Further expansion requires a separate design.

### Tables and entities

- `personal_memory_grants` — grant records (granting user, target run scope, status).
- `personal_memory_grant_events` — audit trail for grant lifecycle events (denied egress, revoke, etc.).
- `proposal_approvals` — first-class metadata-only approval rows (`egress_granting_user` type).

### Grant API (`app.personal_memory_grants`)

- Preview, create, list, revoke, and audit endpoints are active.
- `memory.cross_space_read` remains deny-by-default for the normal retrieval path; the grant is the explicit exception.

### Resolver and ephemeral context (`app.personal_memory_grants.resolver`)

- Grant lifecycle enforced via atomic conditional UPDATE (`active → consuming`).
- `personal_context_block` is ephemeral — built in memory, injected into the adapter prompt only, never persisted.
- `ContextSnapshot.source_refs_json` stores only safe grant metadata; raw memory, generated summaries, and memory IDs are not stored.
- `Run.personal_grant_context_json` stores only safe metadata: grant ID, space IDs, memory count, boolean safety flags.

### Egress guard (`app.personal_memory_grants.egress_guard`)

`check_personal_memory_egress(db, run, target_space_id, …)` → `EgressCheckResult(ALLOW | BLOCK)`.

| Condition | Result |
|---|---|
| Non-personal target | BLOCK (egress_review proposal required) |
| `raw_private_memory_included` in metadata | BLOCK (hard) |
| `target_visibility == "public"` | BLOCK (hard) |
| Unknown target space | BLOCK (fails closed) |
| Personal target | ALLOW |
| Non-grant-derived output | ALLOW |

Enforcement points: `RunOutputMaterializer` (artifact and memory proposal creation), `ArtifactPersistenceService` (file artifact persistence), `MemoryProposalApplier.apply_create/update` (defense-in-depth), `create_source_pointer()` (SourcePointer with grant-derived keys).

Code patch proposals from grant-derived runs are not blocked but carry elevated `risk_level = "high"` and explicit risk metadata.

### Proposal approval gate (`app.proposals.approvals`)

- Approval type `egress_granting_user`; statuses: `approved | revoked`.
- Only `PersonalMemoryGrant.granting_user_id` may record `egress_granting_user`; space admins/owners cannot approve on behalf of the granting user.
- `ProposalApplyService` requires a valid `proposal_approvals` row before applying `egress_review` proposals or grant-derived proposals to non-personal targets.
- Payload flags (e.g., `approved_by_granting_user`) are never treated as proof of approval.

### Egress review proposal creation (`app.personal_memory_grants.egress_review`)

- When materialization is blocked, a metadata-only `egress_review` proposal is created for the granting user.
- Payload contains no output text, raw memory, generated summary, or memory IDs.
- Applying an `egress_review` proposal is metadata-only; shared content is not created automatically.

### Remaining deferred items

See `docs/FUTURE_ROADMAP.md` for the full deferred list. Key items:
- Semantic leakage detection (paraphrased personal-memory meaning requires manual review).
- Full shared-content pipeline from approved egress_review.
- Long-lived, agent-level, space-level, and multi-user grants.
- `GET /api/v1/spaces/{space_id}/grant-stats` admin endpoint.
- Consuming-only sub-limit (separate cap of 3 deferred).

---

## Remaining deferred items

1. Semantic leakage detection for grant-derived output. Exact `personal_context_block` echoes are redacted; paraphrased/inferred personal-memory meaning must be reviewed manually.
2. Shared persistence pipeline from approved egress_review: applying an egress_review proposal is metadata-only. Future phase required for full shared-content apply.
3. Publish proposal apply + redaction pipeline.
4. Federation remote fetch (see `docs/FEDERATED_ACCESS_MODEL.md`).
5. `GET /api/v1/spaces/{space_id}/grant-stats`: space admin aggregate grant statistics endpoint. Deferred. Must return safe aggregate counts only.
6. Consuming-only sub-limit: Combined active+consuming cap of 10 is enforced. Separate consuming-only cap of 3 is deferred.
