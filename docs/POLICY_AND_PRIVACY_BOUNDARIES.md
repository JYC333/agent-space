# Policy and Privacy Boundaries

This document describes the canonical policy enforcement stack and privacy
invariants for agent-space. All information here describes the current
enforced state.

---

## Policy Architecture

The policy stack is:

```
HardInvariantGuard
  → PolicyEngine
  → PolicyGateway (composes the above; enforcement entry point)
  → PolicyDecisionRecord (durable audit evidence)
  → optional RunEvent metadata
```

### 1. HardInvariantGuard

Non-overridable security/privacy invariants. These cannot be weakened by
Policy rows, runtime configuration, or caller-supplied context. They run
before PolicyEngine.

Location: `app/policy/hard_invariants.py`

### 2. PolicyEngine

Stateless decision engine over canonical actions and built-in rules.
Returns `allow`, `require_approval`, or `deny`.

**Registry default behavior**: When no built-in rule matches, PolicyEngine
returns the action definition's `default_decision` — not a permissive ALLOW.
Unknown actions always return DENY with `audit_code="unknown_policy_action"`.

Location: `app/policy/engine.py`

### 3. PolicyGateway

Main service entry point for sensitive actions. Builds context, runs
HardInvariantGuard, calls PolicyEngine, persists PolicyDecisionRecord, and
returns PolicyDecision.

Location: `app/policy/gateway.py`

Business code enforcing wired sensitive actions must use
`PolicyGateway.check_and_record()`. Do not call PolicyEngine directly to
authorize or perform a sensitive action.

**Non-mutating simulation exceptions:** Three locations use `PolicyEngine` directly for
preflight simulation — they are not enforcement points and must not persist
`PolicyDecisionRecord`. Real runtime execution still goes through `PolicyGateway`.
- `PreflightService` (`app/runs/preflight.py`) — dry-run simulation before a run exists.
- `RunService._validate_run_target_agent` / `_validate_adapter_for_target`
  (`app/runs/run_service.py`) — lightweight preflight during run creation.
- `AgentService._check_run` (`app/agents/agent_service.py`) — non-mutating preflight
  before queuing a run.

All other business code performing enforcement must call `PolicyGateway.check_and_record()` —
direct `PolicyEngine` or `HardInvariantGuard` usage outside these allowed locations is a
boundary violation detected by `tests/invariants/test_policy_gateway_boundary.py`.

#### PolicyCheckRequest field semantics

| Field | Role |
|-------|------|
| `context` | **Decision inputs** consumed by `HardInvariantGuard` and `PolicyEngine` rules. Keys are flattened into the guard context. Fields such as `agent_status`, `tool_name`, `trigger_origin`, `derived_from_personal_memory_grant`, `raw_private_memory_included`, `target_visibility`, and `target_space_id` must appear here. |
| `metadata_json` | **Audit-only metadata** written to `PolicyDecisionRecord`. It never grants permission or satisfies approval. Forbidden sentinel fields in this audit bag may still trigger defensive hard DENY, such as `personal_context_block` or approval-proof flags. Dangerous fields are stripped by `sanitize_policy_metadata()`. |
| `payload` | Proposal or policy payload. Only `HardInvariantGuard` reads it (approval-proof flag check for `proposal.apply` / `policy.change`). Not a decision input for any other action. |

### 4. PolicyDecision fields

Every `PolicyDecision` returned by `PolicyGateway`, `PolicyEngine`, or
`HardInvariantGuard` carries three stable machine-readable codes:

| Field | Purpose | Example |
|-------|---------|---------|
| `reason_code` | Stable, machine-readable code for the decision outcome. Consumers can branch on it without parsing `message`. | `"space_boundary"`, `"approved_owner"`, `"hard_invariant_cross_space_memory"` |
| `policy_rule_id` | Identifies the specific rule or invariant that produced this decision. Useful for per-rule analytics. | `"proposal_apply_owner_allow"`, `"hard_invariant_cross_space_memory"` |
| `audit_code` | Stable durable search token persisted in `PolicyDecisionRecord`. Used for audit queries. | `"cross_space_access_denied"`, `"policy_action_not_implemented"` |

**`reason_code` is NOT persisted in `PolicyDecisionRecord`.**
Durable audit relies on `audit_code` (searchable in DB) and `policy_rule_id`
(also stored in `policy_rule_id` column). `reason_code` is an ephemeral
in-process field for runtime branching only.

