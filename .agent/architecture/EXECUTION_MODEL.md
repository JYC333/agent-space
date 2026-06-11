# Execution Model

## Core Objects

**Run** — the central execution object. Every formal agent execution has a durable Run. A run is created by user request, task, automation trigger, API call, or scheduled job. Run produces RunSteps, RunEvents, artifacts, and proposals.

**RunStep** — coarse execution steps within a run. Provides the replay spine for failure diagnosis without reading raw adapter logs.

**RunEvent** — structured append-only harness evidence records within a run. Finer-grained than RunStep but coarser than raw adapter logs. Each RunEvent captures one significant phase (context compilation, runtime selection, sandbox creation, adapter invocation/completion, artifact ingestion, patch collection, validation, proposal creation, evaluation, finalization). Used by RunEvaluationService as the primary structured evidence source.

**RunFinalization** — canonical post-run record created by `PostRunFinalizationService` after a Run reaches a terminal state. Idempotent per `(run_id, finalizer_version)`. Records run evaluation outcome, task evaluation bridge result, and skipped reasons. Append-only.

**Job** — background system task (import, consolidation, backup, agent-run dispatch). Separate from Run. Job handlers create or dispatch Runs; jobs themselves are not product execution records.

**Artifact** — durable output produced by a run. Stored under `artifact_storage_root`. Exportable within the owning space. `storage_path` is always relative to `artifact_storage_root`.

**Proposal** — requested durable change. Created by runs; reviewed by humans; applied by `ProposalApplyService`.

## RunStep Taxonomy

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
| `context_compiled` | ContextSnapshotPopulator completed successfully |
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

RunEvent statuses: `pending`, `running`, `succeeded`, `failed`, `skipped`, `warning`, `cancelled`.

**RunEvent vs RunStep:** RunStep is the coarse lifecycle replay spine. RunEvent is the structured evidence spine used for classification. RunEvent references RunStep, Artifact, Proposal — it does not replace them.

**Append-only:** RunEvent rows are never updated or deleted. `event_index` uses MAX()+1 scoped to `(space_id, run_id)` — same documented distributed-writer risk as RunStep.

**Best-effort writes:** `safe_append_run_event()` wraps all instrumentation points in a savepoint. A RunEvent write failure must not poison Run terminal-state commits, artifact persistence, proposal creation, or evaluation creation.

**Never stored in RunEvent metadata:** raw credentials, stdout/stderr content, full rendered context text, full patch body, raw private memory text, complete file contents.

RunStep error/metadata is filtered by `app/runs/redaction.py` before persisting. Raw credential values are never stored in RunStep rows.

## Actor Identity on Execution Evidence

New audit, event, and RunStep surfaces carry actor identity via `actor_ref` (structured reference). Actor kinds: `user`, `agent`, `system`, `automation`, `connector`, `service_account`.

Existing Run and Proposal rows use separate nullable `*_user_id` and `*_agent_id` fields. New surfaces use `actor_ref`. These fields are not migrated in bulk; new records use actor_ref.

## Canonical Runtime Path

- **Canonical adapter catalog:** `RuntimeAdapterSpec` entries in `backend/app/runtimes/specs.py`
- **Configured runtime instances:** `RuntimeAdapter` rows scoped to a space
- **Generic local CLI execution:** `backend/app/runtimes/adapters/cli_runtime.py` renders commands, grants CLI credential profiles, invokes `LocalExecutor`, and parses output

Do not add new adapters to `app.agents` — it contains Agent/AgentVersion CRUD only.

`RunExecutionService` owns the runtime execution lifecycle. Required external-call pattern:

1. Open short transaction → write run setup state → commit.
2. Call runtime adapter **outside** the transaction.
3. Open short transaction → write result or failure → commit.

## Runtime Policy Gates

