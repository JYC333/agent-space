# Module: Policy

## Purpose

Centralized risk-routing layer. Decides whether sensitive actions are **allowed**,
**denied**, or must go through **approval/proposal review**. Policy is not an enterprise
RBAC/ABAC platform — it is a lightweight, code-owned permission layer that routes risk.

## What policy IS

- A risk-routing layer that gates sensitive actions.
- A canonical registry of every sensitive action the system can perform.
- An approval resolver that checks whether a human actor has authority to apply a proposal.
- A hard invariant enforcer for structural constraints (private memory placement, cross-space reads).

## What policy IS NOT

- Not enterprise RBAC/ABAC.
- Not a policy DSL (no expression language).
- Not a policy UI.
- Not a membership system — `SpaceMembership` roles (`guest`, `member`, `reviewer`, `admin`, `owner`) are the membership source of truth.
- "Forbidden" is **not** a risk level. Forbidden behavior is represented as `decision=deny`.

## Owns

- `PolicyEngine` — stateless built-in rule evaluation (per-request).
- `PolicyActionDefinition` registry (`packages/protocol/src/policy.ts`) — canonical code-owned list of sensitive actions.
- `UnknownPolicyActionError` — raised by `requireActionDefinition()` for unregistered actions. Unknown actions never silently fall through.
- `PolicyDecision` — structured decision result with audit fields.
- Proposal apply gate (`server/src/modules/policy/gateway.ts`) — `checkProposalApplyPolicy`, `effectiveProposalRisk`, `ProposalRiskLevelError`.
- Active enforcement service (`server/src/modules/policy/service.ts`) — service-authenticated internal policy ports.
- Domain-specific persisted-policy enforcement (`server/src/modules/policy/*`).
- Durable policy decision tracing/audit (`server/src/modules/policy/auditWriter.ts`).

## Does Not Own

- User authentication (auth module).
- Proposal creation UI or workflow (proposals module).
- Agent runtime policy (stored on AgentVersion.runtime_policy_json, read by runners).

## Key Models

```
PolicyDecision: allow | deny | require_approval
  reason_code     — stable machine-readable code for runtime branching (not persisted)
  policy_rule_id  — which rule/invariant produced the decision (persisted in PolicyDecisionRecord)
  audit_code      — stable durable search token persisted in PolicyDecisionRecord
  actor_type      — "user" | "run" | None
  actor_id, actor_ref, space_id, resource_type, resource_id

PolicyContext (engine):
  action, space_id, resource_space_id
  user_id, agent_id, agent_status
  agent_tool_permissions, tool_name
  resource_type, resource_id

PolicyActionDefinition:
  action, resource_type, default_risk_level, default_decision
  audit_required, approval_capability, default_required_approver_role
  current_enforcement_point, description
  lifecycle_status: WIRED_DIRECT | WIRED_VIA_PROPOSAL | RESERVED

RiskLevel: low | medium | high | critical
Decision: allow | deny | require_approval
```

`reason_code` is an ephemeral in-process field — it is never stored in `PolicyDecisionRecord`.
Durable audit uses `audit_code` (DB-searchable) and `policy_rule_id` (DB column).

## Canonical Action Registry

Every sensitive action is registered in `packages/protocol/src/policy.ts`. Unknown sensitive
actions must raise through `requireActionDefinition()` — they do not silently fall
through as allow.

**The policy service is the production enforcement entry point.** `PolicyEngine`
alone is not enforcement; it is the stateless rule evaluator inside the active
authority. Sensitive business actions call `enforce()` or
`enforceProposalApply()` through `server/src/modules/policy/service.ts`.
Compatibility fixtures lock the pure decision behavior.

The registry has three lifecycle categories:

**Direct actions** (`lifecycle_status=WIRED_DIRECT`) have a real preferred enforcement call site.
**Proposal actions** (`lifecycle_status=WIRED_VIA_PROPOSAL`) are protected by `proposal.apply`.
**Reserved actions** (`lifecycle_status=RESERVED`) are registered for registry completeness and
fail-closed defence-in-depth. `current_enforcement_point="not_implemented"`. Not wired
to any business code yet. `PolicyGateway` always denies reserved actions regardless of
registry `default_decision`. Not full RBAC/ABAC — they express intent and default risk.

### Wired actions

