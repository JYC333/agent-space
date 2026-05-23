# Roadmap and Future Risks

This document describes current capability lines and known future risks. It is organized by development domain, not by historical phase.

---

## Capability Lines

### 1. Dogfooding Stabilization

**Current state:** Two-person local instance is operational. Space isolation, actor identity, RunStep replay, runtime/credential boundaries, policy enforcement, activity provenance, backup/restore, and deployment control are all active and tested.

**Why it matters:** Dogfooding is the primary feedback loop for finding product gaps and operational risks before any broader use.

**Likely next steps:** Incident collection from real use, gap analysis from observed behavior, contract test expansion, periodic backup/restore rehearsal.

**What must be true first:** n/a — this is the current baseline.

**Not now:** Expanding to more users, remote hosting, public launch.

---

### 2. Database / Postgres Readiness

**Current state:** SQLite with `UnitOfWork`, savepoint isolation, and Postgres-compatible patterns in new code. `RunStep.step_index` uses `MAX()+1` for local SQLite — a documented distributed-writer risk. No SQLite-only SQL in new infrastructure.

**Why it matters:** Moving to Postgres is a significant migration. Patterns introduced now directly determine migration cost.

**Likely next steps:** Audit all implicit SQLite behaviors in existing code; ensure all new timestamps are UTC; review FK constraints.

**What must be true first:** Full audit of existing implicit SQLite behaviors before writing migration scripts.

**Risks if built too early:** Distributed locking and conflict resolution are not yet designed; multi-writer race conditions would require additional schema changes.

**Not now:** Postgres migration itself, distributed multi-host locking, distributed sequence for RunStep ordering.

---

### 3. Backup / Restore / Offsite Safety

**Current state:** `BackupService` is primary (WAL-safe, manifest, local lock). `scripts/backup.sh` is fallback (no manifest). `scripts/restore.sh` is manual restore. Single-host advisory lock. 7-archive retention.

**Why it matters:** Dogfood data has no recovery path without reliable backups and a tested restore procedure.

**Likely next steps:** Offsite backup strategy (manual GPG + external storage as a start). Scheduled restore rehearsal.

**Risks:** No cloud/offsite replication. Single-host advisory lock does not extend to multi-process. Shell script fallback lacks `backup_manifest.json`.

**Not now:** Automatic cloud sync, multi-device conflict resolution, automatic restore.

---

### 4. Runtime / Adapter Expansion

**Current state:** `app.runtimes` is canonical. Registered adapters: `echo` (test), `capability`, `claude_code`, `codex_cli`. Direct Anthropic API adapters (`anthropic_messages`) are intentionally not registered — Claude execution goes through the `claude_code` CLI integration only. `app.agents` contains Agent/AgentVersion CRUD and built-in seeder; new runtime adapters must go in `app.runtimes`.

`RunEvent` evidence spine is fully implemented. `RunExecutionService` emits structured event types covering the full execution lifecycle: context_compiled, runtime_selected, sandbox_created, adapter_invoked, adapter_completed, artifact_ingested (produced paths, output_json artifacts, runtime_output text), patch_collected, validation_started/completed, proposal_created (worktree code_patch and output_json proposals), evaluation_created. `RunEvaluationService` consumes RunEvent as the sole structured evidence source — `output_json.materialization_errors` is a debug field and is never parsed as classifier evidence. `GET /api/v1/runs/{id}/events` returns paginated RunEvent records with DB-level event_type/status filtering.

**Supported mutating CLI path:** `risk_level=high` → `required_sandbox_level=worktree`. This is the only supported path for file-writing CLI adapters (`claude_code`, `codex_cli`). All changes are collected as a `code_patch` Proposal and require human review before being applied to the real workspace.

**Not supported yet (intentionally):** `risk_level=critical` → `one_shot_docker`. The Docker sandbox execution path is not implemented. Runs with `critical` risk fail early with error code `critical_runtime_requires_unimplemented_one_shot_docker`. Do not attempt to use critical risk level until Docker sandbox infrastructure is designed.

