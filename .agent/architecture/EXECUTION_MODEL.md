# Execution Model

## Core Objects

**Run** — the central execution object. Every formal agent execution has a durable Run. A run is created by user request, task, automation trigger, API call, or scheduled job. Run produces RunSteps, RunEvents, artifacts, and proposals. A Run also stores an immutable-at-creation `contract_snapshot_json` containing the source, project/workspace, acceptance and required-output declarations, risk, budget caps, and route hints used for that execution.

`runs.run_role` separates executable Runs from orchestration aggregates. An
`execution` Run owns physical `run_attempts` and may enter routing, adapter,
verification, and supervision. A `coordinator` Run is the root identity and
budget scope for one Plan or Workflow Execution; it never has an Attempt and
cannot be dispatched or supervised. Run lists and execution statistics exclude
coordinators by default, while graph detail surfaces expose them explicitly.

Workflow-backed Runs additionally carry nullable `workflow_version_id`, which
points to the approved evolvable workflow definition used at launch. Fixed
Workflow Automation materializes that version into a `WorkflowExecution` and
durable execution-node/run links. Agent Plans are a separate Task-owned
aggregate: the Agent planning Run proposes Plan Nodes, and a retained
`reference_workflow_version_id` is context only, never the Plan execution
source.

**RunStep** — coarse execution steps within a run. Provides the replay spine for failure diagnosis without reading raw adapter logs.

**RunEvent** — structured append-only harness evidence records within a run. Finer-grained than RunStep but coarser than raw adapter logs. Each RunEvent captures one significant phase (context compilation, runtime selection, sandbox creation, adapter invocation/completion, governed action invocation/completion, artifact ingestion, patch collection, validation, proposal creation, evaluation, finalization). Used by run finalization as the primary structured evidence source.

**RunFinalization** — canonical post-run record created by `PostRunFinalizationService` after a Run reaches a terminal state. Idempotent per `(run_id, attempt_number, finalizer_version)`, so a successful retry receives a fresh evaluation and downstream projection. Records run evaluation outcome, task evaluation bridge result, and skipped reasons. Append-only.

**RunAttempt** — one physical runtime execution under a logical Run. A queued
execution Run creates queued attempt 1 atomically; Supervisor retries create
the next attempt while preserving the logical Run id. Coordinator Runs never
create attempts. Attempt rows retain start/end/activity timestamps, exit and
error evidence, cancellation request/confirmation, and `orphaned` recovery
state. Usage is retained separately in `token_usage_events` and is keyed to
the logical Run.