### 5. PolicyDecisionRecord

Append-only durable evidence of sensitive policy decisions. Persisted for:
- Actions with `audit_required=True`
- Any DENY decision
- Any REQUIRE_APPROVAL decision
- Caller-forced records

Stores `audit_code` and `policy_rule_id` for durable audit queries.
Does **not** store `reason_code` — that is an ephemeral in-process field.

**Never stores**: raw memory content, `personal_context_block`, credentials,
API keys, prompts, patch bodies, stdout/stderr, full file content.
Metadata is sanitized via `sanitize_policy_metadata()` before persistence.

ORM model: `app/models.PolicyDecisionRecord`

---

## Action Registry

Every sensitive action is registered in `app/policy/actions.py`. The
registry defines:
- `default_decision` — authoritative when no rule matches
- `default_risk_level`
- `audit_required`
- `approval_capability`
- `default_required_approver_role`
- `current_enforcement_point` — real module path for wired actions; `"not_implemented"` for reserved
- `lifecycle_status` — three states (see below)
- `record_failure_mode` — `RecordFailureMode` enum: `BEST_EFFORT` | `FAIL_CLOSED` (see below)

### lifecycle_status

| Value | Meaning |
|-------|---------|
| `WIRED_DIRECT` | Action has a direct `PolicyGateway.check_and_record()` call site in business code. |
| `WIRED_VIA_PROPOSAL` | Action is protected via the `proposal.apply` gate only. There is **no direct `PolicyGateway.check_and_record()` call site** for these actions. Calling `check_and_record()` directly always fails closed (`reason_code="policy_action_via_proposal_only"`). The `record_failure_mode` on WIRED_VIA_PROPOSAL actions is declarative intent only — actual durable audit occurs through `proposal.apply`. |
| `RESERVED` | Registered for vocabulary completeness; no enforcement point. Always fails closed with DENY regardless of `default_decision`. |

Unknown actions fail closed with DENY (`audit_code="unknown_policy_action"`).

### record_failure_mode (`RecordFailureMode` enum in `app.policy.actions`)

| Value | Behavior when PolicyDecisionRecord persistence fails |
|-------|-----------------------------------------------------|
| `BEST_EFFORT` | Log a warning and continue — action is not blocked. |
| `FAIL_CLOSED` | Raise `PolicyDecisionRecordPersistError` — the sensitive action must not proceed. Callers must treat this as a hard policy error. |

Actions with `FAIL_CLOSED`: `runtime.use_credential`, `workspace.write_patch`, `proposal.apply`, `policy.change`.

Dynamic escalation to `FAIL_CLOSED` (regardless of per-action default):
- `trigger_origin="automation"` + `audit_required=True` on the action — **regardless of ALLOW/DENY/REQUIRE_APPROVAL**.
- `risk_level=CRITICAL` + `audit_required=True` on the action — **regardless of ALLOW/DENY/REQUIRE_APPROVAL**.
- `trigger_origin="automation"` + non-ALLOW (legacy rule for non-audit-required actions).
- `risk_level=CRITICAL` + non-ALLOW (legacy rule for non-audit-required actions).

**Business-boundary error conversion** — `PolicyDecisionRecordPersistError` must not leak as an unstructured exception:
- `RunExecutionService`: converts to terminal failed run with `error_code="policy_decision_record_persist_failed"`. Run never reaches credential resolution, context rendering, or adapter invocation.
- `ProposalService.accept`: converts to `ProposalPolicyDeniedError` with `audit_code="policy_decision_record_persist_failed"`. Proposal stays pending; `ProposalApplyService.apply()` is never called.
- `apply_code_patch_payload`: converts to `CodePatchApplyError` with stable message containing `policy_decision_record_persist_failed`. No files written.
- `ArtifactPersistenceService`: converts to `PersonalMemoryEgressError` with stable message containing `policy_decision_record_persist_failed`. No file or Artifact row written.

### WIRED_VIA_PROPOSAL clarification

`memory.create`, `memory.update`, `memory.archive`, and `policy.change` are **WIRED_VIA_PROPOSAL**. This means:

