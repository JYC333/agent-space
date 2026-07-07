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

**Helper:** active policy row loading is owned by `server/src/modules/policy/service.ts` and related repositories — single query shape for active rows (`enabled`, `status=active`, priority desc, created_at desc, id desc).

**Domain decisions:** domain-specific matching is handled in the server policy services using the bounded policy row shape.

**PolicyEngine** evaluates stateless built-in rules in priority order. When no rule matches, it uses the action registry's `default_decision` — not a permissive ALLOW. Unknown actions always fail closed with DENY (`audit_code="unknown_policy_action"`). Domain-specific persisted-policy enforcement lives in `server/src/modules/policy/`.

**PolicyEffectCatalog** (documented with `packages/protocol/src/policy.ts`) is the creation contract for active
persisted `Policy` rows from `policy_change` proposals. It is not a full DSL:
it only records whether a domain has a current enforcement effect, the allowed
enforcement modes, and the small rule shape accepted for that domain. Only
supported domains may create active `Policy` rows. Reserved domains are
vocabulary only and fail closed until wired.

**Policy service / gateway** (`server/src/modules/policy/service.ts` and `gateway.ts`) is the enforcement entry point for sensitive actions. It composes hard invariants, PolicyEngine, and PolicyDecisionRecord persistence. Business enforcement code must call one of:
- **`enforce(req)`** — direct-action path. Returns blocked on DENY/REQUIRE_APPROVAL and writes durable audit on ALLOW when required. Used by runtime, context, workspace read/patch, artifact, proposal creation, agent config proposal creation, and automation sensitive gates.
- **`enforceProposalApply(...)`** — proposal application path. Used by `PgProposalApplyService`.

Direct use of `PolicyEngine` or hard-invariant helpers outside documented non-mutating simulations is a boundary violation detected by `server/test/boundaries.test.ts`.

**Non-mutating simulation exceptions (no PolicyDecisionRecord):** preflight simulation may call pure decision helpers only — it must not persist `PolicyDecisionRecord` and must not perform the action. Current simulation call sites live in runs and automations services.

**Hard invariant guard** (`server/src/modules/policy/decisionCore.ts`) runs before PolicyEngine and enforces non-overridable security/privacy invariants.

**PolicyDecisionRecord** is an append-only durable audit table for sensitive policy decisions. Created for: audit_required actions, DENY, REQUIRE_APPROVAL, and forced records.

Space membership role checks remain separate from persisted Policy rows.
Canonical roles (ascending authority): `guest < member < reviewer < admin <
owner`. General owner/admin role helpers live in
`server/src/modules/access/roles.ts`; proposal approval resolution remains in
`server/src/modules/policy/decisionCore.ts`. Approval matrix: owner=all risk
levels, admin=low/medium/high, reviewer=low/medium, member/guest=none.

---

## Policy decision tracing and durable records

**Structured log traces:** the server logger emits JSON log lines for domain policy decisions. Memory content is never included.

**Durable records:** `PolicyDecisionRecord` table persists sensitive policy decisions. `DurablePolicyAuditWriter` (`server/src/modules/policy/auditWriter.ts`) writes only a `PolicyDecisionRecord`.

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
- Enforcement: policy hard invariant + memory proposal/apply validation
- Policy trace on allow_with_log / deny / hard-invariant denial.
- Tests: `server/test/memoryApplyIntegration.test.ts`, `server/test/memoryProposalIntegration.test.ts`, `server/test/policyDecisionCore.test.ts`

---

## run.user_private_scope

**Status:** ✅ Enforced

- Same-space private memory for `owner_user_id == instructed user_id`.
- Active deny excludes same-space private; trace on deny/allow_with_log.
- Cross-space personal private in shared runs: requires `PersonalMemoryGrant`.
- Enforcement: `MemoryRetriever` → `can_read_memory_in_run_context()`
- Tests: `server/test/memoryReadAuthMatrix.test.ts`, `server/test/memoryReadIntegration.test.ts`, `server/test/contextPrepareService.test.ts`

---

## memory.cross_space_read

**Status:** 📄 Deferred — deny by default