**Automation-origin credential requirement:** Runs with `trigger_origin=automation` must use an explicit credential profile (CredentialBroker profile configured). Container-default fallback is not allowed for unattended execution — it could silently pick up stale or shared auth state. Manual runs may still use the container-default fallback for local dogfooding. Failure code: `runtime_credential_profile_required`.

**Preflight:** `POST /api/v1/runs/preflight` validates all execution preconditions (agent, adapter, risk level, workspace, git repo, credential profile) without creating or starting a run. Use this before creating Automation entries.

**Incomplete patch visibility:** When a CLI run produces file changes that cannot be collected (deleted, renamed, binary, oversized, not-UTF-8 files), the resulting code_patch Proposal is marked `incomplete_patch=true` in `payload_json`. Reviewers must be aware the proposal does not represent the full set of agent changes.

**Process cancellation:** `PATCH /runs/{id}/stop` sends SIGTERM to any registered CLI subprocess (same OS process only). Cross-process termination is not supported. Stale runs in `running` status are recovered at worker startup via `RunService.recover_stale_runs()`.

**Why it matters:** Supporting more runtimes expands useful agent work without compromising the control plane.

**Likely next steps:** Docker sandbox infrastructure design for critical/one_shot_docker. External webhook/cron trigger integration with preflight gate.

**What must be true first:** Credential resolver, sandbox policy, RunStep, and preflight are stable and tested for existing adapters.

**Risks if built too early:** New adapters may duplicate policy, sandbox, and credential behavior, or bypass the credential resolver.

**Not now:** Broad CLI adapter deletion, Docker sandbox pool, production container infrastructure, cross-process subprocess termination.

---

### 5. Policy Enforcement Expansion

**Current state:**

- **`PolicyEngine.check()`** is fail-closed: unknown actions return `decision=deny` with
  `audit_code="unknown_policy_action"`. Only registered actions can fall through to allow.
  `BUILTIN_RULES` evaluated in order: space_boundary, agent_status, memory_scope,
  use_credential, tool_permission, workspace_write_patch, policy_change.
- `agent.delegate` is **not** a current action — agent-to-agent delegation is deferred.
- Domain-specific persisted-policy enforcement in `policy/enforcement.py`
  (`memory.private_placement`, `run.user_private_scope`).
- **Canonical action registry** (`policy/actions.py`): **12 wired sensitive actions** are
  code-defined. `require_action_definition()` raises `UnknownPolicyActionError` for unregistered
  actions. **Reserved actions** (15, `lifecycle_status=RESERVED`, including automation.create/fire,
  capability.enable, tool_binding.enable, artifact.export, context.use_personal_grant, workspace.read)
  are registered with `current_enforcement_point="not_implemented"`. `PolicyGateway` always denies
  reserved actions; they are not wired to any `PolicyGateway.check_and_record()` call site yet.
- **Approval resolver** (`policy/approval.py`): `can_approve_policy_action()` calls
  `require_action_definition(action)` first, then checks SpaceMembership role against effective risk.
  - owner → can approve all supported actions including critical
  - admin → can approve low/medium/high; not critical
  - member/guest/viewer → cannot approve by default
- **`proposal.apply` gate** — consolidated in `PolicyGateway.check_proposal_apply()`. Called from
  `ProposalService.accept()`. Runs HardInvariantGuard first (payload flag check), then
  role/risk matrix, then persists PolicyDecisionRecord. Always recorded (audit_required=True).
  Effective risk = `max(type_default, proposal.risk_level)`.
  Denial → HTTP 403; no durable write occurs.
- **`runtime.execute` gate** — checked before credential resolution. DENY/REQUIRE_APPROVAL
  blocks adapter with `error_code=policy_denied_runtime_execute`.
- **`runtime.use_credential` gate** — checked before secret fetch. Same-space manual/api → ALLOW.
  Cross-space → hard DENY (CRITICAL). Automation → REQUIRE_APPROVAL.
- **`context.inject_memory` gate** — in ContextSnapshotPopulator before ContextBuilder.build().
  Cross-space without grant → hard DENY. DENY raises RuntimeError blocking context population.
- **`context.render_for_runtime` gate** — in execution.py before adapter.execute(). Cross-space
  without grant → hard DENY. DENY → `error_code=policy_denied_context_render_for_runtime`.