| Action | Resource | Risk | Default Decision | Enforcement |
|---|---|---|---|---|
| `runtime.execute` | run | medium | allow | `server/src/modules/runs/orchestrationService.ts` |
| `runtime.use_credential` | credential | high | require_approval | provider credential store + run orchestration |
| `context.inject_memory` | memory | low | allow | context/runs modules |
| `context.render_for_runtime` | context | low | allow | runs module |
| `workspace.write_patch` | workspace | high | require_approval | workspaces/proposal appliers |
| `artifact.persist` | artifact | low | allow (audit_required) | run materialization |
| `proposal.create` | proposal | low | allow | proposals + target modules via `enforce()` |
| `proposal.apply` | proposal | medium | require_approval | proposal apply service via `enforceProposalApply()` |
| `workspace.read` | workspace | low | allow | workspaces routes via `enforce()` |
| `agent.config_update` | agent | high | allow (audit_required) | agents routes/repository before config proposal creation |
| `intake.connection_manage` | source_connection | medium | allow (audit_required) | intake routes via `enforce()` |
| `intake.item_create` | intake_item | low | allow (audit_required) | intake routes via `enforce()` |
| `intake.item_update` | intake_item | low | allow (audit_required) | intake routes via `enforce()` |
| `evidence.create` | evidence | low | allow (audit_required) | intake routes via `enforce()` |
| `evidence.update` | evidence | low | allow (audit_required) | intake routes via `enforce()` |
| `evidence.link` | evidence | low | allow (audit_required) | intake routes via `enforce()` |
| `workspace_intake.configure` | workspace_intake | medium | allow (audit_required) | intake routes via `enforce()` |
| `context.select_evidence` | evidence | low | allow | context module via `enforce()` |
| `memory.create` | memory | medium | require_approval | via `proposal.apply` |
| `memory.update` | memory | medium | require_approval | via `proposal.apply` |
| `memory.archive` | memory | medium | require_approval | via `proposal.apply` |
| `policy.change` | policy | high | require_approval | via `proposal.apply` |
| `automation.create` | automation | high | require_approval | `server/src/modules/automations/service.ts` via `enforce()` |
| `automation.update` | automation | high | require_approval | `server/src/modules/automations/service.ts` via `enforce()` |
| `automation.fire` | automation | medium | require_approval | `server/src/modules/automations/service.ts` via `enforce()` |

`proposal.create` covers user-created memory proposals and system-created code_patch
proposals from CLI runs. `agent.config_update` is the domain-specific creation gate
for agent execution config proposals; accepted mutation still goes through
`proposal.apply`. The `proposal.apply` gate is the durable enforcement point for all
memory mutations and accepted config proposal application.

### Reserved actions — lifecycle_status=RESERVED

Registered for registry completeness and fail-closed defence-in-depth.
`current_enforcement_point="not_implemented"`. `PolicyGateway` always denies these.
Not wired to business code. The registry is **not** full RBAC/ABAC.

| Action | Resource | Risk | Default Decision |
|---|---|---|---|
| `context.use_personal_grant` | personal_memory_grant | high | require_approval |
| `workspace.apply_patch` | workspace | high | require_approval |
| `artifact.export` | artifact | high | require_approval |
| `proposal.approve` | proposal | medium | require_approval |
| `memory.read_private` | memory | high | require_approval |
| `memory.promote_shared` | memory | high | require_approval |
| `capability.enable` | capability | high | require_approval |
| `capability.update` | capability | high | require_approval |
| `tool_binding.enable` | tool_binding | high | require_approval |
| `evidence.export` | evidence | high | require_approval |
| `deployment.propose` | deployment | high | require_approval |
| `deployment.execute` | deployment | **critical** | require_approval |

**Actions NOT in the registry at all** (no placeholder yet — must fail-closed as unknown):
- `agent.delegate`

`agent.delegate` is not registered. Agent-to-agent delegation is deferred; future
design should use a server child-run concept such as `run.spawn_child` or
`run.create_child`. `runtime.execute` is separate from delegation and only controls
adapter execution.

## Approval Resolver

`canApprovePolicyAction(...)` in `server/src/modules/policy/decisionCore.ts`.

- Raises `UnknownPolicyActionError` for any action not in the canonical registry. Unknown actions never return True.
- Default approval rules:
  - **owner**: can approve all currently supported proposal.apply actions including critical.
  - **admin**: can approve low, medium, and high risk actions; NOT critical.
  - **reviewer**: can approve low and medium risk actions; NOT high or critical.
  - **member / guest**: cannot approve by default.
  - No membership in the space: cannot approve.