- Structural `space_id` filter; allow/allow_with_log rows do not enable reads.
- Cross-space block traced when an allow-looking policy exists.
- **SourcePointer** stores provenance metadata only; does **not** activate this domain.
- **PersonalMemoryGrant** is the explicit exception path; see `docs/PERSONAL_MEMORY_GRANT.md`.
- Future: explicit grants + federation + policy (see `docs/FEDERATED_ACCESS_MODEL.md`).
- Tests: `server/test/policyDecisionCore.test.ts`,
  `server/test/memoryReadAuthMatrix.test.ts`,
  `server/test/memoryReadIntegration.test.ts`

---

## Policy Effect Contract

**Supported active Policy domains:**

| Domain | Enforcement point |
|--------|-------------------|
| `memory.private_placement` | `server/src/modules/policy/decisionCore.ts` |
| `run.user_private_scope` | `server/src/modules/policy/decisionCore.ts` |

**Reserved / unsupported active Policy row domains:** `runtime.execute`,
`workspace.read`, `agent.config_update`, `automation.fire`,
`capability.enable`, `tool_binding.enable`, `deployment.execute`.

`policy_change` proposal application validates the domain, enforcement mode,
`rule_json`, `applies_to_json`, and approval-proof flags before creating any
active `Policy` row. Unsupported and reserved domains do not create active rows.

---

## SourcePointer (provenance metadata)

**Status:** Schema + metadata API — **no read grant**

- Table `source_pointers`; HTTP/service boundary `server/src/modules/sourcePointers/routes.ts`.
- Create requires active membership in both owner and source spaces.
- Create validates the referenced source object exists in `source_space_id`.
- Delete requires owner/admin in the owner space.
- `granted_by_user_id` is server-assigned; client payload cannot set it.
- `metadata_json` is bounded safe metadata and rejects content-bearing or grant-derived
  personal-memory marker keys recursively.
- SourcePointer must not activate `memory.cross_space_read`, bypass `can_read_memory`, or
  serve as authorization evidence.
- Tests: route registration is covered by `server/test/gateway.test.ts`; schema coverage is in `server/test/baselineSchema.test.ts`.

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
- **WIRED_DIRECT** (28): `lifecycle_status=WIRED_DIRECT` — have a preferred `PolicyGateway.enforce()` or `enforceProposalApply()` call site.
  Actions: `runtime.execute`, `runtime.use_credential`, `context.inject_memory`, `context.render_for_runtime`,
  `workspace.write_patch`, `artifact.persist`, `proposal.create`, `proposal.apply`,
  `agent.config_update`, `workspace.read`, `runtime_skill.render`,
  `automation.create`, `automation.update`, `automation.fire`,
  `intake.connection_manage`, `intake.item_create`, `intake.item_update`,
  `evidence.create`, `evidence.update`, `evidence.link`,
  `workspace_intake.configure`, `context.select_evidence`,
  `retrieval.search`, `retrieval.brief`, `memory.retrieval.search`,
  `memory.retrieval.brief`, `project_public_summary.search`,
  `project_public_summary.brief`.
- **WIRED_VIA_PROPOSAL** (25): `lifecycle_status=WIRED_VIA_PROPOSAL` — enforced exclusively via the `proposal.apply`
  gate (`PolicyGateway.enforceProposalApply()`).
  Actions: `memory.create`, `memory.update`, `memory.archive`, `policy.change`,
  `knowledge.create`, `knowledge.update`, `knowledge.archive`,
  `knowledge.relation_create`, `knowledge.relation_delete`,
  `claim.create`, `claim.update`, `claim.archive`, `claim.relation_create`,
  `claim.relation_delete`, `object_relation.create`, `object_relation.delete`,
  `memory_maintenance_packet`, `retrieval_maintenance_packet`,
  `retrieval_diagnostics_packet`, `skill.import`, `skill.convert`,
  `capability.enable`, `capability.disable`, `capability.update`,
  `runtime_skill.binding_update`.