- **`artifact.persist` gate** — in ArtifactPersistenceService before filesystem write and egress
  guard. personal_context_block in metadata → hard DENY. Always recorded (audit_required=True).
- **`proposal.create` gate** — in ProposalService and CodePatchCollector before Proposal insert.
  force_record=True for high-risk types. DENY blocks proposal creation.
- **PolicyDecisionRecord** — all sensitive decisions persisted. Metadata sanitized before storage:
  no credentials, prompts, patch bodies, stdout/stderr, raw memory, personal_context_block.
- **ProposalApplyService defense-in-depth** — `apply()` requires `accept_context` in
  `{"explicit_user_accept", "internal_seed"}`. Unrecognized context rejects without
  `bypass_source_monitoring=True`.
- **Reviewable proposal inbox** is role-aware.
- Memory write boundary is structural (`_INTERNAL_WRITE_AUTHORITY` sentinel).

**Design invariants:**
- Policy is a risk-routing layer, not enterprise RBAC/ABAC.
- PolicyGateway is the only enforcement entry point. Never call PolicyEngine or
  HardInvariantGuard directly to authorize or perform a sensitive action.
  `PreflightService` may call PolicyEngine only for non-mutating dry-run simulation;
  it must not persist `PolicyDecisionRecord`, and real execution still uses PolicyGateway.
- No enforcement point has legacy fallback paths or backward-compatibility wrappers.
- No secret material is resolved before `runtime.use_credential` passes.
- No context is injected before `context.inject_memory` passes.
- No adapter is invoked before `runtime.execute` and `context.render_for_runtime` pass.
- "Reviewer" is not a SpaceMembership role — it is a future approval capability.
- "Forbidden" is `decision=deny`, not a risk level. Risk levels: low, medium, high, critical.
- Unknown sensitive actions must not silently fall through as allow.
- Proposal acceptance is the human approval event; the proposal.apply gate enforces this.
- `agent.delegate` is not a current canonical action. Future multi-agent child-run creation
  should be designed as `run.spawn_child` / `run.create_child` with explicit control-plane
  policy and evaluation gates.

**Why it matters:** Scattered policy means bypasses are hard to detect as capabilities grow. PolicyGateway provides a single auditable boundary for all sensitive actions.

**Remaining gaps:**
1. `memory.create/update/archive` enforcement points at MemoryStore level (currently only
   at proposal.apply gate).
2. `workspace.read` enforcement point when workspace access control is built.
3. `automation.create`, `automation.fire` — when Automation model is built.
4. `capability.enable`, `tool_binding.enable` — when capability management API is built.
5. Per-user approval capabilities table (extension point exists; table not built).

**Not now:** Full enterprise RBAC/ABAC, user-facing policy editor, global route rewrite, policy DSL, lab/scientific identity roles, agent-to-agent delegation (deferred).

---

### 6. Memory / Provenance / Source-Evidence Maturation

**Current state:** `ActivityRecord`, `ProvenanceLink`, `Proposal.payload_json` provenance entries, and `MemoryEntry.source_*` fields form the current provenance chain. `context_sources` is not in the canonical schema. No first-class `Source` or `Evidence` table exists yet.

**Why it matters:** Trustworthy memory depends on a complete provenance chain. Future external ingestion depends on knowing where data came from and whether it was reviewed.

**Likely next steps:** Define minimal `Source`/`Evidence` objects when the current field mapping becomes insufficient. Add trust vocabulary tests for all capture paths.

**What must be true first:** ActivityRecord-based provenance is tested for all current capture paths. Trust resolution for all current `activity_type` values is correct.

**Risks if built too early:** First-class Source/Evidence schema without lifecycle definitions creates premature ingestion risk.

**Not now:** Broad Source/Evidence ontology, vector retrieval over external corpus.

---

### 7. Information Horizon

**Current state:** No `InformationItem`, `DiscoveryQueue`, or `ReadingState` table. Candidate-only rule is enforced by the absence of implementation.

**Why it matters:** Reachable-but-unread information management is a core product differentiator. Done wrong, it pollutes trusted memory.

