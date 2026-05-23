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

**PolicyEngine** evaluates stateless built-in rules in priority order. When no rule matches, it uses the action registry's `default_decision` — not a permissive ALLOW. Unknown actions always fail closed with DENY (`audit_code="unknown_policy_action"`). Domain-specific persisted-policy enforcement lives in `policy/enforcement.py`.

**PolicyGateway** (`app.policy.gateway`) is the enforcement entry point for sensitive actions. It composes HardInvariantGuard, PolicyEngine, and PolicyDecisionRecord persistence. All business enforcement code must call `PolicyGateway.check_and_record()`. Direct use of `PolicyEngine`, `HardInvariantGuard`, or `default_engine` outside the allowed set is a boundary violation detected by `tests/invariants/test_policy_gateway_boundary.py`.

**Non-mutating simulation exceptions (no PolicyDecisionRecord):** Three locations use `PolicyEngine` directly for preflight simulation only — they must not persist `PolicyDecisionRecord` and must not enforce actions:
- `app.runs.preflight.PreflightService` — dry-run simulation of `runtime.execute` before a run exists.
- `app.runs.run_service.RunService._validate_run_target_agent` / `_validate_adapter_for_target` — lightweight preflight during run creation (before queuing). Real enforcement with `PolicyGateway` happens in `RunExecutionService`.
- `app.agents.agent_service.AgentService._check_run` — non-mutating preflight before queuing a run. Real enforcement in `RunExecutionService`.

**HardInvariantGuard** (`app.policy.hard_invariants`) runs before PolicyEngine and enforces non-overridable security/privacy invariants.

**PolicyDecisionRecord** (`app.models.PolicyDecisionRecord`) is an append-only durable audit table for sensitive policy decisions. Created for: audit_required actions, DENY, REQUIRE_APPROVAL, and forced records.

Space membership role checks remain separate from persisted Policy rows. Canonical roles (ascending authority): `guest < member < reviewer < admin < owner`. Approval matrix: owner=all risk levels, admin=low/medium/high, reviewer=low/medium, member/guest=none. Role helpers in `app.policy.roles`.

---

## Policy decision tracing and durable records

**Structured log traces:** `app.policy.trace.record_policy_decision_trace()` (logger `app.policy.trace`) emits JSON log lines for domain policy decisions. Memory content is never included.

**Durable records:** `PolicyDecisionRecord` table (ORM: `app.models.PolicyDecisionRecord`) persists sensitive policy decisions. Populated via `PolicyGateway.check_and_record()`. Metadata is sanitized before persistence — no credentials, prompts, patch bodies, stdout, stderr, raw memory, or `personal_context_block`.

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

## PolicyGateway enforcement points (wired)

`PolicyGateway` is the **only enforcement** entry point for sensitive policy decisions.
`PolicyEngine` is internal to the policy package — calling it directly is not
enforcement and must not be used to authorize sensitive actions outside the policy
package. Business services must not call `PolicyEngine` or `HardInvariantGuard`
directly. The sole direct-call exception is `PreflightService` dry-run simulation:
it performs no action, mutates no state, and creates no `PolicyDecisionRecord`.

**The action registry is not full RBAC/ABAC.** It is a lightweight code-owned
permission manifest that routes risk and enables unknown-action fail-closed behaviour.

**Registry structure**: The registry has three lifecycle states, distinguished by `lifecycle_status`:
- **WIRED_DIRECT** (8): `lifecycle_status=WIRED_DIRECT` — have a real direct `PolicyGateway.check_and_record()` call site.
  Actions: `runtime.execute`, `runtime.use_credential`, `context.inject_memory`, `context.render_for_runtime`,
  `workspace.write_patch`, `artifact.persist`, `proposal.create`, `proposal.apply`.
- **WIRED_VIA_PROPOSAL** (4): `lifecycle_status=WIRED_VIA_PROPOSAL` — enforced exclusively via the `proposal.apply`
  gate (`PolicyGateway.check_proposal_apply()`). Must not be called via `check_and_record()` — doing so fails closed
  with `reason_code="policy_action_via_proposal_only"`.
  Actions: `memory.create`, `memory.update`, `memory.archive`, `policy.change`.