- **RESERVED** (11): `lifecycle_status=RESERVED` — registered for vocabulary completeness and fail-closed
  defence-in-depth, but not wired to business code yet. `PolicyGateway` always denies reserved actions.
  `current_enforcement_point="not_implemented"` is a human-readable marker.
  Actions: `context.use_personal_grant`, `workspace.apply_patch`, `artifact.export`,
  `proposal.approve`, `memory.read_private`, `memory.promote_shared`, `runtime_skill.execute`,
  `tool_binding.enable`, `evidence.export`, `deployment.propose`, `deployment.execute`.

**record_failure_mode** (`RecordFailureMode` in `packages/protocol/src/policy.ts`): Each action definition carries a typed `record_failure_mode` field:
- `BEST_EFFORT` (default) — if `PolicyDecisionRecord` persistence fails, log a warning and continue.
- `FAIL_CLOSED` — preferred enforcement raises `PolicyAuditPersistError` if durable persistence fails; the sensitive action must not proceed.
  Actions with `FAIL_CLOSED`: `runtime.use_credential`, `workspace.write_patch`, `artifact.persist`, `proposal.apply`,
  `policy.change`, `skill.import`, `skill.convert`, `capability.enable`, `capability.disable`,
  `capability.update`, `runtime_skill.binding_update`, `automation.create`, `automation.fire`,
  `automation.update`, `retrieval.search`, `retrieval.brief`, `memory.retrieval.search`, `memory.retrieval.brief`,
  `project_public_summary.search`, `project_public_summary.brief`.
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
| `runtime.execute` | `server/src/modules/runs/orchestrationService.ts` | Uses `enforce()` before credentials, context snapshot, and adapter execution. Decision fields are in `context`; safe duplicates are in `metadata_json`. |
| `runtime.use_credential` | `server/src/modules/providers/providerCommandStore.ts`, provider invocation, and run orchestration | Uses `enforce()` before ModelProvider API-key secret fetch; `resource_space_id` comes from the credential row. Same-space manual/api/delegation origins allow; automation requires approval. CLI-profile runtimes use the CLI CredentialBroker path. **fail_closed**. |
| `context.inject_memory` | `server/src/modules/context/` and `server/src/modules/runs/` | Uses `enforce()` before context assembly/persistence; cross-space access hard denies. |
| `context.render_for_runtime` | `server/src/modules/runs/` | Before adapter execution — cross-space hard DENY. `has_personal_grant_context` in `context`. |
| `workspace.write_patch` | `server/src/modules/workspaces/` and proposal appliers | Uses `enforce()` before workspace file writes. **fail_closed**. |
| `workspace.read` | `server/src/modules/workspaces/routes.ts` | Uses `enforce()` before workspace tree/file/status/diff reads. Uses actual `Workspace.space_id` as `resource_space_id`. Normal project reads default allow; system_core, external-root, protected/restricted, full diff, and secret-like path reads use `force_record=True`. PathPolicy still blocks traversal and secret-like paths before content is returned. Full diff is bounded and secret-like diff values are redacted; secret-like diff paths are denied. |
| `artifact.persist` | `server/src/modules/runs/materializationService.ts` | Uses `enforce()` before persistence. Blocked decisions are audited once and write no file or row. **fail_closed**. |
| `proposal.create` | `server/src/modules/proposals/` and target modules | Uses `enforce()` for user-created proposals. |
| `proposal.create` | `server/src/modules/workspaces/codePatchCollector.ts` | Uses `enforce()` with `force_record=True` for system-created code_patch proposals. |
| `proposal.apply` | `server/src/modules/proposals/applyService.ts` | Uses `enforceProposalApply()`; unsupported types deny first. **fail_closed**. |
| `agent.config_update` | `server/src/modules/agents/service.ts` | Uses `enforce()` before creating `agent_config_update` proposals. This is the domain-specific proposal creation audit; accepted mutation still goes through `proposal.apply`. Metadata includes changed field names and safe IDs only, not raw system prompt or policy blobs. |
| `automation.create` | `server/src/modules/automations/service.ts` | **Uses server `enforce()`**. Runtime preflight and policy preflight simulation must pass before the Automation row is written. `membership_role`, `agent_id`, `trigger_type` in `context`. **fail_closed** — persistence failure blocks creation. |
| `automation.update` | `server/src/modules/automations/service.ts` | **Uses server `enforce()`**. `membership_role`, `agent_id` in `context`. **fail_closed**. |
| `automation.fire` | `server/src/modules/automations/service.ts` | **Uses server `enforce()`**. Runtime preflight and policy preflight simulation rerun. `membership_role`, `agent_id`, `trigger_origin="automation"` in `context`. Creates a queued Run, an `agent_run` job, and an AutomationRun record; scheduled fire advances the schedule in the same transaction as the Run/Job/AutomationRun writes. **fail_closed**. |
| `retrieval.search` / `retrieval.brief` | `server/src/modules/retrieval/tool/service.ts` | Uses `enforce()` before managed-run Knowledge search/brief execution. Domain must be enabled, an instructed-user viewer must exist, and audit is pointer-only. **fail_closed**. |
| `memory.retrieval.search` / `memory.retrieval.brief` | `server/src/modules/retrieval/tool/service.ts`, `server/src/modules/runs/managedRetrievalTools.ts` | Uses `enforce()` before explicitly opted-in managed-run Memory retrieval. Disabled-domain calls are denied/audited before returning a model-visible domain-not-enabled tool result. **fail_closed**. |
| `project_public_summary.search` / `project_public_summary.brief` | `server/src/modules/retrieval/tool/service.ts`, `server/src/modules/runs/managedRetrievalTools.ts` | Uses `enforce()` before explicitly opted-in Project public-summary retrieval. Disabled-domain calls are denied/audited before returning a model-visible domain-not-enabled tool result. **fail_closed**. |