## Proposal Apply Gate

`enforceProposalApply(...)` in `server/src/modules/policy/gateway.ts`, called from
`server/src/modules/proposals/applyService.ts`.

Returns a full `PolicyDecision` with:
- `decision`: allow / require_approval / deny
- `message`, `audit_code` (approved_owner, approved_admin, insufficient_role, no_membership, unsupported_proposal_type)
- `reason_code`: stable machine-readable code matching `audit_code` in all branches
- `policy_rule_id`: stable rule identifier (e.g. `proposal_apply_owner_allow`, `proposal_type_not_supported`)
- `actor_type="user"` on all branches
- `risk_level`: effective risk = `max(type_default_risk, proposal.risk_level)`
- `action="proposal.apply"`, `resource_type="proposal"`, `resource_id=proposal.id`
- `proposal_type`, `approval_capability`
- `metadata_json`: proposal_type, membership_role, effective_risk, proposal_declared_risk, default_type_risk, supported_apply_type

Effective risk computation:
- `memory_create / memory_update / memory_archive / follow_up_task` → medium
- `code_patch / policy_change / egress_review` → high
- Unknown proposal type → high (conservative)
- Effective risk = max(type default, explicit proposal.risk_level)
- Invalid proposal.risk_level string raises `ProposalRiskLevelError` before any role check

`supported_apply_type` in `metadata_json`:
- `true` for proposal types with both a registered applier and an explicit policy
  risk-table entry (`SUPPORTED_PROPOSAL_TYPES`)
- `false` for unsupported/unknown types — proposal.apply denies before dispatch

At proposal accept time:
- `allow` → proceed to `ProposalApplyService.apply()`
- `require_approval` or `deny` → `enforceProposalApply()` raises `PolicyGateBlocked`; proposal stays pending

## Additional Enforcement Boundaries

### proposal.apply gate (wired)
`PgProposalApplyService.accept()` in `server/src/modules/proposals/applyService.ts`
calls `enforceProposalApply(...)` before applying accepted proposal side effects.

- Accepted proposals represent the human approval event.
- The acting user must have approval authority for the proposal type and effective risk level.
- `PolicyGateBlocked` is raised if denied or approval is required; the HTTP handler rolls back the request session, writes the blocking audit record independently, and returns 403.
- No durable write (MemoryEntry, Policy, Task, code patch) occurs on denial.
- `ProposalRiskLevelError` is raised for invalid proposal.risk_level; HTTP callers return 422.

### Memory placement invariant (wired)
Policy hard invariant in `server/src/modules/policy/decisionCore.ts` plus memory
proposal/apply validation — `visibility=private` only in personal spaces.

### Run user private scope (wired)
Memory/context read checks in `server/src/modules/memory/`,
`server/src/modules/context/`, and `server/src/modules/policy/decisionCore.ts`
govern private memory access in run context.

## Active Enforcement Points

### Policy Service / Policy Gateway (enforcement entry point)

`enforce(PolicyCheckRequest(...))` and `enforceProposalApply(...)` are the
preferred production entry points for sensitive policy decisions. Do not call
`PolicyEngine` or hard-invariant helpers directly to authorize or perform
sensitive actions.
The documented non-mutating simulation points may call `PolicyEngine`; they do
not persist `PolicyDecisionRecord`, and actual runtime execution still uses
the active policy service.

`DurablePolicyAuditWriter` writes only `PolicyDecisionRecord` using an independent
transaction. `PolicyGateBlocked` represents DENY and REQUIRE_APPROVAL. Local runtime
blocked paths call `write_blocked_gate_audit()` once; `PolicyAuditPersistError`
blocks a fail-closed action whose audit cannot be persisted. Business transactions
are never committed just to commit audit or lock rows.

### Wired enforcement points

`PolicyPort` is the only production enforcement entry point. `PolicyEngine` is internal to
the policy package except for the documented non-mutating simulation paths:
run creation, agent run preflight, standalone preflight, and automation policy
preflight.