- **RESERVED** (15): `lifecycle_status=RESERVED` — registered for vocabulary completeness and fail-closed
  defence-in-depth, but not wired to business code yet. `PolicyGateway` always denies reserved actions.
  `current_enforcement_point="not_implemented"` is a human-readable marker.
  Actions: `context.use_personal_grant`, `workspace.read`, `workspace.apply_patch`, `artifact.export`,
  `proposal.approve`, `memory.read_private`, `memory.promote_shared`, `capability.enable`, `capability.update`,
  `tool_binding.enable`, `automation.create`, `automation.fire`, `automation.update`, `deployment.propose`,
  `deployment.execute`.

**record_failure_mode** (`RecordFailureMode` enum in `app.policy.actions`): Each action definition carries a typed `record_failure_mode` field:
- `BEST_EFFORT` (default) — if `PolicyDecisionRecord` persistence fails, log a warning and continue.
- `FAIL_CLOSED` — if persistence fails, raise `PolicyDecisionRecordPersistError`; the sensitive action must not proceed.
  Actions with `FAIL_CLOSED`: `runtime.use_credential`, `workspace.write_patch`, `proposal.apply`, `policy.change`.
  Dynamic escalation to `FAIL_CLOSED` also occurs for:
  - `trigger_origin="automation"` + `audit_required=True` on the action — **regardless of ALLOW/DENY/REQUIRE_APPROVAL**.
  - CRITICAL risk level + `audit_required=True` on the action — **regardless of ALLOW/DENY/REQUIRE_APPROVAL**.
  - `trigger_origin="automation"` + non-ALLOW (legacy rule for non-audit-required actions).
  - CRITICAL risk level + non-ALLOW (legacy rule for non-audit-required actions).

Actions completely absent from the registry (`agent.delegate`)
fail closed via `unknown_policy_action` DENY if ever passed to `PolicyEngine` or
`PolicyGateway`.

### context vs metadata_json semantics

| Field | Where it belongs | Why |
|-------|-----------------|-----|
| `context` | Decision inputs consumed by `HardInvariantGuard` and `PolicyEngine` rules | Keys are flattened into the guard context. Fields such as `agent_status`, `tool_name`, `trigger_origin`, `derived_from_personal_memory_grant`, `raw_private_memory_included`, `target_visibility`, `target_space_id` must appear here. |
| `metadata_json` | Sanitized audit-only metadata written to `PolicyDecisionRecord` | Never grants permission or satisfies approval. Forbidden sentinel fields in this audit bag may still trigger defensive hard-DENY behavior, such as `personal_context_block` or approval-proof flags. Dangerous fields are stripped by `sanitize_policy_metadata()`. |
| `payload` | Proposal/policy payload | Only `HardInvariantGuard` inspects payload (approval-proof flag check for `proposal.apply` / `policy.change`). Not a decision input for any other action. |

### WIRED_DIRECT action inventory

| Action | File | Gate |
|--------|------|------|
| `runtime.execute` | `runs/execution.py` | Before credentials, context snapshot, and adapter.execute(). Decision fields (`agent_status`, `tool_name`, `trigger_origin`, etc.) in `context`; audit duplicates in `metadata_json`. **Actor**: `actor_type="user"`, `actor_id=instructed_by_user_id` for manual runs with a user; otherwise `actor_type="run"`, `actor_id=run.id`, `actor_ref={run_id, trigger_origin}`. `run_id` and `resource_id` always refer to the run. |
| `runtime.use_credential` | `runs/execution.py` | `resource_space_id` from actual `Credential` row. Before secret fetch. `trigger_origin` in `context`. **fail_closed** — persistence failure blocks credential resolution. |
| `context.inject_memory` | `runs/context_snapshot_populator.py` | Before ContextBuilder.build() — cross-space hard DENY. `trigger_origin` in `context`. |
| `context.render_for_runtime` | `runs/execution.py` | Before adapter.execute() — cross-space hard DENY. `has_personal_grant_context` in `context`. |
| `artifact.persist` | `runs/artifact_persistence.py` | DENY **and** REQUIRE_APPROVAL both block file write and Artifact row creation. `target_space_id`, `derived_from_personal_memory_grant`, `raw_private_memory_included` in `context`. |
| `proposal.create` | `memory/proposals.py` | User-created memory proposals. `target_visibility` and `target_scope` in `context`. |
| `proposal.create` | `runs/code_patch_collector.py` | System-created code_patch proposals — force_record=True. |
| `proposal.apply` | `memory/proposals.py` | `PolicyGateway.check_proposal_apply()` — unsupported types deny first; role/risk matrix + hard invariants. **fail_closed** — persistence failure blocks apply. |