### Non-PolicyGateway revalidation guards

These guards are policy-relevant but are not separate action-registry entries.
They enforce object visibility/type boundaries before data is attached or
rendered.

| Guard | File | Boundary |
|-------|------|----------|
| Context artifact attachment | `server/src/modules/agents/routes.ts`, `server/src/modules/context/routes.ts`, `server/src/modules/context/repository.ts`, `server/src/modules/context/prepareService.ts` | `context_artifact_ids` are capped at 8, de-duplicated, restricted to attachable artifact types, checked against artifact visibility and project access, rendered as `bounded_summary` packs with `raw_artifact_content_included=false`, and revalidated at prepare time before runtime context injection. Unsupported/hidden/project-inaccessible artifacts become blocked attachment refs, not silent context content. |

### WIRED_VIA_PROPOSAL action inventory

These actions are enforced exclusively via the `proposal.apply` gate (`PolicyGateway.enforceProposalApply()`).
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
| `claim.create` | `proposal.apply` gate | `claim_create` creates a global Claim atom. No direct PolicyGateway call site. |
| `claim.update` | `proposal.apply` gate | `claim_update` updates a global Claim atom. No direct PolicyGateway call site. |
| `claim.archive` | `proposal.apply` gate | `claim_archive` archives a global Claim atom. No direct PolicyGateway call site. |
| `object_relation.create` | `proposal.apply` gate | `object_relation_create` creates an FK-backed ObjectRelation. No direct PolicyGateway call site. |
| `object_relation.delete` | `proposal.apply` gate | `object_relation_delete` archives an ObjectRelation. No direct PolicyGateway call site. |
| `memory_maintenance_packet` | `proposal.apply` gate | Private packets remain creator-only. Explicit `visibility = space_shared` + `review_scope = space_ops` packets are reviewable only when the `retrieval.space.settings` `context_ops_review_mode` field permits the reviewer role. No canonical Memory writes and no direct PolicyGateway call site. |
| `retrieval_maintenance_packet` | `proposal.apply` gate | Private packets remain creator-only. Explicit `visibility = space_shared` + `review_scope = space_ops` packets are reviewable only when the `retrieval.space.settings` `context_ops_review_mode` field permits the reviewer role. May create child ObjectRelation proposals for supported findings. No direct PolicyGateway call site. |
| `retrieval_diagnostics_packet` | `proposal.apply` gate | Private packets remain creator-only. Explicit `visibility = space_shared` + `review_scope = space_ops` packets are reviewable only when the `retrieval.space.settings` `context_ops_review_mode` field permits the reviewer role. No canonical Knowledge or Memory writes and no direct PolicyGateway call site. |