- There is **no direct** `PolicyGateway.check_and_record("memory.create")` (or update/archive/policy.change) call site anywhere in the codebase.
- Protection is achieved entirely through `PolicyGateway.check_proposal_apply()` in `ProposalService.accept()`.
- `proposal.apply` is the fail_closed audit and approval gate for all of these actions.
- `RunService` and `AgentService` use `PolicyEngine` directly (non-mutating simulation) — they do not write `PolicyDecisionRecord` rows. Real enforcement is exclusively in `RunExecutionService`.
- No Automation implementation exists. Automation-reserved actions always deny at the policy gateway.

---

## Hard Invariants

These invariants are enforced unconditionally and cannot be overridden:

1. **Space isolation** — cross-space memory reads require an explicit
   PersonalMemoryGrant. No Policy row can open cross-space access.

2. **SourcePointer does not grant read access** — SourcePointers store
   provenance metadata only. Using one as authorization evidence is denied.

3. **personal_context_block is ephemeral** — it must never be persisted.
   Any persistence action with `personal_context_block` in metadata or
   context is denied.

4. **raw_private_memory_included=true blocks egress** — any egress-sensitive
   action with this flag is denied.

5. **Public target visibility blocks grant-derived output** — artifacts and
   proposals derived from personal memory grants cannot have public visibility.

6. **Payload metadata is not approval proof** — flags like `approved_by_user`,
   `auto_approved`, `pre_approved` in payload/metadata are ignored as approval
   evidence and cause denial.

7. **Unknown target space in egress-sensitive path fails closed** — DENY.

---

## Product Roles

Canonical roles (ascending authority):

| Role     | Approval authority | Other authority |
|----------|--------------------|-----------------|
| guest    | None | Read invited content only |
| member   | None | Create activity, artifacts, proposals; run low-risk allowed actions |
| reviewer | Low and medium risk | Approve memory/wiki/task proposals with effective risk ≤ medium |
| admin    | Low, medium, and high risk | Approve policy/capability/credential/workspace proposals with effective risk ≤ high |
| owner    | All risk levels including critical | Full authority inside the space (hard invariants still apply) |

Role helpers: `app/policy/roles.py`

---

## Wired Sensitive Actions

`PolicyGateway` is the **only enforcement** entry point for WIRED_DIRECT sensitive
actions. `PolicyEngine` and `HardInvariantGuard` must not be called directly
to authorize or perform them. See the non-mutating simulation exceptions in the
PolicyGateway section above for the allowed preflight-only sites.

### WIRED_DIRECT Actions

| Action | Enforcement Point | Decision inputs (context) | Behavior |
|--------|------------------|-----------------------------|----------|
| `runtime.execute` | `RunExecutionService` before `adapter.execute()` | `agent_status`, `tool_name`, `trigger_origin`, `adapter_type`, risk/sandbox fields | DENY/REQUIRE_APPROVAL prevents execution; records PolicyDecisionRecord + RunEvent |
| `runtime.use_credential` | `RunExecutionService` before `resolve_runtime_credentials()` | `trigger_origin`, `instructed_by_user_id`; `resource_space_id` from Credential row | DENY/REQUIRE_APPROVAL prevents credential resolution. **fail_closed** — persistence failure blocks credential resolution. |
| `context.inject_memory` | `ContextSnapshotPopulator` before `ContextBuilder.build()` | `trigger_origin` | Cross-space DENY; records PolicyDecisionRecord on DENY |
| `context.render_for_runtime` | `RunExecutionService` before `adapter.execute()` | `has_personal_grant_context` | Cross-space DENY; records PolicyDecisionRecord on DENY |
| `artifact.persist` | `ArtifactPersistenceService` before file write | `target_space_id`, `derived_from_personal_memory_grant`, `raw_private_memory_included` | DENY/REQUIRE_APPROVAL blocks file write and Artifact row; records PolicyDecisionRecord (audit_required=True) |
| `proposal.create` | `ProposalService.create_proposal()` and `code_patch_collector.py` | `target_visibility`, `target_scope` | Audit gate for user-created memory proposals and system-created code_patch proposals (force_record=True for code_patch path) |
| `proposal.apply` | `ProposalService.accept()` | `payload` scanned for approval-proof flags | Proposal types with no apply handler deny immediately (`audit_code="unsupported_proposal_type"`). Supported types: `check_proposal_apply_policy` evaluates role/risk matrix (owner=all, admin=low/medium/high, reviewer=low/medium, member/guest=none). PolicyDecisionRecord recorded (audit_required=True). **fail_closed** — persistence failure blocks apply. |
| `workspace.write_patch` | `apply_code_patch_payload()` before any file writes | `proposal_id`, `proposal_type`, `proposal_apply_allowed` | PolicyDecisionRecord recorded; safe patch summary only (no patch body). **fail_closed**. |