Attempt evidence is append-per-attempt: `verification_results` rows are keyed
by `(run_id, attempt_number, verifier_type, verifier_version)` (re-verifying
the same attempt upserts; a retry never overwrites a prior attempt's rows),
`run_steps`/`run_events` are stamped with the attempt that produced them, and
evaluation classifies only the finalized attempt's stamped evidence plus
unstamped rows. `runs.output_json/error_json/exit_code` mirror the latest
attempt only. Usage is read from the canonical token ledger. A policy-pause
resume reuses the same attempt and merges
the approval grant into the attempt's `error_json` instead of clearing the
pause evidence; a dispatch that finds no reusable attempt backfills one marked
`attempt_backfilled_on_dispatch`.

### Task / Run / Attempt lifecycle invariants

1. One Attempt belongs to exactly one Run; `(space_id, run_id, attempt_number)`
   is unique and `attempt_number > 0`.
2. An execution Run has at least one Attempt from creation (same transaction);
   coordinator Runs never own Attempts.
3. `runs.status` and the max-attempt `run_attempts.status` move in the same
   transaction (single CTE dual-write path).
4. Retries only add Attempts; a terminal Attempt's error/exit evidence is never
   cleared or rewritten, and usage remains append-only in the token ledger.
5. A Run returns from a terminal status to `queued` only through a persisted
   `RunSupervisorDecision` for that attempt or an explicit human resume.
6. Crash recovery first terminalizes the orphaned Attempt, then the Supervisor
   creates a new Attempt; an Attempt is never moved from `orphaned` back to
   `running` in place.
7. Manually executing the same Task again creates a new Run and a new
   `task_runs` row through `max_runs` admission; terminal Runs are not reused.
8. `contract_snapshot_json` is immutable; routing/fallback replace `selected_*`
   state but never `requested_*` state.
9. A terminal Attempt (succeeded/failed/degraded/cancelled/orphaned) never
   returns to a non-terminal status; only a `waiting_for_review` policy pause
   resumes the same Attempt, and it must retain the pause evidence.
10. Finalization/evaluation/verification records are append-only per
    `(run_id, attempt_number)`.

**RunSupervisorDecision** — an idempotent durable policy decision for a terminal
attempt. The MVP aggregates `token_usage_events` across the logical Run,
classifies retryable structured error codes, enforces the contract attempt/cost
caps, and queues either a same-route retry or a C2 fallback-chain reroute. When
no eligible retry remains it moves the Run to `waiting_for_review`; explicit
runtime-profile selections remain hard pins and therefore cannot be rerouted.

**Job** — background system task (import, consolidation, backup, agent-run dispatch). Separate from Run. Job handlers create or dispatch Runs; jobs themselves are not product execution records.

Project Research is a workflow-level consumer of these execution primitives.
Its `baseline`, `historical_backfill`, and `incremental` run kinds are persisted
as `project_operations` progress, not as a second execution table. Source
backfill and post-processing jobs remain owned by Sources; the research
orchestrator only advances operation stages, links materialized artifacts, and
creates screening/idea checkpoints. A historical operation serializes workflow
state changes while allowing Source ingestion to continue through a persisted
pending-incremental queue.

Auto Research uses only the managed `model_api` path. Setup selects a
ModelProvider and optional model; the server provisions the system research
Agent/profile. Research source post-processing and synthesis Runs snapshot a
JSON Schema output contract in the Run contract, and plain-text output is a
terminal structured-output failure. OpenCode, Claude Code, and Codex remain
generic local CLI runtimes and are not part of the Research execution API.

**AgentRunGroup** — manager-owned multi-agent room for grouped runs. A group has
members, messages, delegations, one root run, and optional child runs. Human
users manage/review the group; child-run creation is server-owned and policy
gated through `run.spawn_child`. Managed API grouped runs can request child
runs through the authorized `agent.delegate` runtime tool and can pause on
other room results through `agent.wait_for_results`; frontend room
messages remain natural-language instructions, but the Tiptap composer resolves
structured `@agent` tokens into traceable recipient segments. No structured
mention defaults to the manager, adjacent mentions can fan out one segment to
multiple agents, separated mention groups create separate prompts, and the user
can explicitly choose Agent coordination to route the full turn to the manager
for decomposition/delegation instead of direct fan-out.

**Artifact** — durable output produced by a run. Stored under `artifact_storage_root`. Exportable within the owning space. `storage_path` is always relative to `artifact_storage_root`.

**Proposal** — requested durable change. Created by runs; reviewed by humans; applied by `ProposalApplyService`.

## RunStep Taxonomy

## Run contract snapshot

`runs.contract_snapshot_json` is written once when the Run is created and is
never refreshed from mutable Task, Automation, or Workflow configuration. The
snapshot is versioned as `run_contract.v1` and carries the source kind/id so a
later evaluation can distinguish a Task, Automation, Workflow, delegation, or
direct run.

Runtime request and routing outcome are separate. The immutable
`requested_runtime_profile_id` plus `runtime_profile_selection_source` record
the caller's intent. The current `runtime_profile_id`, `adapter_type`,
`model_provider_id`, runtime snapshot, and `route_decision_id` are selected
execution state. Public DTOs expose them with `selected_*` and
`active_route_decision_id` names. Routing and fallback retries may replace
selected state but never requested state; an explicit request remains a hard pin.

TaskRun creation copies the Task contract and project binding. Automation fire
copies the automation's validated contract configuration. Workflow run drafts
carry a server-resolved built-in template id/config; the Run creation route
re-resolves that template before constructing the snapshot. Direct runs get a
null-contract direct snapshot. When Task, Automation, and Workflow carriers
overlap, creation-time explicit precedence selects the highest-precedence cap;
without precedence the strictest cap wins. The snapshot records both the
declared carriers and the effective budget plus its resolution trace.

The enforcement boundary is deliberately narrow: `max_duration_seconds` caps
the adapter timeout, `max_runs` is resolved from the immutable budget source
precedence and enforced for Task, Automation, and Workflow/plan coordinator
admissions before dispatch. Plan child Runs carry `root_run_id`, so one
workflow fire is counted once rather than once per child; historical source
executions must remain below the cap,
`max_attempts` caps physical attempts for this logical Run, and `max_cost` is
enforced against the sum of `token_usage_events.estimated_cost_usd` before a
retry. The snapshot is exposed by the Run read model, while Task API mappings
expose the source contract fields.

When multiple sources occupy the effective `max_runs` precedence tier and
declare the same effective cap, admission locks and checks every such source;
the Task admission path performs this resolution before inserting either the
Run or its `task_runs` link. A dispatch check repeats the same source set from
the immutable snapshot, so inherited Automation/Workflow limits cannot first
fail after Task admission has already consumed a run count.

Every budget source carrying a cap is validated before admission: Task,
Automation, and Plan IDs must resolve to a current-space record, Workflow IDs
must resolve to an approved version under an active Workflow Asset whose
space and version scope are consistent with the current space, and missing or
foreign references fail closed. A direct Workflow Run
uses the same transaction for source validation, advisory-lock admission,
context snapshot, Run row, and initial attempt; a rejected cap therefore
cannot return a queued Run that will fail only when dispatched. Dispatch
repeats invalid-source detection and turns a malformed historical snapshot
into a failed Run rather than treating it as zero prior executions.

RunStep records the coarse execution spine of a run:

| Step kind | Meaning |
|---|---|
| `queued` | Run created, not yet started |
| `context_prepared` | Context assembled for adapter |
| `adapter_started` | Runtime adapter began execution |
| `adapter_completed` | Adapter returned a result |
| `artifact_created` | Artifact persisted from run output |
| `proposal_created` | Proposal created from run output |
| `failed` | Run failed; sanitized error captured in step |

RunSteps are **best-effort evidence**. They are savepoint-isolated from critical writes (run terminal state, memory, policy rows). A RunStep write failure must not poison the run's terminal state commit.

## RunEvent Taxonomy

RunEvent records the structured phase-level evidence spine of a run:

| event_type | Meaning |
|---|---|
| `context_compiled` | `ContextPrepareService` completed successfully |
| `runtime_selected` | Runtime adapter resolved; sandbox level decided |
| `credential_granted` | Credentials resolved for adapter |
| `sandbox_created` | Worktree sandbox created |
| `adapter_invoked` | Adapter.execute() called (status=running) |
| `adapter_completed` | Adapter returned; status succeeded/failed/cancelled |
| `artifact_ingested` | Produced artifact paths ingested |
| `patch_collected` | Code patch proposal collected; one per run attempt |
| `validation_started` | Worktree validation commands started |
| `validation_completed` | Worktree validation commands completed |
| `proposal_created` | Proposal created from run output |
| `evaluation_created` | RunEvaluation appended |
| `run_finalized` | RunFinalization completed or failed |
| `delegation_requested` | Agent group child-run delegation requested |
| `delegation_policy_denied` | `run.spawn_child` blocked a child-run delegation |
| `delegation_queued` | Child run created and queued for dispatch |
| `delegation_started` | Delegated child run started and the group delegation moved to running |
| `delegation_completed` | Delegated child run reached a terminal state and the group delegation result was projected |
| `action_invoked` | AgentToolGateway began a registry action call after exposure checks |
| `action_completed` | Registry action call returned a success or model-visible failed tool result |

RunEvent statuses: `pending`, `running`, `succeeded`, `failed`, `skipped`, `warning`, `cancelled`.

**RunEvent vs RunStep:** RunStep is the coarse lifecycle replay spine. RunEvent is the structured evidence spine used for classification. RunEvent references RunStep, Artifact, Proposal — it does not replace them.

**Append-only:** RunEvent rows are never updated or deleted. `event_index` uses MAX()+1 scoped to `(space_id, run_id)` — same documented distributed-writer risk as RunStep.

**Best-effort writes:** `safe_append_run_event()` wraps all instrumentation points in a savepoint. A RunEvent write failure must not poison Run terminal-state commits, artifact persistence, proposal creation, or evaluation creation.

**Never stored in RunEvent metadata:** raw credentials, stdout/stderr content, full rendered context text, full patch body, raw private memory text, complete file contents.

### Registry actions and Project Chat

Managed model tools dispatch through `AgentToolGateway` and
`SystemActionGateway`; see [SYSTEM_ACTIONS.md](SYSTEM_ACTIONS.md). Registry
visibility, run/profile capability exposure, and call-time PolicyGateway
enforcement are separate gates. Side-effecting calls use the canonical tool
call id as their idempotency key. Best-effort `action_invoked` /
`action_completed` RunEvents carry safe summaries and PolicyDecisionRecord ids;
their persistence failure does not block or roll back the action. Required
PolicyDecisionRecord persistence remains the fail-closed audit boundary.

Project Chat reuses the same session -> managed Run -> orchestration pipeline.
The session and Run persist the validated `project_id`; the prepared prompt
includes bounded Project name/description/focus context, and the run capability
set enables only proposal-producing source actions. Generated proposals are
returned as structured `action_previews` and persisted in assistant-message
metadata. A failed run also persists and returns any proposals already created
before failure. This preview is a pointer/read model, not proof of approval or
an alternate apply path.

Project Chat candidate collection suppresses the ordinary space-wide memory,
Knowledge, Source, and Activity selectors. It may include only the requested
Project's approved public summary in addition to the separately ACL-validated
bounded Project preamble.

RunStep error/metadata is filtered by `server/src/modules/runs/evidenceRedaction.ts` before persisting. Raw credential values are never stored in RunStep rows.

## Actor Identity on Execution Evidence

New audit, event, and RunStep surfaces carry actor identity via `actor_ref` (structured reference). Actor kinds: `user`, `agent`, `system`, `automation`, `connector`, `service_account`.

Existing Run and Proposal rows use separate nullable `*_user_id` and `*_agent_id` fields. New surfaces use `actor_ref`. These fields are not migrated in bulk; new records use actor_ref.

## Canonical Runtime Path

- **Canonical adapter catalog:** `RuntimeAdapterSpec` entries in
  `server/src/modules/runtimeAdapters/specs.ts`. Each entry declares the
  executor family and runtime capability/trust claims;
  `RunOrchestrationService` dispatches through that family map rather than
  enumerating adapter names.
- **Controlled CLI tools:** `runtimeTools` installs vendor CLI versions under
  `$AGENT_SPACE_HOME/runtime-tools`; only the `INSTANCE_ADMIN_EMAIL` user may
  install/activate instance tool versions.
- **Run authority:** server `runs` owns run execution, stop,
  top-level run read/status/trace, post-run evaluation/finalization, the
  internal `POST /internal/runs/execute` port, server execution locks, and
  `agent_run` job dispatch (the server entrypoint runs the worker loop;
  The agents module owns run creation subresources (`POST /agents/{id}/runs`
  and the singular legacy alias). Runtime context preparation, workspace
  sandbox preparation, artifact/proposal materialization, and finalization are
  native server.
- **Generic local CLI execution:** server `runs/vendorCliAdapter.ts`
  renders commands, grants CLI credential profiles through the server broker,
  prepares the server sandbox/worktree, invokes the local CLI process, parses
  output, and materializes produced artifacts/proposals. Runtime instruction
  files are rendered by server context preparation into the sandbox only.
  OpenCode may instead use a ModelProvider: the server writes a run-scoped
  OpenAI-compatible provider entry to the sandbox `opencode.json` and routes
  requests through the expiring provider proxy lease; provider API keys are
  not ambient subprocess environment variables.
- **Sandbox execution status:** `one_shot_docker` is the executor mode for
  critical local-CLI runs. `DockerCliCommandExecutor` mounts only the
  server-owned run sandbox, the read-only runtime-tools root, and at most one
  read-only credential profile. It enforces `--network none`, read-only root,
  dropped capabilities, no-new-privileges, PID/CPU/memory limits, and bounded
  tmpfs mounts. If Docker or the configured image is unavailable, execution
  fails closed; it never silently falls back to a worktree subprocess.
  `RunOrchestrationService.enforceRuntimePolicy` derives this upgrade from the
  immutable run contract's `risk_level`, so manual, plan, task, and automation
  entry points share the same critical-risk boundary.
- Run detail reads expose the immutable contract, verification results,
  attempt/supervisor history, route decision, and finalization history as
  separate panels. Saving a successful verified run as a workflow is a
  server-authoritative preview → save flow; the server decides whether the
  save is a draft or a proposal based on the run's recorded evidence and risk.
- **Space runtime policy:** space owners/admins manage
  `space_runtime_tool_policies`. Agent versions store the resolved
  `runtime_tool_version`, and runs fail closed before credential resolution if
  that version is unavailable, disabled, or disallowed for the active space.

Do not add new adapters to the agents module — it contains Agent/AgentVersion CRUD only.

### Runtime delegation boundary

System-level delegation is currently real only for managed API runs inside an
`AgentRunGroup`: `agent.delegate` and `agent.wait_for_results` are exposed
through the group and policy boundary. Vendor CLIs do not receive those
server-owned tools. A CLI may nevertheless create its own runtime-internal
subagents; that behavior is not uniformly controllable across runtimes.
Claude runs currently render and verify a run-scoped `.claude/settings.json`
denying the runtime-internal `Task` tool; OpenCode renders and verifies a
run-scoped locked-agent `opencode.json` denying Task and webfetch; Codex
remains `unknown` until its equivalent control is verified. Absence of a
server tool alone does not prove single-agent execution.

### Runtime capability declarations

The spec fields `subagent_support`, `subagent_disable_mechanism`,
`delegation_controllability`, `structured_output`, `checkpoint_resume`,
`cancellation_reliability`, `observability_level`, `side_effect_level`,
`data_exposure`, and `trust_level` are declarations used by later routing and
conformance work. They are intentionally conservative: Claude Code and
OpenCode declare runtime-configurable subagent disablement, Codex CLI remains
`unknown` until verified, and planned runtimes are not treated as executable merely because a
catalog entry exists. C3 turns these declarations into conformance-backed
route constraints.

The C3 MVP stores one result per runtime×version in
`runtime_conformance_results`. A result is `passed` only when every check in
the suite has an explicit passing observation; probe errors become failed
checks. The five MVP checks are file-scope obedience, subagent-attempt
detection, cancellation reliability, structured-output compliance, and
credential leakage. A runtime declaration is not itself conformance evidence.

The runtime execution lifecycle uses this external-call pattern:

1. Open short transaction → write run setup state → commit.
2. Call runtime adapter **outside** the transaction.
3. Open short transaction → write result or failure → commit.

## Runtime Policy Gates

`PolicyGateway` is the only enforcement entry point for all policy gates.
`PolicyEngine` is internal to the policy package; business services must not
call it directly to authorize or perform a sensitive action. `PreflightService`
may call it only for non-mutating dry-run simulation, which does not persist a
`PolicyDecisionRecord`. Actual runtime execution still uses `PolicyGateway`.

Policy gates run in this order inside server run orchestration:

1. **`runtime.execute`** — `PolicyGateway.enforce()` is called **before** credential resolution, context snapshot population, and `adapter.execute()`. Rule-relevant fields (`agent_status`, `agent_tool_permissions`, `tool_name`, `adapter_type`, `trigger_origin`, etc.) are passed in `PolicyCheckRequest.context`; safe audit copies remain in `metadata_json`. Blocking decisions raise `PolicyGateBlocked`, are written once through `write_blocked_gate_audit()`, and fail the run.

2. **`runtime.use_credential`** — called after adapter type resolution but
   **before** any ModelProvider key fetch or CLI profile release. The resource
   is the selected ModelProvider or CLI credential profile in the run's active
   space. Active-space grant resolution happens before secret/profile material
   is loaded; missing or disabled grants fail closed. Cross-space credential →
   hard DENY (CRITICAL). Automation origin → REQUIRE_APPROVAL. Same-space
   manual/api/delegation → ALLOW. DENY → `error_code=policy_denied_runtime_use_credential`.

3. **`context.inject_memory`** — called by server `ContextPrepareService` **before** memory context retrieval. Cross-space without grant → hard DENY. DENY → run context preparation fails closed.

4. **`context.render_for_runtime`** — called after context snapshot is assembled, **before** `adapter.execute()`. Cross-space without grant → hard DENY. DENY → `error_code=policy_denied_context_render_for_runtime`.

5. **`run.spawn_child`** — called by `AgentGroupRunService` before creating a
   delegated child run. The service proves same-space group membership, active
   group/member/agent status, parent-run agent identity, root lineage, and
   capacity limits. Public HTTP callers may post room messages, but child-run
   creation is initiated by authorized agent runtime output such as
   `agent.delegate`; callers may not directly forge agent-origin child-run
   spawns. Audit write failure is fail-closed and rolls back child-run creation.

None of these gates may be bypassed. No secret material is resolved before `runtime.use_credential` passes. No context is injected before `context.inject_memory` passes. No adapter is invoked before both `runtime.execute` and `context.render_for_runtime` pass.

**artifact.persist** — `RunMaterializationService` calls `PolicyGateway.enforce()` before the egress guard, filesystem write, or Artifact row creation. DENY and REQUIRE_APPROVAL call `write_blocked_gate_audit()` once and then raise `PersonalMemoryEgressError`. `PolicyAuditPersistError` and blocked-decision audit write failures block artifact persistence.

## Runtime Credential Resolver

`server/src/modules/providers` and the server credential broker are the
canonical runtime credential resolver.

- Resolves credentials through active-space grants: ModelProvider API keys from
  encrypted user-owned `Credential` rows, CLI login state from user-owned
  filesystem profiles.
- Runtime adapters must not read `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` from
  the ambient environment.
- Raw credential values are never stored in RunStep fields, artifact content, or logs.
- `server/src/modules/runs/evidenceRedaction.ts` redacts sensitive
  content before persisting runtime evidence.

## RunStep Replay and Failure Diagnosis

`GET /api/v1/runs/{id}/steps` returns ordered RunStep records.

`GET /api/v1/runs/{id}/trace` is the preferred reconstruction endpoint. It
aggregates the safe replay spine for a run in one response: Run,
AgentVersion, RuntimeAdapter, ModelProvider, ContextSnapshot metadata,
RunSteps, RunEvents, Artifacts, Proposals, parent, and children. It does not
inline artifact content, raw rendered context text, raw system prompt text, or
secret material.

This allows:
- Identifying which step failed and reading the sanitized error.
- Tracing artifact/proposal creation back to the step.
- Reconstructing a coarse run summary without raw adapter logs.

RunSteps are retained indefinitely (no auto-purge).

## Artifact and Proposal Linkage

- Artifacts carry `run_id` (FK to producing run).
- Proposals carry `run_id` (FK to producing run) when created from run output.
- `Proposal.payload_json["provenance_entries"]` links back to the ActivityRecord or run that produced the proposal.
- `ArtifactReadService.resolve_stored_file` rejects paths escaping `artifact_storage_root` or inside `sandbox_root`.

## Artifact Path Safety

`Artifact.storage_path` is always relative to `artifact_storage_root`. Export never serves files outside artifact storage root. Missing file returns 404, does not leak host path.

## Run Lifecycle

```
queued → running → terminal → finalized
                       ↘ supervisor retry → queued → running → terminal → finalized
queued → running → waiting_for_dependency → queued → running → terminal
```

**Terminal** means runtime execution has ended (status: `succeeded`, `failed`, `degraded`, or `cancelled`).

`waiting_for_dependency` is a non-terminal parked state for AgentRunGroup runs
that called `agent.wait_for_results`. The worker releases the execution lock and
the lifecycle projector requeues the same run after every declared dependency
run reaches a hard terminal state.

**Finalized** means `PostRunFinalizationService` has performed deterministic post-run evaluation and, when applicable, task-level evaluation bridging.

Before finalization, the A2 Verification Engine evaluates declared
deterministic checks in the live run sandbox and persists attempt-scoped
`verification_results` (keyed by run, attempt number, verifier type, and
verifier version; reads return the current attempt's rows). The execution
path emits `validation_started` and
`validation_completed` RunEvents. The verifier is server-owned and uses
`ValidationRecipe`/workspace profile command declarations plus Run contract
checks; it executes argv without a shell and bounds command time. The result
rows, not the runtime exit code, are the completion evidence for declared
checks. `manual_review` and `model_judge` are declared-but-skipped types until
their later phases implement the corresponding authority.

Automation should create Runs and call `POST /runs/{id}/finalize` after the run reaches a terminal state. Do not call internal evaluation services directly.

## PostRunFinalizationService — Canonical Post-Run Boundary

`PostRunFinalizationService` is the canonical post-run write boundary. It is the only service that should be called to trigger post-run evaluation and task bridging.

### API

- **`POST /api/v1/runs/{run_id}/finalize`** — finalize a terminal run; idempotent.
- **`GET /api/v1/runs/{run_id}/finalization`** — latest `RunFinalization` for the run.
- **`GET /api/v1/runs/{run_id}/finalizations`** — all `RunFinalization` records, newest first.
- **`POST /api/v1/runs/{run_id}/resume`** — human-approved requeue for a
  `waiting_for_review` Run; policy pauses resume the same attempt, while a
  Supervisor terminal hold starts a new explicitly authorized attempt.
- **`POST /api/v1/runs/{run_id}/abandon`** — human-reviewed abandon path that
  records a cancelled terminal outcome.

The finalize endpoint is the single write surface.

### What finalization does

1. Creates one `RunEvaluation`.
2. Dispatches the run-finalized hooks through the server finalization service. The tasks-owned `task_evaluation_bridge` hook creates one `TaskEvaluation` bridge row when a `TaskRun` link exists (`runs` never imports `tasks`; `tasks` registers the hook through the module registry).
3. Creates one `RunFinalization` row with `status=completed`.
4. Appends one `run_finalized` `RunEvent`.

When a Run has declared checks, finalization also includes the verification
summary in `RunEvaluation.evidence_json`; failed/error results map to the
`validation` layer and incomplete evidence cannot be classified as passed.

### What finalization does NOT do

- Does not mutate Run terminal status.
- Does not write MemoryEntry, Policy, WorkspaceProfile, ValidationRecipe, Capability, Artifact, or Proposal.
- Does not create RunReflection.
- Does not create learning proposals.
- Does not auto-apply anything.
- Does not call an LLM.
- Does not execute validators; validator execution belongs to the pre-cleanup
  Verification Engine boundary.

### Idempotency

Repeated calls to `POST /finalize` for the same `(run_id, attempt_number, finalizer_version)` return the existing completed `RunFinalization` without creating additional `RunEvaluation`, `TaskEvaluation`, or `run_finalized` event rows. A later physical attempt has a different attempt number and is finalized independently.

### Non-terminal rejection

Calling `POST /finalize` on a non-terminal run (queued, running, waiting_for_review) returns HTTP 422.

## RunEvaluation — Deterministic Harness Evaluation (Internal Primitive)

`RunEvaluation` is the canonical record for deterministic harness-level evaluation of a completed Run.

### Design principles

- **Append-only.** Each run finalization evaluation creates a new row. Existing evaluations are never deleted or overwritten. `GET /runs/{id}/evaluation` returns the most recent row.
- **Classifier-version auditable.** `evaluator_version` (e.g. `harness_eval.v1`) is stored per row, so classification history is preserved across version upgrades.
- **Harness-boundary evidence only.** Uses Run.status/error_json/output_json/exit_code, ordered RunSteps, RunEvents, ContextSnapshot metadata, Artifacts, Proposals, ValidationRecipe, and linked Task/TaskRun. No LLM-as-judge. No parsing of vendor CLI internal tool calls.
- **RunEvent as primary classification source.** RunEvent structured `error_code` fields are the canonical classification input for patch, artifact, adapter, and materialization event evidence. `output_json.materialization_errors` is never parsed as classifier evidence — it is a debug/summary field only.
- **Materialization outcomes are RunEvent-covered.** `RunMaterializationService` returns materialization items and failures. `RunOrchestrationService` emits `artifact_ingested` / `proposal_created` RunEvents for each output JSON artifact and proposal success and failure. Runtime output text persistence emits `artifact_ingested` on success and failure. All materialization error codes map to the `tool` failure_layer via `_EXACT_ERROR_CODE_MAP`. Activity materialization failures are represented as artifact_ingested warning events with metadata_json.kind="activity" to avoid expanding the RunEvent enum.
- **Evidence-only for CLI runtimes.** Local CLI runtimes are black-box at the harness. No internal tool-call trajectory is reconstructed from stdout/stderr.
- **Verification results are authoritative for declared checks.** The engine
  persists bounded result summaries before sandbox cleanup. RunEvaluation
  consumes them and remains a classifier, while TaskEvaluation projects the
  verification summary and failed/incomplete checks into its checklist and
  known issues.

### RunStep adapter_started semantics

`RunOrchestrationService` creates an `adapter_started` step and later marks it succeeded/failed via `complete_step`/`fail_step`. There is no required separate `adapter_completed` step.

**Evaluation treats `adapter_started` with status in {`succeeded`, `failed`, `cancelled`} as adapter completion from the harness perspective.**

`missing_adapter_completed` is only flagged when `adapter_started` exists AND is still in a non-terminal state (queued/running/pending) AND no `adapter_completed` step was recorded.

### Classification pipeline

**A. outcome_status** (ordered rules):
1. Non-terminal status → `unknown`
2. `status == failed` → `failed`
3. `status == cancelled` → `failed` (`run_cancelled` synthesized into error codes so B2 exact map → `orchestration / run_cancelled`)
4. `exit_code != 0` → `failed`
5. `error_json` present → `failed`
6. `status == degraded` → `partial`
7. Succeeded + failed/error verification result → `failed`
8. Succeeded + skipped/missing declared verification → `unknown`
9. Succeeded + validation-failed proposal → `partial`
10. Succeeded + incomplete patch or materialization warning → `partial`
11. `status == succeeded` → `passed`
12. Otherwise → `unknown`

**B. failure_layer** (ordered rules, exact error-code mapping first):
1. outcome passed/unknown → null
2. Exact error-code mapping (canonical list in `server/src/modules/runs/finalizationService.ts::EXACT_ERROR_CODE_MAP`) — overrides all heuristics
3. Missing context snapshot (for runs that require one) → `context`
4. Validation failure signals → `validation`
5. `sandbox` keyword in failed step error_type → `sandbox`
6. Missing adapter completion → `orchestration`
7. Adapter step failed or non-zero exit → `runtime`
8. `tool` keyword in step error_type → `tool`
9. Otherwise → `unknown`

**C. trajectory_status**:
- `insufficient_evidence` — no steps, no snapshot, no artifacts, no proposals
- `unsafe` — high-risk proposal (`risk_level=high/critical`) or low-trust artifact
- `incomplete` — incomplete patch signals, adapter not yet terminal, or no terminal step
- `acceptable`

Note: `trajectory_status` does not imply `failure_layer`. A run can be `outcome_status=passed` and `trajectory_status=unsafe`.

### Canonical error-code mappings

`file_access_adapter_requires_worktree_policy` → `policy` (not `sandbox`; exact map runs first).

Materialization error codes → `tool` failure_layer (all via exact map):
- `produced_artifact_ingestion_error` — produced artifact path ingestion failure
- `runtime_output_artifact` — runtime output text persistence failure
- `output_artifact_materialization_error` — adapter output_json artifact spec failure
- `output_proposal_materialization_error` — adapter output_json proposed_change spec failure
- `output_activity_materialization_error` — adapter output_json activity spec failure
- `code_patch_collection_error` — worktree patch collection exception

### What evaluation does NOT do

- Does not write MemoryEntry, Policy, Proposal, Capability, WorkspaceProfile, or ValidationRecipe.
- Run finalization does not create RunReflection; task-level evaluation is created through the task evaluation bridge.
- Does not mutate Run, Artifact, or Proposal rows.
- Does not auto-apply any Proposal.

## Evolvable-Asset Evaluation Harness (D2)

The evaluation harness applies the Verification Engine to an
`evaluation_cases` fixture's stored baseline output and a system-produced
candidate run's stored output for comparison. Cases may be created directly with an
explicit read-only fixture or from a visible successful/degraded Run whose
latest `RunEvaluation` passed. The case records its input, expectation,
verification recipe, baseline version, and source run; sensitive fixture data
is sanitized and bounded before persistence.

`POST /api/v1/evolution/assets/:assetId/versions/:versionId/evaluation-cases/:caseId/execute`
requires a `candidate_run_id` and creates an `evolvable_asset_evaluation` job.
The worker re-reads that run's durable output after validating its visibility,
terminal status, passed post-run evaluation, and exact candidate-version pin.
It then evaluates candidate and baseline outputs with
`verification_engine.v1`'s output-checking core, stores structured scores,
check evidence, and regression blockers in
`evolvable_asset_evaluation_runs`, and updates the candidate's latest
evaluation summary. This MVP does not execute a candidate from `input_json`
inside the evaluation job; the candidate run must already have been produced
by the normal run authority. The evaluation job is read-only and has no shell,
network, or write-capable connector authority. Unsupported checks produce an
error/failed evaluation and never a pass.

Promotion proposals embed a database-derived evaluation summary and a policy.
The default is `warn_only`, so promotion can proceed with a visible warning.
The caller may request `hard_gate`; additionally, high/critical-risk assets
automatically switch to hard-gate after five active evaluation cases. The
applier re-queries evaluation rows and only accepts a passed
`verification_engine.v1` evaluation created by the evaluation-case executor.
Proposal payload summaries are evidence, not authorization. Public metadata
recording cannot forge a passed engine evaluation.

## TaskEvaluation — Task-Level Evaluation Bridge

`TaskEvaluation` records task-level evaluation results. It is downstream of `RunEvaluation` and populated via the task evaluation bridge.

### Evaluation layers

| Layer | Class | Scope | Append-only |
|---|---|---|---|
| Harness | `RunEvaluation` | Per-Run, deterministic, harness-boundary evidence | Yes |
| Task bridge | `TaskEvaluation` | Per-Task, mapped from RunEvaluation | Yes |

### Design principles

- **Append-only.** Each task evaluation bridge call creates a new row. Old rows are never overwritten or deleted.
- **Task ↔ Run source of truth is `TaskRun`.** There is no `runs.task_id` column; all task-run linkage checks use `TaskRun` rows.
- **RunEvaluation bridge.** The task evaluation bridge maps an existing `RunEvaluation` to a new `TaskEvaluation` row during finalization when `TaskRun` linkage exists — do not call it directly from API routes.
- **Does not mutate Task.status.**
- **Does not write MemoryEntry, Policy, Proposal, RunReflection, or any learning object.**
- **Invoked by finalization.** `POST /runs/{id}/finalize` orchestrates both RunEvaluation and TaskEvaluation bridge through `PostRunFinalizationService`. There is no separate public API for creating TaskEvaluation bridge rows from a Run.
- **ValidationRecipe is an input/criteria source.** It flows in at the top of the execution loop alongside `WorkspaceProfile` and informs `RunEvaluation` classification. It is not downstream of `TaskEvaluation`.

### Evidence artifact linkage rule

| Creation path | Evidence source | TaskArtifact required |
|---|---|---|
| Bridge (`create_from_run_evaluation`) | Artifacts linked to the evaluated Run via `Artifact.run_id` | No |
| Manual (`create_manual_task_evaluation`) | Caller-supplied `evidence_artifact_ids` | Yes — all IDs must be linked through `TaskArtifact` |

When a manual task evaluation also supplies `run_id`, that run must be linked to
the task through `TaskRun`, and each evidence artifact must be linked through a
`TaskArtifact` row whose `run_id` matches the evaluation run. Bridge rows do not
create `TaskArtifact` rows as a side effect.

### Deterministic mapping from RunEvaluation.outcome_status

| outcome_status | score | recommendation | confidence |
|---|---|---|---|
| `passed` | 1.0 | `accept` | 1.0 |
| `partial` | 0.5 | `review` | 0.7 |
| `failed` | 0.0 | `retry` | 1.0 |
| `unknown` | null | `needs_evidence` | 0.3 |

`evaluator_type` is always `run_evaluation_bridge` for bridge-created rows.

### RunReflection

`RunReflection` is not automatically created by run or task finalization. It is populated externally (import, manual entry, or future evaluator output) and acts as the source for `ReflectionProposalBuilder`.

### Learning Loop Apply Path

`ReflectionProposalBuilder` creates pending proposal candidates from a `RunReflection`. Accepted proposals are applied through `ProposalApplyService`.

**Supported apply types (from reflection):**
- `follow_up_task` — accepted proposal creates a `Task` row. This is the first low-risk learning apply path.

**Unsupported apply types (remain pending-only):**
- `workspace_profile_update`, `validation_recipe_update`, `capability_update`, `policy_update` — accepted proposals raise `UnsupportedProposalTypeError`.

Automation manual and schedule-triggered fire queue runs through the existing
runtime gates. The `/automations` UI supports agent-run, maintenance, and
versioned Workflow targets. Workflow targets carry `workflow_asset_key`,
`workflow_resolution`, optional `workflow_version_id`, and `input_json`;
scheduled Workflow targets are pinned for reproducibility. Each fire creates a
`WorkflowExecution` and `automation_runs.workflow_execution_id`; it does not
create a Plan or `plan_review`. Schedule automations can carry same-space
`AutomationCredentialGrant` pre-authorization. No external trigger is
implemented. No proposal type auto-applies without user acceptance.

### Future Work

- Runtime session checkpoint/fork/resume semantics remain open under A3.1;
  the current Run Detail Resume action only resumes a `waiting_for_review` Run
  through the existing server endpoint and is not a runtime-session checkpoint.
- Apply handlers for `workspace_profile_update`, `validation_recipe_update`, `capability_update`, `policy_update`.

## What Is Intentionally Not Modeled Yet

- Full tool-call ontology (individual tool invocation records per step).
- Token-level traces.
- Sub-agent orchestration schema.
- Cost accounting per run or step.
- Vendor-specific trace schema.