### Context artifact attachment structural guard

`context_artifact_ids` are not a PolicyGateway action. They are structurally
guarded by `server/src/modules/context/repository.ts` and prevalidated at
managed-run creation:

- attachable type allowlist: `retrieval_brief`, `retrieval_eval_report`,
  `retrieval_explain_report`, `retrieval_maintenance_report`,
  `memory_maintenance_report`;
- visibility: `space_shared`/`public_template`, creator/owner-visible private
  rows, and `workspace_shared` only when `artifacts.workspace_id` matches the
  caller's workspace context;
- project gate: project-scoped artifacts require project visibility;
- content mode: bounded summary only, with raw artifact content excluded from
  the runtime context pack.

### Knowledge policy and proposal boundary

Knowledge durable writes are implemented through `ProposalApplyService` and
protected by `proposal.apply`. The action registry marks `knowledge.create`,
`knowledge.update`, and `knowledge.archive` as `WIRED_VIA_PROPOSAL`. The same proposal-gated
boundary protects Claim/ObjectRelation writes through `claim.create`,
`claim.update`, `claim.archive`, `object_relation.create`, and
`object_relation.delete`.

`SUPPORTED_PROPOSAL_TYPES` includes `knowledge_create`, `knowledge_update`,
`knowledge_archive`, plus `claim_create`, `claim_update`, `claim_archive`,
`object_relation_create`, and `object_relation_delete`. Unsupported proposal
types still deny at the `proposal.apply` gate with
`unsupported_proposal_type`.

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

Run creation, agent run preflight, standalone preflight, and automation policy
preflight use `PolicyEngine` directly (non-mutating
simulation only — no `PolicyDecisionRecord`). They are absent from the wired
action inventories because they are not enforcement and must not emit
`PolicyDecisionRecord`.
**Real enforcement runs exclusively in `RunOrchestrationService`.**

Automation supports manual and schedule-triggered fire. Policy preflight is not
enforcement: it does not call `PolicyGateway.enforce()`, decrypt credentials, or
mutate Run, Automation, MemoryEntry, Proposal, Policy, Credential, or Artifact
rows.
Runtime requirements decide whether provider defaults apply: `capability`,
`claude_code`, and `codex_cli` never inherit the space default
ModelProvider. Runtime-scoped provider defaults decide which provider is used
for `model_provider_mode=required`; only those runtimes fall back to the space
default provider. Runtime requirements are mandatory for every wired runtime
adapter; unknown non-empty adapter types fail with `runtime_requirements_missing`
instead of silently using `model_provider_mode=none`.

## Policy table wiring summary