**Likely next steps:** Keep documentation-only. Define `SourceProfile` / `InformationItem` minimal schema when Activity/Source/Evidence foundation is stable.

**What must be true first:** ActivityRecord-first capture, Source/Evidence trust vocabulary, and proposal-gated memory are all stable and tested.

**Risks if built too early:** External source ingestion without trust gates will pollute trusted Memory with unreviewed content. Attention overload without bounded discovery queue.

**Not now:** Crawler, RSS/external feed ingestion, broad metadata indexing, embeddings, auto-promotion of horizon content.

---

### 8. Automation / Triggers

**Current state:** Jobs exist and `Run.trigger_origin` reserves `automation`. No `Automation` or `Trigger` model. Runtime foundation for automation-safe execution is in place:
  - `trigger_origin="automation"` is validated in `RunService.create_run()`
  - Automation-origin CLI runs must use an explicit credential profile (no container fallback)
  - `POST /api/v1/runs/preflight` must pass before any Automation entry can be created
  - `incomplete_patch` is surfaced on proposals so partial changes are never silently accepted

**Why it matters:** Background work needs explicit ownership, policy, and audit. Hidden background mutations are dangerous.

**Likely next steps:** Define `Automation` model (owner, trigger type, schedule, preflight snapshot, max_runs_per_day). Wire preflight as a creation gate. All automation runs must produce proposals (no direct memory writes).

**What must be true first:** Preflight endpoint, automation-safe credential check, and RunStep audit are all stable. Runtime foundation hardening is complete.

**Risks if built too early:** Hidden background memory or policy writes. Runaway cost. No ownership or review path. Credential fallback allowing automation to silently use wrong credentials.

**Not now:** Cron scheduler, external source refresh triggers, broad event-driven automation. Docker sandbox for critical-risk automation runs.

---

### 9. Connectors / Integrations

**Current state:** No Connector/Integration model. Provider and CLI credentials are special-case modules.

**Why it matters:** External chat, calendar, docs, publishing, and import/export will become separate incompatible subsystems without a common boundary.

**Likely next steps:** Draft connector/integration schema only after Source/Evidence design is stable.

**What must be true first:** Source/Evidence design is stable. Activity-first ingestion path is tested.

**Risks if built too early:** External data may bypass provenance and enter trusted Memory directly. Privacy and trust lifecycle are undefined for connector-sourced data.

**Not now:** One-off integration tables for each external source. External chat capture before trust gate exists.

---

### 10. Self-Evolution

**Current state:** System-core workspace registration and host deployer exist. Self-evolution is disabled by default. Deployment job persistence is absent (501-gated). No capability lifecycle persistence.

**Why it matters:** Self-evolution is high-risk. It must not bypass human governance or gain host authority.

**Likely next steps:** Keep disabled. Document allowed evolution surfaces (prompts, playbooks, context policies, capability manifests) with required evaluation gate definitions.

**What must be true first:** Proposal review, evaluation signals, deployment job persistence, capability lifecycle persistence, and rollback path are all implemented and tested.

**Risks if built too early:** Agents may expand their own scope, modify production code without approval, or gain deployment authority.

**Not now:** Direct self-modifying agents, app-container deployment control, automatic scope expansion.

---

### 11. Frontend Command Center

**Current state:** `HomeGalleryPage` consumes `/home/summary`. Space switcher, proposals, settings active. Planned modules show "soon" badge. Some frontend/backend type drift exists for memory proposals, workspace fields, and space type.

**Why it matters:** Users need a daily operating surface that shows attention items, review queue, runtime status, and recent work without exposing internal domain logic.

**Likely next steps:** Review inbox aggregate API and UI. Continue-working surfaces from runs/tasks/proposals/artifacts. Frontend/backend type contract alignment.

**What must be true first:** Stable backend aggregate APIs and resolved API type contracts.

**Not now:** Native mobile app, advanced offline queue, frontend-only business rule inference.

---

### 12. Privacy / Retention / Export

**Current state:** Memory visibility/sensitivity exists. Artifact export exists. No bulk memory export, no retention policy, and no hard-delete semantics defined.

**Why it matters:** Personal OS data needs trust, portability, and correct deletion semantics.

