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

**PolicyEffectCatalog** (`app.policy.effects`) is the creation contract for active
persisted `Policy` rows from `policy_change` proposals. It is not a full DSL:
it only records whether a domain has a current enforcement effect, the allowed
enforcement modes, and the small rule shape accepted for that domain. Only
supported domains may create active `Policy` rows. Reserved domains are
vocabulary only and fail closed until wired.

**PolicyGateway** (`app.policy.gateway`) is the enforcement entry point for sensitive actions. It composes HardInvariantGuard, PolicyEngine, and PolicyDecisionRecord persistence. Business enforcement code must call one of:
- **`PolicyGateway.enforce(req)`** — direct-action path. Raises `PolicyGateBlocked` on DENY/REQUIRE_APPROVAL and writes durable audit on ALLOW when required. Used by runtime, context, workspace read/patch, artifact, proposal creation, agent config proposal creation, and automation sensitive gates.
- **`PolicyGateway.enforce_proposal_apply(...)`** — proposal application path. Used by `ProposalService.accept()`.

Direct use of `PolicyEngine`, `HardInvariantGuard`, or `default_engine` outside the allowed set is a boundary violation detected by `tests/invariants/test_policy_gateway_boundary.py`.

**Non-mutating simulation exceptions (no PolicyDecisionRecord):** Four locations use `PolicyEngine` directly for preflight simulation only — they must not persist `PolicyDecisionRecord` and must not enforce actions:
- `app.runs.preflight.PreflightService` — dry-run simulation of `runtime.execute` before a run exists.
- `app.runs.run_service.RunService._validate_run_target_agent` / `_validate_adapter_for_target` — lightweight preflight during run creation (before queuing). Real enforcement with `PolicyGateway` happens in `RunExecutionService`.
- `app.agents.agent_service.AgentService._check_run` — non-mutating preflight before queuing a run. Real enforcement in `RunExecutionService`.
- `app.automation.policy_preflight.AutomationPolicyPreflightService` — read-only policy preflight simulation of automation-origin `runtime.execute`, `runtime.use_credential`, `context.inject_memory`, and `context.render_for_runtime`. Runtime requirements decide whether ModelProvider/API-key credential simulation applies. Runtime policy input construction is shared with `RunExecutionService` through `app.runs.policy_inputs`; real enforcement remains in `RunExecutionService`.

**HardInvariantGuard** (`app.policy.hard_invariants`) runs before PolicyEngine and enforces non-overridable security/privacy invariants.

**PolicyDecisionRecord** (`app.models.PolicyDecisionRecord`) is an append-only durable audit table for sensitive policy decisions. Created for: audit_required actions, DENY, REQUIRE_APPROVAL, and forced records.

Space membership role checks remain separate from persisted Policy rows. Canonical roles (ascending authority): `guest < member < reviewer < admin < owner`. Approval matrix: owner=all risk levels, admin=low/medium/high, reviewer=low/medium, member/guest=none. Role helpers in `app.policy.roles`.

---

## Policy decision tracing and durable records

**Structured log traces:** `app.policy.trace.record_policy_decision_trace()` (logger `app.policy.trace`) emits JSON log lines for domain policy decisions. Memory content is never included.

**Durable records:** `PolicyDecisionRecord` table (ORM: `app.models.PolicyDecisionRecord`) persists sensitive policy decisions. `DurablePolicyAuditWriter` (`app.policy.audit`) opens its own `SessionLocal()` transaction and writes only a `PolicyDecisionRecord`. The HTTP `PolicyGateBlocked` handler rolls back its request session and writes a blocking record independently.

Runtime-local blocked paths call `write_blocked_gate_audit(exc)` exactly once and fail the operation. No business object is committed merely to persist policy audit evidence.

Metadata is sanitized before persistence — no credentials, prompts, patch bodies, stdout, stderr, raw memory, or `personal_context_block`.

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

## Policy Effect Contract

**Supported active Policy domains:**

| Domain | Enforcement point |
|--------|-------------------|
| `memory.private_placement` | `app.policy.enforcement.check_private_memory_placement` |
| `run.user_private_scope` | `app.policy.enforcement.can_read_memory_in_run_context` |

**Reserved / unsupported active Policy row domains:** `runtime.execute`,
`workspace.read`, `agent.config_update`, `automation.fire`,
`capability.enable`, `tool_binding.enable`, `deployment.execute`.