### WIRED_VIA_PROPOSAL action inventory

These actions are enforced exclusively via the `proposal.apply` gate (`PolicyGateway.check_proposal_apply()`).
There are **no direct `PolicyGateway.check_and_record()` call sites** for these actions in business code.
Calling `check_and_record()` with them directly fails closed with `reason_code="policy_action_via_proposal_only"`.

The `record_failure_mode` field on WIRED_VIA_PROPOSAL actions is **declarative intent only** — it documents
the expected audit posture of the action but does not drive direct enforcement. The `proposal.apply` gate
is the actual fail_closed audit and approval boundary for all of these actions.

| Action | Protected via | Notes |
|--------|--------------|-------|
| `memory.create` | `proposal.apply` gate (`check_proposal_apply_policy`) | Memory writes require proposal approval. No direct PolicyGateway call site. |
| `memory.update` | `proposal.apply` gate | Memory updates require proposal approval. No direct PolicyGateway call site. |
| `memory.archive` | `proposal.apply` gate | Memory archive requires proposal approval. No direct PolicyGateway call site. |
| `policy.change` | `proposal.apply` gate | Requires admin/owner role. No direct PolicyGateway call site. Durable audit occurs through `proposal.apply`. |

`PreflightService`, `RunService.create_run`, and `AgentService._check_run` use `PolicyEngine` directly
(non-mutating simulation only — no `PolicyDecisionRecord`). They are absent from the wired action
inventories because they are not enforcement and must not emit `PolicyDecisionRecord`.
**Real enforcement runs exclusively in `RunExecutionService`.**

## Policy table wiring summary

| Domain | Runtime wired | Tracing |
|--------|---------------|---------|
| `memory.private_placement` | `policy/enforcement.py` | Structured log |
| `run.user_private_scope` | `policy/enforcement.py` | Structured log |
| `memory.cross_space_read` | Structural deny only | Structured log on blocked cross-space with allow-looking row |
| `runtime.execute` | `runs/execution.py` PolicyGateway (decision fields in `context`; audit duplicates in `metadata_json`) | PolicyDecisionRecord |
| `runtime.use_credential` | `runs/execution.py` PolicyGateway (`trigger_origin` in `context`; Credential.space_id from DB) | PolicyDecisionRecord |
| `context.inject_memory` | `runs/context_snapshot_populator.py` PolicyGateway (`trigger_origin` in `context`) | PolicyDecisionRecord on DENY |
| `context.render_for_runtime` | `runs/execution.py` PolicyGateway (`has_personal_grant_context` in `context`) | PolicyDecisionRecord on DENY |
| `artifact.persist` | `runs/artifact_persistence.py` PolicyGateway (`target_space_id`, `derived_from_personal_memory_grant`, `raw_private_memory_included` in `context`; DENY+REQUIRE_APPROVAL block) | PolicyDecisionRecord (audit_required=True) |
| `proposal.create` | `memory/proposals.py` + `runs/code_patch_collector.py` (`target_visibility`, `target_scope` in `context` for memory proposals) | PolicyDecisionRecord (force_record=True for code_patch) |
| `proposal.apply` | `memory/proposals.py` PolicyGateway | PolicyDecisionRecord (audit_required=True). Unsupported proposal types deny at gate (`audit_code="unsupported_proposal_type"`) before any role check. Role matrix: owner=all, admin=low/medium/high, reviewer=low/medium. |

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
| `raw_private_memory_included` in egress guard `output_metadata` | BLOCK (hard; this is not `PolicyCheckRequest.metadata_json`) |
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