**Likely next steps:** Define bulk memory export format. Add deletion audit semantics for memory and artifacts. Document export format (Markdown/JSON).

**What must be true first:** Activity, memory, and artifact lifecycle states are stable. Provenance links survive export.

**Not now:** Full cross-device sync, automated retention enforcement, global hard-delete automation without operator review.

---

### 13. Control Plane and Learning Loop

**Current state:** The data model supports the current control-plane loop. Core model supports:

- `ExecutionPlane` — registered execution environments and their capability envelope
- `ModelProvider` — provider credential and config binding
- `RuntimeAdapter` — adapter registration per plane
- Run execution metadata snapshots — per-run plane/adapter/model resolution record
- `WorkspaceProfile` — per-workspace runtime preferences and context hints
- `ValidationRecipe` — evaluation criteria and success signals for a workspace/task type
- `ExternalRunRecord` — ingested output from externally-managed runs
- `RunReflection` — structured analysis of a run's outcome against validation criteria
- `RuntimeToolBinding` — declared tool bindings per adapter/plane
- `ContextSnapshot` runtime-facing metadata — rendered context state at run time
- Artifact runtime/execution-plane provenance — artifacts carry producing plane and adapter

**Design principle:** External runtime output is evidence, not truth. Long-term changes (memory, WorkspaceProfile, Capability, Policy) must go through proposals and require human approval. `ReflectionProposalBuilder` creates learning proposal candidates from `RunReflection` results.

**Current target loop:**
```
User request
→ WorkspaceProfile + ValidationRecipe
→ ContextSnapshot / rendered context
→ ExecutionPlane + RuntimeAdapter
→ Run
→ RunEvent (structured append-only harness evidence spine)
→ Artifact / ExternalRunRecord
→ RunEvaluation (deterministic harness layer, RunEvent as primary evidence)
→ TaskEvaluation (append-only task bridge)
→ RunReflection  (learning candidate source)
→ Proposal (pending, requires human review)
→ approved Task / Memory / WorkspaceProfile / Capability / Policy update
```

**Learning apply status:**
- `follow_up_task` — **implemented**. Accepted proposals create a `Task` row through `ProposalApplyService`. This is the first closed apply path in the learning loop.
- `memory_update` (from reflection) — proposals created; apply uses the standard `memory_update` handler (target_memory_id required).
- `workspace_profile_update`, `validation_recipe_update`, `capability_update`, `policy_update` — proposals created by `ReflectionProposalBuilder`; accepting them raises `UnsupportedProposalTypeError`. Apply handlers are deferred.

`RunReflection` is not automatically created by `RunEvaluationService` or `TaskEvaluationService`. Automation is not implemented.

**PostRunFinalizationService — canonical post-run boundary (implemented):**

`PostRunFinalizationService` is the single write surface for post-run evaluation. Automation should call `POST /runs/{id}/finalize` after a run reaches a terminal state.

- Creates exactly one `RunEvaluation` per finalization (internal: `RunEvaluationService`).
- If a `TaskRun` link exists, creates one `TaskEvaluation` bridge row (internal: `TaskEvaluationService`).
- Creates one `RunFinalization` record; idempotent per `(run_id, finalizer_version)`.
- Appends one `run_finalized` RunEvent.
- Never writes Memory, Policy, Proposal, WorkspaceProfile, ValidationRecipe, Capability, or RunReflection.
- Never auto-applies anything.

**RunEvaluation — deterministic internal evaluation primitive (implemented):**

`RunEvaluation` is the append-only harness-level evaluation record created by `RunEvaluationService`. It is an internal primitive called by `PostRunFinalizationService`. Key properties:
- Each `evaluate()` call appends a new row. Existing rows are never deleted.
- Uses harness-visible evidence only: Run metadata, RunSteps, ContextSnapshot, Artifacts, Proposals.
- `evaluator_version` is stored per row for classifier-version auditability.
- CLI runtimes are black-box; no internal tool-call trajectory is reconstructed.
- `adapter_started` terminal status counts as adapter completion from the harness perspective.
- Evaluation never writes Memory, Policy, Proposal, WorkspaceProfile, ValidationRecipe, or Capability.