`policy_change` proposal application validates the domain, enforcement mode,
`rule_json`, `applies_to_json`, and approval-proof flags before creating any
active `Policy` row. Unsupported and reserved domains do not create active rows.

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
directly. The documented direct-call exceptions are non-mutating preflight
simulations: they perform no action, mutate no state, and create no
`PolicyDecisionRecord`.

**The action registry is not full RBAC/ABAC.** It is a lightweight code-owned
permission manifest that routes risk and enables unknown-action fail-closed behaviour.

**Registry structure**: The registry has three lifecycle states, distinguished by `lifecycle_status`:
- **WIRED_DIRECT** (13): `lifecycle_status=WIRED_DIRECT` — have a preferred `PolicyGateway.enforce()` or `enforce_proposal_apply()` call site.
  Actions: `runtime.execute`, `runtime.use_credential`, `context.inject_memory`, `context.render_for_runtime`,
  `workspace.write_patch`, `workspace.read`, `artifact.persist`, `proposal.create`, `proposal.apply`,
  `agent.config_update`,
  `automation.create`, `automation.update`, `automation.fire`.
- **WIRED_VIA_PROPOSAL** (9): `lifecycle_status=WIRED_VIA_PROPOSAL` — enforced exclusively via the `proposal.apply`
  gate (`PolicyGateway.enforce_proposal_apply()`).
  Actions: `memory.create`, `memory.update`, `memory.archive`, `policy.change`,
  `knowledge.create`, `knowledge.update`, `knowledge.archive`,
  `knowledge.relation_create`, `knowledge.relation_delete`.
- **RESERVED** (11): `lifecycle_status=RESERVED` — registered for vocabulary completeness and fail-closed
  defence-in-depth, but not wired to business code yet. `PolicyGateway` always denies reserved actions.
  `current_enforcement_point="not_implemented"` is a human-readable marker.
  Actions: `context.use_personal_grant`, `workspace.apply_patch`, `artifact.export`,
  `proposal.approve`, `memory.read_private`, `memory.promote_shared`, `capability.enable`, `capability.update`,
  `tool_binding.enable`, `deployment.propose`, `deployment.execute`.

**record_failure_mode** (`RecordFailureMode` enum in `app.policy.actions`): Each action definition carries a typed `record_failure_mode` field:
- `BEST_EFFORT` (default) — if `PolicyDecisionRecord` persistence fails, log a warning and continue.
- `FAIL_CLOSED` — preferred enforcement raises `PolicyAuditPersistError` if durable persistence fails; the sensitive action must not proceed.
  Actions with `FAIL_CLOSED`: `runtime.use_credential`, `workspace.write_patch`, `artifact.persist`, `proposal.apply`, `policy.change`.
  Dynamic escalation to `FAIL_CLOSED` also occurs for:
  - `trigger_origin="automation"` + `audit_required=True` on the action — **regardless of ALLOW/DENY/REQUIRE_APPROVAL**.
  - CRITICAL risk level + `audit_required=True` on the action — **regardless of ALLOW/DENY/REQUIRE_APPROVAL**.
  - `trigger_origin="automation"` + non-ALLOW on non-audit-required actions.
  - CRITICAL risk level + non-ALLOW on non-audit-required actions.

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
| `runtime.execute` | `runs/execution.py` | Uses `enforce()` before credentials, context snapshot, and adapter execution. Decision fields are in `context`; safe duplicates are in `metadata_json`. |
| `runtime.use_credential` | `runs/execution.py` | Uses `enforce()` before ModelProvider API-key secret fetch; `resource_space_id` comes from the `Credential` row. CLI-profile runtimes use the CLI CredentialBroker path. **fail_closed**. |
| `context.inject_memory` | `runs/context_snapshot_populator.py` | Uses `enforce()` before ContextBuilder.build(); cross-space access hard denies. |
| `context.render_for_runtime` | `runs/execution.py` | Before adapter.execute() — cross-space hard DENY. `has_personal_grant_context` in `context`. |
| `workspace.write_patch` | `memory/code_patch_apply.py` | Uses `enforce()` before workspace file writes. **fail_closed**. |
| `workspace.read` | `workspace_console/api.py` | Uses `enforce()` before workspace tree/file/status/diff reads. Uses actual `Workspace.space_id` as `resource_space_id`. Normal project reads default allow; system_core, external-root, protected/restricted, full diff, and secret-like path reads use `force_record=True`. PathPolicy still blocks traversal and secret-like paths before content is returned. Full diff is bounded and secret-like diff values are redacted; secret-like diff paths are denied. |
| `artifact.persist` | `runs/artifact_persistence.py` | Uses `enforce()` before egress guard or persistence. Blocked decisions are audited once through `write_blocked_gate_audit()` and write no file or row. **fail_closed**. |
| `proposal.create` | `proposals/service.py` | Uses `enforce()` for user-created memory proposals. |
| `proposal.create` | `runs/code_patch_collector.py` | Uses `enforce()` with `force_record=True` for system-created code_patch proposals. |
| `proposal.apply` | `proposals/service.py` | Uses `enforce_proposal_apply()`; unsupported types deny first. **fail_closed**. |
| `agent.config_update` | `agents/agent_service.py` | Uses `enforce()` before creating `agent_config_update` proposals. This is the domain-specific proposal creation audit; accepted mutation still goes through `proposal.apply`. Metadata includes changed field names and safe IDs only, not raw system prompt or policy blobs. |
| `automation.create` | `automation/service.py` | **Uses `enforce()`** — raises `PolicyGateBlocked` on denial, global handler writes durable record. Runtime preflight and policy preflight simulation must pass before the Automation row is written. `membership_role`, `agent_id`, `trigger_type` in `context`. **fail_closed** — persistence failure blocks creation. |
| `automation.update` | `automation/service.py` | **Uses `enforce()`**. `membership_role`, `agent_id` in `context`. **fail_closed**. |
| `automation.fire` | `automation/service.py` | **Uses `enforce()`**. Runtime preflight and policy preflight simulation rerun. `membership_role`, `agent_id`, `trigger_origin="automation"` in `context`. Creates queued Run only. **fail_closed**. |