### WIRED_VIA_PROPOSAL Actions

These actions are enforced exclusively via the `proposal.apply` gate
(`PolicyGateway.check_proposal_apply()`). Calling `check_and_record()` directly
with them always fails closed (`reason_code="policy_action_via_proposal_only"`).

| Action | Protected via | Behavior |
|--------|--------------|----------|
| `memory.create` | `proposal.apply` gate | Memory writes require proposal approval |
| `memory.update` | `proposal.apply` gate | Memory updates require proposal approval |
| `memory.archive` | `proposal.apply` gate | Memory archive requires proposal approval |
| `policy.change` | `proposal.apply` gate | Requires admin/owner role. `PolicyProposalApplier.apply()` enforces role check inline; no direct PolicyGateway call. **fail_closed**. |

---

## Reserved Actions (lifecycle_status=RESERVED, not yet wired to enforcement)

These actions are registered in the action registry with `lifecycle_status=RESERVED` and
`current_enforcement_point="not_implemented"`. `PolicyGateway` always denies reserved actions
(DENY with `reason_code="policy_action_not_implemented"`, `audit_code="policy_action_not_implemented"`),
regardless of `default_decision`. They document intended policy posture for future wiring.
They are **not** wired to any business code call site yet.

| Action | Notes |
|--------|-------|
| `capability.enable` | Capability lifecycle persistence not yet wired |
| `capability.update` | Capability lifecycle persistence not yet wired |
| `tool_binding.enable` | Tool binding lifecycle not yet wired |
| `automation.create` | Automation model not yet wired |
| `automation.fire` | Automation model not yet wired |
| `automation.update` | Automation model not yet wired |
| `context.use_personal_grant` | personal_memory_grants/ does not yet call PolicyGateway |
| `workspace.read` | Workspace read APIs do not yet call PolicyGateway |
| `workspace.apply_patch` | Direct workspace patch path not yet wired |
| `artifact.export` | Artifact export surface not yet wired |
| `proposal.approve` | Explicit approval row recording not yet wired |
| `memory.read_private` | Private memory read path not yet wired |
| `memory.promote_shared` | Memory visibility promotion not yet wired |
| `deployment.propose` | Deployment proposal not yet wired |
| `deployment.execute` | Deployment execution not yet wired (critical risk) |

Actions completely absent from the registry (`agent.delegate`) fail
closed via `unknown_policy_action` DENY if passed to `PolicyEngine` or `PolicyGateway`.

---

## Enforced Memory and Context Boundaries

### Memory private placement

`visibility=private` is only permitted in personal spaces. Any attempt to
write a private-visibility memory in a non-personal space is denied by
`check_private_memory_placement()`.

Enforcement: `app/policy/enforcement.py` → `MemoryStore.create`

### Run context isolation

ContextBuilder and MemoryRetriever enforce `space_id` as a hard filter.
Cross-space memory reads are denied even when the same user instructed both runs.

Enforcement: `app/memory/retriever.py`, `app/policy/enforcement.py`

### Personal memory grant egress guard

When a run includes grant-derived personal context:
- `personal_context_block` is injected at runtime only — never persisted
- Exact echoes of the block are redacted from run output before persistence
- Grant-derived artifact/proposal persistence in non-personal spaces requires
  an `egress_review` proposal with explicit granting-user approval
- `raw_private_memory_included=true` always blocks egress (HardInvariantGuard)

Enforcement: `app/personal_memory_grants/egress_guard.py`

### SourcePointer

SourcePointers store provenance metadata only. They never grant read access
to memory entries or workspace content. SourcePointers do not contain
memory content, file content, or credentials.

---

## Policy Decision Tracing

Structured policy decision traces are emitted to the `app.policy.trace`
logger (JSON format). PolicyDecisionRecord provides durable persistence for
audit-required decisions.

Traces never include: memory content, `personal_context_block`, credentials,
or raw output.