`PolicyGateway` is the only enforcement entry point for all policy gates.
`PolicyEngine` is internal to the policy package; business services must not
call it directly to authorize or perform a sensitive action. `PreflightService`
may call it only for non-mutating dry-run simulation, which does not persist a
`PolicyDecisionRecord`. Actual runtime execution still uses `PolicyGateway`.

Policy gates run in this order inside `RunExecutionService._execute_real_adapter_path()`:

1. **`runtime.execute`** — `PolicyGateway.enforce()` is called **before** credential resolution, context snapshot population, and `adapter.execute()`. Rule-relevant fields (`agent_status`, `agent_tool_permissions`, `tool_name`, `adapter_type`, `trigger_origin`, etc.) are passed in `PolicyCheckRequest.context`; safe audit copies remain in `metadata_json`. Blocking decisions raise `PolicyGateBlocked`, are written once through `write_blocked_gate_audit()`, and fail the run.

2. **`runtime.use_credential`** — called after adapter type resolution but **before** any secret fetch. `resource_space_id` is resolved from the actual `Credential` row by ID — never inferred from `RuntimeAdapter.space_id`. If `credential_id` exists but the `Credential` row is missing, execution fails closed with `error_code=credential_metadata_missing`. Cross-space credential → hard DENY (CRITICAL). Automation origin → REQUIRE_APPROVAL. Same-space manual/api → ALLOW. DENY → `error_code=policy_denied_runtime_use_credential`.

3. **`context.inject_memory`** — called in `ContextSnapshotPopulator.populate()` **before** `ContextBuilder.build()`. Cross-space without grant → hard DENY. DENY → RuntimeError with `[error_code=policy_denied_context_inject_memory]`.

4. **`context.render_for_runtime`** — called after context snapshot is assembled, **before** `adapter.execute()`. Cross-space without grant → hard DENY. DENY → `error_code=policy_denied_context_render_for_runtime`.

None of these gates may be bypassed. No secret material is resolved before `runtime.use_credential` passes. No context is injected before `context.inject_memory` passes. No adapter is invoked before both `runtime.execute` and `context.render_for_runtime` pass.

**artifact.persist** — `ArtifactPersistenceService` calls `PolicyGateway.enforce()` before the egress guard, filesystem write, or Artifact row creation. DENY and REQUIRE_APPROVAL call `write_blocked_gate_audit()` once and then raise `PersonalMemoryEgressError`. `PolicyAuditPersistError` and blocked-decision audit write failures block artifact persistence.

## Runtime Credential Resolver

`runtimes/credentials.py` is the canonical resolver.