### WIRED_VIA_PROPOSAL action inventory

These actions are enforced exclusively via the `proposal.apply` gate (`PolicyGateway.enforce_proposal_apply()`).
There are no standalone production enforcement call sites for these actions.

The `record_failure_mode` field on WIRED_VIA_PROPOSAL actions is **declarative intent only** — it documents
the expected audit posture of the action but does not drive direct enforcement. The `proposal.apply` gate
is the actual fail_closed audit and approval boundary for all of these actions.

| Action | Protected via | Notes |
|--------|--------------|-------|
| `memory.create` | `proposal.apply` gate | Memory writes require proposal approval. No direct PolicyGateway call site. |
| `memory.update` | `proposal.apply` gate | Memory updates require proposal approval. No direct PolicyGateway call site. |
| `memory.archive` | `proposal.apply` gate | Memory archive requires proposal approval. No direct PolicyGateway call site. |
| `policy.change` | `proposal.apply` gate | Requires admin/owner role. No direct PolicyGateway call site. Durable audit occurs through `proposal.apply`. |
| `knowledge.create` | `proposal.apply` gate | `knowledge_create` creates active KnowledgeItem rows only after proposal acceptance. No direct PolicyGateway call site. |
| `knowledge.update` | `proposal.apply` gate | `knowledge_update` creates a new KnowledgeItem version and marks the previous row superseded. No direct PolicyGateway call site. |
| `knowledge.archive` | `proposal.apply` gate | `knowledge_archive` archives an item. No direct PolicyGateway call site. |
| `knowledge.relation_create` | `proposal.apply` gate | `knowledge_relation_create` creates a same-space database-backed relation. No direct PolicyGateway call site. |
| `knowledge.relation_delete` | `proposal.apply` gate | `knowledge_relation_delete` archives a relation. No direct PolicyGateway call site. |

### Knowledge policy and proposal boundary

Knowledge durable writes are implemented through `ProposalApplyService` and
protected by `proposal.apply`. The action registry marks `knowledge.create`,
`knowledge.update`, `knowledge.archive`, `knowledge.relation_create`, and
`knowledge.relation_delete` as `WIRED_VIA_PROPOSAL`.

`SUPPORTED_PROPOSAL_TYPES` includes `knowledge_create`, `knowledge_update`,
`knowledge_archive`, `knowledge_relation_create`, and
`knowledge_relation_delete`. Unsupported proposal types still deny at the
`proposal.apply` gate with `unsupported_proposal_type`.

Knowledge read and proposal-creation endpoints enforce MVP visibility before
creating proposals: `space_shared` and `workspace_shared` are readable to
current-space members; `private` and `restricted` are owner-readable only.
Relation reads omit rows unless both endpoints are visible to the viewer.
`ProposalApplyService` also performs domain-specific Knowledge authorization
after `proposal.apply` allows acceptance, so malformed proposals cannot mutate
or relate another user's private or restricted Knowledge.

Knowledge source monitoring is not complete. The apply service has an explicit
Knowledge branch in source monitoring to document the boundary, but external or
untrusted Activity/Artifact-derived Knowledge still needs a future evaluator.

