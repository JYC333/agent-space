# System Actions and Agent Tool Gateway

## Purpose and source of truth

System actions are the typed inventory of application capabilities that may be
exposed through HTTP, managed-agent tools, internal jobs, or server-only calls.
They do not replace policy actions: a system action describes what can be
invoked, while its `policy_action` identifies the mandatory enforcement gate.

The canonical definition list is `SYSTEM_ACTION_REGISTRY` in
`packages/protocol/src/systemActions.ts`. Server loading and semantic
validation live in `server/src/modules/systemActions/registry.ts`.
`POLICY_ACTION_REGISTRY` in `packages/protocol/src/policy.ts` remains the
canonical policy vocabulary.

Every system action declares:

- stable dotted id and version;
- visibility (`internal_only`, `agent_tool`, `public_api`, `external_mcp`, or
  `system_job`);
- allowed actor types;
- input/output Zod schemas;
- owning module and application-service boundary;
- policy action, side-effect class, idempotency requirement, proposal type,
  and whether advance approval grants may apply.

There are currently no `external_mcp` actions. Adding an MCP wrapper requires a
separate authenticated/rate-limited public design; it must not expose the agent
gateway directly.

## Dispatch boundary

`SystemActionGateway` performs registry lookup, actor and visibility checks,
idempotency validation, input validation, policy enforcement, executor lookup,
and output validation in that order. Unknown actions, missing executors,
unsupported actor/visibility combinations, missing idempotency keys, invalid
schemas, and denied policy decisions fail closed.

The gateway is actor-neutral. HTTP routes continue to call their owning
application services and `PolicyGateway` enforcement points. Server jobs may
use internal/system-job actions. Managed model runs use `AgentToolGateway`, the
agent-specific adapter over `SystemActionGateway`.

## Managed-agent exposure

`AgentToolGateway` composes retrieval, delegation, and enabled generic actions
for a managed run. Exposure requires all of:

1. registry visibility includes `agent_tool` and actor type includes `agent`;
2. the immutable AgentVersion `tool_permissions_json.allowed_tools` permits the
   action and the action is present in `runs.capabilities_json`;
3. a call-time PolicyGateway decision allows the registered policy action.

The currently enabled generic write-capable tools are proposal-only:
`source.connection.propose_create`, `project.source.propose_bind`, and
`source.backfill.propose_start`. They receive the run's space, agent, instructed
user, run, and Project scope. Project-only actions reject an unscoped run;
backfill proposal lookup also proves the plan belongs to that Project. Agents
do not receive direct activation, proposal-apply, grant-management, credential,
deployment, or memory-write actions.

These three tools have concrete Zod input contracts and matching model-visible
JSON schemas. Missing connection, plan, or required connection-draft fields are
rejected before policy enforcement or executor dispatch.

Retrieval and delegation retain their domain-specific policy adapters behind
the gateway. An action without a canonical policy adapter is denied. Tool-call
failures are returned as structured tool results so one denied action does not
silently become an ungoverned execution path.

## Audit and idempotency

Managed action dispatch emits best-effort RunEvents `action_invoked` and
`action_completed`. Completion metadata includes the safe action summary and
PolicyDecisionRecord id; failures use `action_completed` with `ok=false` and a
safe error code. RunEvent persistence failure does not roll back or block an
action. The fail-closed audit boundary is PolicyGateway decision-record
persistence according to the policy action's `record_failure_mode`.

Side-effecting definitions require an idempotency key. Managed calls use the
canonical tool-call id. Proposal-producing services additionally persist
`created_by_run_id` plus `action_idempotency_key`, so replay returns the same
proposal rather than duplicating a draft or mutation.

## Proposal and approval-grant boundary

Agent-initiated durable source changes always create a normal proposal first.
`ProposalApplyService` is the only apply boundary and reruns `proposal.apply`
policy and domain authorization in the apply transaction.

`action_approval_grants` are human-created, revocable advance approvals scoped
to space, agent, action, and optional Project/resource, with expiry and optional
use limit. A matching grant may cause the just-created agent proposal to be
accepted immediately through the same apply service; it records the grant as
the approval source and increments usage atomically. Expired, revoked,
exhausted, or scope/payload/type-mismatched grants leave the proposal pending.

Only registry actions marked `grantable` can use this path. Grant create/revoke
are user-only public actions and are not agent tools. Proposal apply, memory
writes, credentials, policy override, and deployment remain fresh-human-review
boundaries.

## Current source and Project actions

The registry covers recipe planning/creation/dry-run/activation, connection
create/update/propose/activate, Project binding/proposal actions,
ProjectOperation read/create/status changes, history-import preview/plan/
proposal/pause/resume, and internal approved backfill start. Sources owns
connection and history-import execution state; Projects owns binding,
operation, corpus, and Project chat consumption state.

Project Chat is not a second execution pipeline. It creates a Project-scoped
session and managed Run, enables the three proposal actions above, and returns
safe `action_previews`. The same previews are stored on the assistant message
metadata and link to canonical Review proposals.

## Invariants

- Registry absence, policy-adapter absence, or unknown action means deny.
- Visibility metadata is an exposure ceiling, never authorization by itself.
- Agents create proposals; they do not apply them directly.
- A grant never changes the proposal payload or bypasses apply-time checks.
- Credentials are resolved by their owning service and never accepted as tool
  payload secrets.
- `external_mcp` remains empty until separately designed.
- RunEvent/action audit metadata contains no prompts, credentials, raw source
  content, stdout, or stderr.