**Downstream bridge layers:**
- `TaskEvaluation` — append-only task-level evaluation derived from `RunEvaluation` through `TaskEvaluationService`. Invoked by `PostRunFinalizationService` when `TaskRun` linkage exists.
- `RunReflection` — learning candidate source; populated externally (import, manual entry, or evaluator output). Not automatically created from evaluation or finalization.
- Run Viewer UI — surface for browsing finalization and evaluation history per run.

**Next work:**
1. Run a manual-managed dogfood flow using a real workspace.
2. Generate a runtime task spec from WorkspaceProfile + ContextSnapshot.
3. Execute through local Codex / Claude Code / OpenCode manually or semi-manually.
4. Import diff/log/summary as ExternalRunRecord and Artifacts.
5. Generate RunReflection and proposal candidates.
6. Evaluate whether proposal payloads are reviewable and useful.
7. Only after 2–3 successful dogfood runs, automate the most stable parts.

**Deferred intentionally:**
- `RunStep` / `SubRun` until deeper trace or delegation is needed.
- `RunRoutingPolicy` until routing rules outgrow service-level logic.
- Separate `ContextBundle` table until one snapshot needs multiple rendered runtime bundles.
- `ExternalCapability` / `CapabilityExport` until vendor plugin/skill export becomes real.
- `Automation` / `Trigger` until managed run flow is stable.
- Apply handlers for `workspace_profile_update`, `validation_recipe_update`, `capability_update`, `policy_update` — deferred until dogfood validates payload shape.
- Full native coding agent loop is not a current priority.
- Cloud Codex / Claude managed integrations are not current priority.
- Plugin marketplace is not current priority.

**Risk watch:**
- `workspace_profile_update`, `validation_recipe_update`, `capability_update`, `policy_update` apply handlers are not wired; those paths in the learning loop remain open.
- Runtime-facing context quality is unvalidated in real tasks.
- RunReflection quality is unvalidated in real tasks.
- WorkspaceProfile and ValidationRecipe usefulness must be validated through dogfooding.
- API writes that affect `cloud_allowed`, preferred runtime, policy, or capability must remain proposal-gated or tightly permissioned.

---

## Known Future Risks

| Risk | Why it matters | Current status |
|---|---|---|
| Postgres migration | Current SQLite-only patterns will require rewrite; migration of existing data is non-trivial | Postgres-compatible patterns enforced in new code; migration not yet planned |
| Distributed multi-process locking | Current advisory lock is single-host only | Documented risk; single-process for now |
| Cloud/offsite backup | No automated offsite replication | Manual GPG + offsite transfer documented; not automated |
| Full retention policy | Personal data retention and legal obligations | Lifecycle states defined; retention policy engine deferred |
| Broader policy enforcement | Some enforcement points (memory.create at MemoryStore, workspace.read) still use local checks, not PolicyGateway | 8 enforcement points wired via PolicyGateway; memory/workspace remaining |
| Credential access grants | No per-run/per-tool credential scope; credential resolver is a single boundary | Resolver boundary set; grants deferred |
| Source/Evidence first-class schema | Current field mapping insufficient for broad external ingestion | Deferred behind ingestion gate |
| Information Horizon ingestion safety | External data can pollute trusted Memory without trust gates | Candidate-only rule enforced by absence of implementation |
| Automation scope creep | Background work without ownership/policy can silently mutate data | No Automation model; invariants documented |
| Self-evolution scope creep | Agents expanding their own permissions or target domain | Disabled by default; deployer-only gate |
| Code patch operational risk | Partial apply with rollback failure leaves filesystem inconsistent | Explicit compensation logic; partial-apply errors surfaced |
| Frontend exposing disabled surfaces | Planned-but-not-built modules appearing interactive | Registry `planned: true` pattern; "soon" badges enforced |
| External connector privacy risk | External data ingested without lifecycle/trust bounds | No connector model; Source/Evidence design required first |
| Actor identity migration cost | Many historical nullable user/agent fields across core tables | New surfaces use `actor_ref`; fields not migrated in bulk; actor_ref used for new records |
| Workspace console sessions / API keys | Feature-gated; operators cannot manage them through UI | 501-gated; manual operator action required |