| Domain | Runtime wired | Tracing |
|--------|---------------|---------|
| `memory.private_placement` | `server/src/modules/policy/decisionCore.ts` | Structured log |
| `run.user_private_scope` | `server/src/modules/policy/decisionCore.ts` | Structured log |
| `memory.cross_space_read` | Structural deny only | Structured log on blocked cross-space with allow-looking row |
| `runtime.execute` | `server/src/modules/runs/orchestrationService.ts` PolicyGateway (decision fields in `context`; audit duplicates in `metadata_json`) | PolicyDecisionRecord |
| `runtime.use_credential` | provider credential resolver + run orchestration PolicyGateway for ModelProvider API-key runtimes (`trigger_origin` in `context`; credential space from DB) | PolicyDecisionRecord |
| `context.inject_memory` | context/runs PolicyGateway (`trigger_origin` in `context`) | PolicyDecisionRecord on DENY |
| `context.render_for_runtime` | runs PolicyGateway (`has_personal_grant_context` in `context`) | PolicyDecisionRecord on DENY |
| `workspace.read` | workspaces PolicyGateway (`read_kind`, `relative_path`, workspace posture in `context`) | PolicyDecisionRecord on DENY/REQUIRE_APPROVAL and forced audit for system_core/external-root/restricted/full-diff/secret-like reads |
| `artifact.persist` | run materialization PolicyGateway (`artifact_type`, `visibility`, workspace/project IDs, storage shape in `context`) | PolicyDecisionRecord (audit_required=True) |
| `proposal.create` | proposals + target modules (`target_visibility`, `target_scope` in `context` for memory proposals) | PolicyDecisionRecord (force_record=True for code_patch) |
| `proposal.apply` | proposal apply service PolicyGateway | PolicyDecisionRecord (audit_required=True). Unsupported proposal types deny at gate (`audit_code="unsupported_proposal_type"`) before any role check. Role matrix: owner=all, admin=low/medium/high, reviewer=low/medium. |
| `knowledge.*` | proposals + knowledge proposal appliers via `proposal.apply` | No direct write gate. Accepted `knowledge_*` proposals create/version/archive KnowledgeItem or create/archive ObjectRelation rows. |
| `agent.config_update` | `server/src/modules/agents/service.ts` PolicyGateway before `agent_config_update` proposal creation | PolicyDecisionRecord (audit_required=True, safe metadata only) |
| `automation.create` | `server/src/modules/automations/service.ts` PolicyGateway | PolicyDecisionRecord (audit_required=True, fail_closed). `membership_role` in context; requires admin/owner. Runtime preflight + policy preflight snapshots are stored in `preflight_snapshot_json`. |
| `automation.update` | `server/src/modules/automations/service.ts` PolicyGateway | PolicyDecisionRecord (audit_required=True, fail_closed). `membership_role` in context; requires admin/owner. |
| `automation.fire` | `server/src/modules/automations/service.ts` PolicyGateway | PolicyDecisionRecord (audit_required=True, fail_closed). `membership_role`, `trigger_origin="automation"` in context. Runtime preflight + policy preflight snapshots are stored in `AutomationRun.preflight_snapshot_json`. |

Malformed effects on security-sensitive domains fail safe → **deny** (`get_active_policy_match`).

---

## Space isolation

**Status:** ✅ Enforced at data layer — `server/test/baselineSchema.test.ts` and
`server/test/leafDomainInvariants.test.ts`

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

### Grant API (`server/src/modules/personalMemoryGrants/`)

- Preview, create, list, revoke, and audit endpoints are active.
- `memory.cross_space_read` remains deny-by-default for the normal retrieval path; the grant is the explicit exception.

### Resolver and ephemeral context (`server/src/modules/personalMemoryGrants/`)

- Grant lifecycle enforced via atomic conditional UPDATE (`active → consuming`).
- `personal_context_block` is ephemeral — built in memory, injected into the adapter prompt only, never persisted.
- `ContextSnapshot.source_refs_json` stores only safe grant metadata; raw memory, generated summaries, and memory IDs are not stored.
- `Run.personal_grant_context_json` stores only safe metadata: grant ID, space IDs, memory count, boolean safety flags.

### Egress status

Automatic grant-derived output blocking is **not implemented** in the run materialization
path. The system records safe grant context metadata and exposes explicit
`egress_granting_user` approval rows, but it does not yet route grant-derived artifacts,
memory proposals, or code patches through a unified review flow.

Future implementation must be proposal/review based and must not rely on payload flags as
proof of approval.

### Remaining deferred items

See `docs/FUTURE_ROADMAP.md` for the full deferred list. Key items:
- Semantic leakage detection (paraphrased personal-memory meaning requires manual review).
- Full shared-content pipeline from approved egress_review.
- Long-lived, agent-level, space-level, and multi-user grants.
- `GET /api/v1/spaces/{space_id}/grant-stats` admin endpoint.
- Consuming-only sub-limit (separate cap of 3 deferred).

---

## Remaining deferred items

1. Semantic leakage detection for grant-derived output.
2. Shared persistence pipeline from approved egress review. Future phase required for full shared-content apply.
3. Publish proposal apply + redaction pipeline.
4. Federation remote fetch (see `docs/FEDERATED_ACCESS_MODEL.md`).
5. `GET /api/v1/spaces/{space_id}/grant-stats`: space admin aggregate grant statistics endpoint. Deferred. Must return safe aggregate counts only.
6. Consuming-only sub-limit: Combined active+consuming cap of 10 is enforced. Separate consuming-only cap of 3 is deferred.