- Resolves credentials from `ModelProvider` encrypted config, not env variables directly.
- Runtime adapters must not read `ANTHROPIC_API_KEY` from the environment.
- Raw credential values are never stored in RunStep fields, artifact content, or logs.
- `app/runs/redaction.py` redacts sensitive content before persisting.

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
```

**Terminal** means runtime execution has ended (status: `succeeded`, `failed`, `degraded`, or `cancelled`).

**Finalized** means `PostRunFinalizationService` has performed deterministic post-run evaluation and, when applicable, task-level evaluation bridging.

Automation should create Runs and call `POST /runs/{id}/finalize` after the run reaches a terminal state. Do not call internal evaluation services directly.

## PostRunFinalizationService — Canonical Post-Run Boundary

`PostRunFinalizationService` is the canonical post-run write boundary. It is the only service that should be called to trigger post-run evaluation and task bridging.

### API

- **`POST /api/v1/runs/{run_id}/finalize`** — finalize a terminal run; idempotent.
- **`GET /api/v1/runs/{run_id}/finalization`** — latest `RunFinalization` for the run.
- **`GET /api/v1/runs/{run_id}/finalizations`** — all `RunFinalization` records, newest first.

The finalize endpoint is the single write surface.

### What finalization does

1. Calls `RunEvaluationService.evaluate()` to create one `RunEvaluation`.
2. Dispatches the run-finalized hooks (`app.runs.lifecycle_hooks.RunFinalizedHookRegistry`). The tasks-owned `task_evaluation_bridge` hook creates one `TaskEvaluation` bridge row via `TaskEvaluationService.create_from_run_evaluation()` when a `TaskRun` link exists (`runs` never imports `tasks`; `tasks` registers the hook through the module registry).
3. Creates one `RunFinalization` row with `status=completed`.
4. Appends one `run_finalized` `RunEvent`.

### What finalization does NOT do

- Does not mutate Run terminal status.
- Does not write MemoryEntry, Policy, WorkspaceProfile, ValidationRecipe, Capability, Artifact, or Proposal.
- Does not create RunReflection.
- Does not create learning proposals.
- Does not auto-apply anything.
- Does not call an LLM.

### Idempotency

Repeated calls to `POST /finalize` for the same `(run_id, finalizer_version)` return the existing completed `RunFinalization` without creating additional `RunEvaluation`, `TaskEvaluation`, or `run_finalized` event rows.

### Non-terminal rejection

Calling `POST /finalize` on a non-terminal run (queued, running, waiting_for_review) returns HTTP 422.

## RunEvaluation — Deterministic Harness Evaluation (Internal Primitive)

`RunEvaluation` is the canonical record for deterministic harness-level evaluation of a completed Run.

### Design principles

- **Append-only.** Each `RunEvaluationService.evaluate()` call creates a new row. Existing evaluations are never deleted or overwritten. `GET /runs/{id}/evaluation` returns the most recent row.
- **Classifier-version auditable.** `evaluator_version` (e.g. `harness_eval.v1`) is stored per row, so classification history is preserved across version upgrades.
- **Harness-boundary evidence only.** Uses Run.status/error_json/output_json/exit_code, ordered RunSteps, RunEvents, ContextSnapshot metadata, Artifacts, Proposals, ValidationRecipe, and linked Task/TaskRun. No LLM-as-judge. No parsing of vendor CLI internal tool calls.
- **RunEvent as primary classification source.** RunEvent structured `error_code` fields are the canonical classification input for patch, artifact, adapter, and materialization event evidence. `output_json.materialization_errors` is never parsed as classifier evidence — it is a debug/summary field only.
- **Materialization outcomes are RunEvent-covered.** `RunOutputMaterializer` returns a `MaterializationResult` (artifact_items, proposal_items, failed_items). `RunExecutionService` emits `artifact_ingested` / `proposal_created` RunEvents for each output JSON artifact and proposal success and failure. Runtime output text persistence emits `artifact_ingested` on success and failure. All materialization error codes map to the `tool` failure_layer via `_EXACT_ERROR_CODE_MAP`. Activity materialization failures are represented as artifact_ingested warning events with metadata_json.kind="activity" to avoid expanding the RunEvent enum.
- **Evidence-only for CLI runtimes.** Local CLI runtimes are black-box at the harness. No internal tool-call trajectory is reconstructed from stdout/stderr.

### RunStep adapter_started semantics

`RunExecutionService` creates an `adapter_started` step and later marks it succeeded/failed via `complete_step`/`fail_step`. There is no required separate `adapter_completed` step.

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
7. Succeeded + validation-failed proposal → `partial`
8. Succeeded + incomplete patch or materialization warning → `partial`
9. `status == succeeded` → `passed`
10. Otherwise → `unknown`

**B. failure_layer** (ordered rules, exact error-code mapping first):
1. outcome passed/unknown → null
2. Exact error-code mapping (canonical list in `evaluation.py:_EXACT_ERROR_CODE_MAP`) — overrides all heuristics
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
- `RunEvaluationService` does not create TaskEvaluation or RunReflection; task-level evaluation is created through `TaskEvaluationService`.
- Does not mutate Run, Artifact, or Proposal rows.
- Does not auto-apply any Proposal.

## TaskEvaluation — Task-Level Evaluation Bridge

`TaskEvaluation` records task-level evaluation results. It is downstream of `RunEvaluation` and populated via `TaskEvaluationService`.

### Evaluation layers

| Layer | Class | Scope | Append-only |
|---|---|---|---|
| Harness | `RunEvaluation` | Per-Run, deterministic, harness-boundary evidence | Yes |
| Task bridge | `TaskEvaluation` | Per-Task, mapped from RunEvaluation | Yes |

### Design principles

- **Append-only.** Each `TaskEvaluationService` call creates a new row. Old rows are never overwritten or deleted.
- **Task ↔ Run source of truth is `TaskRun`.** `Run.task_id` is a denormalized shortcut only. All task-run linkage checks use `TaskRun` rows.
- **RunEvaluation bridge.** `TaskEvaluationService.create_from_run_evaluation()` maps an existing `RunEvaluation` to a new `TaskEvaluation` row. It is invoked by the tasks-owned `task_evaluation_bridge` run-finalized hook (`app.tasks.run_lifecycle`) during finalization when `TaskRun` linkage exists — do not call it directly from API routes.
- **Does not mutate Task.status.**
- **Does not write MemoryEntry, Policy, Proposal, RunReflection, or any learning object.**
- **Invoked by finalization.** `POST /runs/{id}/finalize` orchestrates both RunEvaluation and TaskEvaluation bridge through `PostRunFinalizationService`. There is no separate public API for creating TaskEvaluation bridge rows from a Run.
- **ValidationRecipe is an input/criteria source.** It flows in at the top of the execution loop alongside `WorkspaceProfile` and informs `RunEvaluation` classification. It is not downstream of `TaskEvaluation`.

### Evidence artifact linkage rule

| Creation path | Evidence source | TaskArtifact required |
|---|---|---|
| Bridge (`create_from_run_evaluation`) | Artifacts linked to the evaluated Run via `Artifact.run_id` | No |
| Manual (`create_manual_task_evaluation`) | Caller-supplied `evidence_artifact_ids` | Yes — all IDs must be linked through `TaskArtifact` |

Bridge rows do not create `TaskArtifact` rows as a side effect.

### Deterministic mapping from RunEvaluation.outcome_status

| outcome_status | score | recommendation | confidence |
|---|---|---|---|
| `passed` | 1.0 | `accept` | 1.0 |
| `partial` | 0.5 | `review` | 0.7 |
| `failed` | 0.0 | `retry` | 1.0 |
| `unknown` | null | `needs_evidence` | 0.3 |

`evaluator_type` is always `run_evaluation_bridge` for bridge-created rows.

### RunReflection

`RunReflection` is not automatically created by `RunEvaluationService` or `TaskEvaluationService`. It is populated externally (import, manual entry, or future evaluator output) and acts as the source for `ReflectionProposalBuilder`.

### Learning Loop Apply Path

`ReflectionProposalBuilder` creates pending proposal candidates from a `RunReflection`. Accepted proposals are applied through `ProposalApplyService`.

**Supported apply types (from reflection):**
- `follow_up_task` — accepted proposal creates a `Task` row. This is the first low-risk learning apply path.

**Unsupported apply types (remain pending-only):**
- `workspace_profile_update`, `validation_recipe_update`, `capability_update`, `policy_update` — accepted proposals raise `UnsupportedProposalTypeError`.

Automation manual and schedule-triggered fire queue runs through the existing
runtime gates. Schedule automations can carry same-space
`AutomationCredentialGrant` pre-authorization. No external trigger is
implemented. No proposal type auto-applies without user acceptance.

### Future Work

- Run Viewer UI — surface for browsing RunEvent and RunEvaluation history per run.
- Apply handlers for `workspace_profile_update`, `validation_recipe_update`, `capability_update`, `policy_update`.

## What Is Intentionally Not Modeled Yet

- Full tool-call ontology (individual tool invocation records per step).
- Token-level traces.
- Sub-agent orchestration schema.
- Cost accounting per run or step.
- Vendor-specific trace schema.