Knowledge must not automatically enter Memory or ContextBuilder. Promotion to
Memory requires a separate future proposal flow.

`PreflightService`, `RunService.create_run`, `AgentService._check_run`, and
`AutomationPolicyPreflightService` use `PolicyEngine` directly (non-mutating
simulation only — no `PolicyDecisionRecord`). They are absent from the wired
action inventories because they are not enforcement and must not emit
`PolicyDecisionRecord`.
**Real enforcement runs exclusively in `RunExecutionService`.**

Automation supports manual and schedule-triggered fire. Policy preflight is not
enforcement: it does not call `PolicyGateway.enforce()`, decrypt credentials, or
mutate Run, Automation, MemoryEntry, Proposal, Policy, Credential, or Artifact
rows.
Runtime requirements decide whether provider defaults apply: `echo`,
`capability`, `claude_code`, and `codex_cli` never inherit the space default
ModelProvider. Runtime-scoped provider defaults decide which provider is used
for `model_provider_mode=required`; only those runtimes fall back to the space
default provider. Runtime requirements are mandatory for every wired runtime
adapter; unknown non-empty adapter types fail with `runtime_requirements_missing`
instead of silently using `model_provider_mode=none`.

## Policy table wiring summary

| Domain | Runtime wired | Tracing |
|--------|---------------|---------|
| `memory.private_placement` | `policy/enforcement.py` | Structured log |
| `run.user_private_scope` | `policy/enforcement.py` | Structured log |
| `memory.cross_space_read` | Structural deny only | Structured log on blocked cross-space with allow-looking row |
| `runtime.execute` | `runs/execution.py` PolicyGateway (decision fields in `context`; audit duplicates in `metadata_json`) | PolicyDecisionRecord |
| `runtime.use_credential` | `runs/execution.py` PolicyGateway for ModelProvider API-key runtimes (`trigger_origin` in `context`; Credential.space_id from DB) | PolicyDecisionRecord |
| `context.inject_memory` | `runs/context_snapshot_populator.py` PolicyGateway (`trigger_origin` in `context`) | PolicyDecisionRecord on DENY |
| `context.render_for_runtime` | `runs/execution.py` PolicyGateway (`has_personal_grant_context` in `context`) | PolicyDecisionRecord on DENY |
| `workspace.read` | `workspace_console/api.py` PolicyGateway (`read_kind`, `relative_path`, workspace posture in `context`) | PolicyDecisionRecord on DENY/REQUIRE_APPROVAL and forced audit for system_core/external-root/restricted/full-diff/secret-like reads |
| `artifact.persist` | `runs/artifact_persistence.py` PolicyGateway (`target_space_id`, `derived_from_personal_memory_grant`, `raw_private_memory_included` in `context`; DENY+REQUIRE_APPROVAL block) | PolicyDecisionRecord (audit_required=True) |
| `proposal.create` | `proposals/service.py` + `runs/code_patch_collector.py` (`target_visibility`, `target_scope` in `context` for memory proposals) | PolicyDecisionRecord (force_record=True for code_patch) |
| `proposal.apply` | `proposals/service.py` PolicyGateway | PolicyDecisionRecord (audit_required=True). Unsupported proposal types deny at gate (`audit_code="unsupported_proposal_type"`) before any role check. Role matrix: owner=all, admin=low/medium/high, reviewer=low/medium. |
| `knowledge.*` | `proposals/service.py` + `knowledge/service.py` via `proposal.apply` | No direct write gate. Accepted `knowledge_*` proposals create/version/archive KnowledgeItem or archive/create KnowledgeItemRelation rows. |
| `agent.config_update` | `agents/agent_service.py` PolicyGateway before `agent_config_update` proposal creation | PolicyDecisionRecord (audit_required=True, safe metadata only) |
| `automation.create` | `automation/service.py` PolicyGateway | PolicyDecisionRecord (audit_required=True, fail_closed). `membership_role` in context; requires admin/owner. Runtime preflight + policy preflight snapshots are stored in `preflight_snapshot_json`. |
| `automation.update` | `automation/service.py` PolicyGateway | PolicyDecisionRecord (audit_required=True, fail_closed). `membership_role` in context; requires admin/owner. |
| `automation.fire` | `automation/service.py` PolicyGateway | PolicyDecisionRecord (audit_required=True, fail_closed). `membership_role`, `trigger_origin="automation"` in context. Runtime preflight + policy preflight snapshots are stored in `AutomationRun.preflight_snapshot_json`. |

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