| Action | File | When |
|---|---|---|
| `runtime.execute` | `server/src/modules/runs/orchestrationService.ts` | Before credentials, context snapshot, and adapter execution |
| `runtime.use_credential` | `server/src/modules/providers/providerCommandStore.ts` + run orchestration | Uses real credential/provider space from DB; before secret resolution |
| `context.inject_memory` | `server/src/modules/context/prepareService.ts` | Before context assembly/persistence |
| `context.render_for_runtime` | `server/src/modules/runs/orchestrationService.ts` | After context snapshot, before adapter execution |
| `artifact.persist` | `server/src/modules/runs/materializationService.ts` via `enforce()` | Before egress guard and filesystem/row persistence; fail-closed audit |
| `proposal.create` | `server/src/modules/proposals/` and target modules via `enforce()` | Code patch collection uses `force_record=True` |
| `proposal.apply` | `server/src/modules/proposals/applyService.ts` via `enforceProposalApply()` | Before accepted proposal side effects |
| `workspace.write_patch` | `server/src/modules/workspaces/` and proposal appliers via `enforce()` | Before any workspace file writes |
| `policy.change` | `server/src/modules/proposals/applyService.ts` via `enforceProposalApply()` | Protected by the `proposal.apply` gate for `policy_change` proposals |

**runtime.execute context fields**: Rule-relevant fields (`agent_status`, `agent_tool_permissions`,
`tool_name`, `adapter_type`, `trigger_origin`, `risk_level`, etc.) are passed in
`PolicyCheckRequest.context` so `PolicyEngine` rules can read them. Safe copies are
kept in `metadata_json` for audit only.

**runtime.execute actor semantics**: For manual/user-origin runs where
`instructed_by_user_id` is set and `trigger_origin == "manual"`, the actor is the
instructing user: `actor_type="user"`, `actor_id=instructed_by_user_id`. For
non-user-origin runs (automation, job, system), the actor is the run itself:
`actor_type="run"`, `actor_id=run.id`, with an `actor_ref` dict carrying
`{run_id, trigger_origin}` for traceability. `run_id` and `resource_id` always
refer to the run regardless of actor type.

**runtime.use_credential**: `resource_space_id` is resolved from the actual `Credential` row by ID,
not from `RuntimeAdapter.space_id`. If a `credential_id` exists but the `Credential` row is
missing, execution fails closed with `credential_metadata_missing` before any secret is resolved.

**proposal.create coverage**: `proposal.create` gates user-created memory proposals
and system-created code_patch proposals. The latter uses `force_record=True`;
durable memory mutation still occurs only behind `proposal.apply`.

### ProposalApplyService defense-in-depth

`ProposalApplyService.apply()` requires `accept_context` in `{"explicit_user_accept", "internal_seed"}`.
Direct calls without a valid `accept_context` must pass `bypass_source_monitoring=True` (test/seed paths only).

### Stateless Engine Rules

`PolicyEngine.check()` first calls `requireActionDefinition(action)`. Unknown actions
return DENY with `audit_code="unknown_policy_action"`. `BUILTIN_RULES` evaluated in order:

1. `rule_space_boundary` — deny cross-space access
2. `rule_agent_status` — deny `runtime.execute` and `memory.*` for non-active agents
3. `rule_memory_scope` — `require_approval` for `memory.create/update/archive` to protected scopes
4. `rule_use_credential` — same-space manual ALLOW; cross-space DENY (CRITICAL); automation REQUIRE_APPROVAL
5. `rule_tool_permission` — deny `runtime.execute` if tool/adapter not in agent allowlist
6. `rule_workspace_write_patch` — `require_approval` without proposal_id; `allow` with valid proposal
7. `rule_automation` — allow automation.create/update/fire for admin/owner; deny lower roles
8. `rule_runtime_execute_risk_level` — reflect context risk level on `runtime.execute`

Falls through to registry default only for **known** registered actions when no rule matches.

## Future Work

- **Wiring placeholder actions**: Each placeholder action in the registry needs a
  preferred `PolicyGateway.enforce()` call site before it becomes enforceable. Until
  wired, unknown-action fail-closed still applies if they are called without a registry
  entry, but having them registered means callers can at least look up metadata.
- `context.use_personal_grant` — add PolicyGateway call site in `personal_memory_grants/`
  when grant resolution merits its own policy audit trail; until then, egress guard is
  the enforcement boundary.
- `memory.create/update/archive` are WIRED_VIA_PROPOSAL — enforced only through `proposal.apply`.
- Extend approval resolver with per-user/per-project approval capabilities when needed.
- Space-level policy row overrides (currently domain-specific only).
- Future multi-agent child-run creation: design as `run.spawn_child` / `run.create_child`
  with explicit server policy and evaluation gates.
