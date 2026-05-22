# Execution Model

## Core Objects

**Run** — the central execution object. Every formal agent execution has a durable Run. A run is created by user request, task, automation trigger, API call, or scheduled job. Run produces RunSteps, artifacts, and proposals.

**RunStep** — coarse execution steps within a run. Provides the replay spine for failure diagnosis without reading raw adapter logs.

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

RunStep error/metadata is filtered by `app/runs/redaction.py` before persisting. Raw credential values are never stored in RunStep rows.

## Actor Identity on Execution Evidence

New audit, event, and RunStep surfaces carry actor identity via `actor_ref` (structured reference). Actor kinds: `user`, `agent`, `system`, `automation`, `connector`, `service_account`.

Existing Run and Proposal rows use separate nullable `*_user_id` and `*_agent_id` fields. New surfaces use `actor_ref`. These fields are not migrated in bulk; new records use actor_ref.

## Canonical Runtime Path

- **Canonical for new adapters:** `core/backend/app/runtimes/` (subclass `BaseRuntimeAdapter`, register in `registry.py`)
- **CLI subprocess wrappers:** `core/backend/app/cli_adapters/` (detection, probing, subprocess execution via `LocalExecutor`/`DockerExecutor`)
- **CLI bridge:** `core/backend/app/runtimes/adapters/cli_runtime.py` — the only point that imports CLI adapter classes and converts their output to `RuntimeAdapterResult`

Do not add new adapters to `app.agents` — it contains Agent/AgentVersion CRUD only.

`RunExecutionService` owns the runtime execution lifecycle. Required external-call pattern:

1. Open short transaction → write run setup state → commit.
2. Call runtime adapter **outside** the transaction.
3. Open short transaction → write result or failure → commit.

## Runtime Credential Resolver

`runtimes/credentials.py` is the canonical resolver.

- Resolves credentials from `ModelProvider` encrypted config, not env variables directly.
- Runtime adapters must not read `ANTHROPIC_API_KEY` from the environment.
- Raw credential values are never stored in RunStep fields, artifact content, or logs.
- `app/runs/redaction.py` redacts sensitive content before persisting.

## RunStep Replay and Failure Diagnosis

`GET /api/v1/runs/{id}/steps` returns ordered RunStep records.

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

## RunEvaluation — Deterministic Harness Evaluation

`RunEvaluation` is the canonical record for deterministic harness-level evaluation of a completed Run.

### Design principles

- **Append-only.** Each `RunEvaluationService.evaluate()` call creates a new row. Existing evaluations are never deleted or overwritten. `GET /runs/{id}/evaluation` returns the most recent row.
- **Classifier-version auditable.** `evaluator_version` (e.g. `harness_eval.v1`) is stored per row, so classification history is preserved across version upgrades.
- **Harness-boundary evidence only.** Uses Run.status/error_json/output_json/exit_code, ordered RunSteps, ContextSnapshot metadata, Artifacts, Proposals, ValidationRecipe, and linked Task/TaskRun. No LLM-as-judge. No parsing of vendor CLI internal tool calls.
- **Evidence-only for CLI runtimes.** CLI adapters are black-box at the harness. No internal tool-call trajectory is reconstructed from stdout/stderr.

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

### What evaluation does NOT do

- Does not write MemoryEntry, Policy, Proposal, Capability, WorkspaceProfile, or ValidationRecipe.
- Does not create TaskEvaluation or RunReflection (those are downstream bridge layers).
- Does not mutate Run, Artifact, or Proposal rows.
- Does not auto-apply any Proposal.

### Future work

- Richer trajectory evidence events per step.
- Task-level evaluation bridge (TaskEvaluation).
- Run reflection bridge (RunReflection).
- LLM-as-judge layer, only after deterministic layer is stable.
- Run Viewer UI.

## What Is Intentionally Not Modeled Yet

- Full tool-call ontology (individual tool invocation records per step).
- Token-level traces.
- Sub-agent orchestration schema.
- Cost accounting per run or step.
- Vendor-specific trace schema.
