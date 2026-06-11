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

### 2. Database / PostgreSQL

**Current state:** PostgreSQL is the server database. `UnitOfWork`, savepoint isolation, and explicit transaction boundaries are all in place. `RunStep.step_index` uses `MAX()+1` — a documented distributed-writer risk under concurrent writers.

**Why it matters:** All new schema and query work must stay PostgreSQL-idiomatic.

**Likely next steps:** Stronger `RunStep` ordering under distributed writers (DB sequence or distributed counter). Distributed multi-host locking (advisory lock is currently single-host).

**Not now:** Distributed multi-host locking, distributed sequence for RunStep ordering.

---

### 3. Backup / Restore / Offsite Safety

**Current state:** `BackupService` is the canonical full-system backup (pg_dump custom-format snapshot + files + manifest, local lock; live `db/postgres` never archived). `ops/scripts/system/backup.sh` and `ops/scripts/system/restore.sh` are the offline full-system equivalents (same archive format; restore rebuilds database and files in one command). `ops/scripts/db/dump.sh` / `ops/scripts/db/restore.sh` are DB-only pg_dump/pg_restore operator tools. Single-host advisory lock. 7-archive retention.

**Why it matters:** Dogfood data has no recovery path without reliable backups and a tested restore procedure.

**Likely next steps:** Offsite backup strategy (manual GPG + external storage as a start). Scheduled restore rehearsal.

**Risks:** No cloud/offsite replication. Single-host advisory lock does not extend to multi-process.

**Not now:** Automatic cloud sync, multi-device conflict resolution, automatic restore.

---

### 4. Runtime / Adapter Expansion

**Current state:** `app.runtimes` is canonical. Registered adapters: `echo` (test), `capability`, `claude_code`, `codex_cli`. Claude execution goes through the `claude_code` RuntimeAdapterSpec. `app.agents` contains Agent/AgentVersion CRUD and built-in seeder; new local CLI runtimes should start as RuntimeAdapterSpec entries.

`RunEvent` evidence spine is fully implemented. `RunExecutionService` emits structured event types covering the full execution lifecycle: context_compiled, runtime_selected, sandbox_created, adapter_invoked, adapter_completed, artifact_ingested (produced paths, output_json artifacts, runtime_output text), patch_collected, validation_started/completed, proposal_created (worktree code_patch and output_json proposals), evaluation_created. `RunEvaluationService` consumes RunEvent as the sole structured evidence source — `output_json.materialization_errors` is a debug field and is never parsed as classifier evidence. `GET /api/v1/runs/{id}/events` returns paginated RunEvent records with DB-level event_type/status filtering.

**Supported mutating CLI path:** `risk_level=high` → `required_sandbox_level=worktree`. This is the only supported path for file-writing local CLI runtimes (`claude_code`, `codex_cli`). All changes are collected as a `code_patch` Proposal and require human review before being applied to the real workspace.

**Not supported yet (intentionally):** `risk_level=critical` → `one_shot_docker`. The Docker sandbox execution path is not implemented. Runs with `critical` risk fail early with error code `critical_runtime_requires_unimplemented_one_shot_docker`. Do not attempt to use critical risk level until Docker sandbox infrastructure is designed.

**CLI credential requirement:** Manual and automation CLI runs must use an explicit
CredentialBroker profile. Container-default fallback is not allowed because it can
silently pick up stale or shared auth state. Failure code:
`runtime_credential_profile_required`.

**Preflight:** `POST /api/v1/runs/preflight` validates all execution preconditions (agent, adapter, risk level, workspace, git repo, credential profile) without creating or starting a run. Use this before creating Automation entries.

**Incomplete patch visibility:** When a CLI run produces file changes that cannot be collected (deleted, renamed, binary, oversized, not-UTF-8 files), the resulting code_patch Proposal is marked `incomplete_patch=true` in `payload_json`. Reviewers must be aware the proposal does not represent the full set of agent changes.

**Process cancellation:** `PATCH /runs/{id}/stop` sends SIGTERM to any registered CLI subprocess (same OS process only). Cross-process termination is not supported. Stale runs in `running` status are recovered at worker startup via `RunService.recover_stale_runs()`.

**Why it matters:** Supporting more runtimes expands useful agent work without compromising the control plane.

**Likely next steps:** Docker sandbox infrastructure design for critical/one_shot_docker. External webhook/cron trigger integration with preflight gate.

**What must be true first:** Credential resolver, sandbox policy, RunStep, and preflight are stable and tested for existing adapters.

**Risks if built too early:** New adapters may duplicate policy, sandbox, and credential behavior, or bypass the credential resolver.

**Not now:** Docker sandbox pool, production container infrastructure, cross-process subprocess termination.

---

### 5. Policy Enforcement Expansion

**Current state:**

- **`PolicyEngine.check()`** is fail-closed: unknown actions return `decision=deny` with
  `audit_code="unknown_policy_action"`. Only registered actions can fall through to allow.
  `BUILTIN_RULES` evaluated in order: space_boundary, agent_status, memory_scope,
  use_credential, tool_permission, workspace_write_patch, policy_change, automation,
  runtime_execute_risk_level.
- `agent.delegate` is **not** a current action — agent-to-agent delegation is deferred.
- Domain-specific persisted-policy enforcement in `policy/enforcement.py`
  (`memory.private_placement`, `run.user_private_scope`).
- **PolicyEffectCatalog** (`policy/effects.py`) is a lightweight effect contract,
  not a full DSL. `policy_change` proposals may create active `Policy` rows only
  for supported domains with real enforcement points. Reserved domains
  (`runtime.execute`, `automation.fire`, `capability.enable`,
  `tool_binding.enable`, `deployment.execute`) are vocabulary only and fail
  closed until wired.
- **Canonical action registry** (`policy/actions.py`): **21 WIRED_DIRECT + 9 WIRED_VIA_PROPOSAL
  sensitive actions** are code-defined. `require_action_definition()` raises
  `UnknownPolicyActionError` for unregistered actions. **Reserved actions** (12,
  `lifecycle_status=RESERVED`, including capability.enable, tool_binding.enable, artifact.export,
  context.use_personal_grant, deployment.propose, deployment.execute) are registered
  with `current_enforcement_point="not_implemented"`. `PolicyGateway` always denies reserved actions.
  `workspace.read`, `agent.config_update`, `automation.create`, `automation.update`,
  `automation.fire`, Intake/Evidence actions, and `context.select_evidence` are WIRED_DIRECT.
- **Approval resolver** (`policy/approval.py`): `can_approve_policy_action()` calls
  `require_action_definition(action)` first, then checks SpaceMembership role against effective risk.
  - owner → can approve all supported actions including critical
  - admin → can approve low/medium/high; not critical
  - reviewer → can approve low/medium; not high/critical
  - member/guest → cannot approve by default
- **`proposal.apply` gate** — consolidated in `PolicyGateway.enforce_proposal_apply()`. Called from
  `ProposalService.accept()`. Runs HardInvariantGuard first (payload flag check), then
  role/risk matrix, then persists PolicyDecisionRecord. Always recorded (audit_required=True).
  Effective risk = `max(type_default, proposal.risk_level)`.
  Denial → raises `PolicyGateBlocked` → global exception handler writes durable audit record → HTTP 403.
- **Preferred audit model** — `PolicyGateway.enforce()` and `enforce_proposal_apply()` write
  ALLOW records through `DurablePolicyAuditWriter`, which writes only
  `PolicyDecisionRecord` in an independent transaction. The HTTP
  `PolicyGateBlocked` handler rolls back the request transaction and writes a
  blocking record independently; runtime-local blocked paths call
  `write_blocked_gate_audit()` once and fail the run. No business object is
  committed merely to persist audit evidence.
- **`runtime.execute` gate** — uses `enforce()` before credential resolution. DENY/REQUIRE_APPROVAL
  blocks adapter with `error_code=policy_denied_runtime_execute`.
- **`runtime.use_credential` gate** — uses `enforce()` before secret fetch. Same-space manual/api → ALLOW.
  Cross-space → hard DENY (CRITICAL). Automation → REQUIRE_APPROVAL.
- **Runtime/automation policy input parity** — `RunExecutionService` and
  `AutomationPolicyPreflightService` share `app.runs.policy_inputs` for
  `runtime.execute` request construction and credential policy metadata
  construction. Preflight remains simulation-only: no `PolicyGateway`, no
  `PolicyDecisionRecord`, no business-row mutation.
- **`context.inject_memory` gate** — uses `enforce()` in ContextSnapshotPopulator before ContextBuilder.build().
  Cross-space without grant → hard DENY. DENY raises RuntimeError blocking context population.
- **`context.render_for_runtime` gate** — in execution.py before adapter.execute(). Cross-space
  without grant → hard DENY. DENY → `error_code=policy_denied_context_render_for_runtime`.
- **`artifact.persist` gate** — uses `enforce()` in ArtifactPersistenceService before egress
  guard or persistence. Blocked decisions write one durable audit record; audit
  failure writes no artifact. Always recorded and fail closed.
- **`proposal.create` gate** — uses `enforce()` in ProposalService and CodePatchCollector
  before Proposal insert. CodePatchCollector passes `force_record=True`.
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
- No secret material is resolved before `runtime.use_credential` passes.
- No context is injected before `context.inject_memory` passes.
- No adapter is invoked before `runtime.execute` and `context.render_for_runtime` pass.
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
2. `capability.enable`, `tool_binding.enable` — when capability management API is built.
3. Schedule automation credential pre-authorization exists through
   `AutomationCredentialGrant`; broader per-run/per-tool credential scoping and
   user-facing allowance management remain deferred.

**Not now:** Full enterprise RBAC/ABAC, user-facing policy editor, global route rewrite, policy DSL, lab/scientific identity roles, agent-to-agent delegation (deferred).

---

### 6. Memory / Provenance / Source-Evidence Maturation

**Current state:** `ActivityRecord`, `ProvenanceLink`, `Proposal.payload_json` provenance entries, and `MemoryEntry.source_*` fields form the durable accepted-object provenance chain. `context_sources` is not in the canonical schema. Intake/Evidence now has first-class candidate tables (`IntakeItem`, `SourceSnapshot`, `ExtractedEvidence`, and `EvidenceLink`), but these are not accepted Memory/Knowledge.

**Why it matters:** Trustworthy memory depends on a complete provenance chain. Future external ingestion depends on knowing where data came from and whether it was reviewed.

**Current state:** Canonical Intake/Evidence tables exist for source connectors, source connections, intake items, source snapshots, extraction jobs, extracted evidence, workspace intake profiles, and workspace source bindings. Workspace source bindings are workspace-scoped; projects consume evidence through links rather than owning raw intake.

**Likely next steps:** Extend connector-specific ingestion behind the same Intake/Evidence lifecycle. Add trust vocabulary tests for new capture paths.

**What must be true first:** ActivityRecord-based provenance is tested for all current capture paths. Trust resolution for all current `activity_type` values is correct.

**Risks if extended too broadly:** Connector-specific behavior can bypass candidate lifecycle, retention bounds, or proposal review.

**Not now:** Broad ontology, web crawling, vector retrieval over external corpus.

---

### 7. Intake and Evidence

**Current state:** Intake/Evidence is implemented as a candidate-only substrate. Evidence can be selected into context snapshots through active relevance/context `EvidenceLink` rows (`context_candidate`, `supports`, `mentions`, `provenance`), and selected evidence receives an auditable `used_in_context` link to the run. `used_in_context` is audit-only, not a selector input. Internal ActivityRecord/Artifact/RunEvent normalization is item/evidence-idempotent; repeated manual normalization may add skipped audit jobs for traceability but does not duplicate active/candidate evidence. Evidence cannot become active Memory without proposal review.

**Why it matters:** External and internal source material needs provenance, trust, retention, and explicit promotion boundaries. Done wrong, it pollutes trusted memory.

**Likely next steps:** Add connector-specific adapters and extraction workers behind `SourceConnection`, `IntakeItem`, `ExtractionJob`, and `ExtractedEvidence`. Keep the current connector family narrow unless a concrete product workflow requires expansion.

**What must be true first:** Intake/Evidence trust vocabulary, context selection, retention, and proposal-gated memory remain stable and tested.

**Risks if extended too early:** External source ingestion without trust gates will pollute trusted Memory with unreviewed content. Attention overload without bounded queues and filters. Intake artifact writes now clean up the written file if the immediate Artifact DB row creation fails after the file write; a future transaction-aware storage pass should still handle process failure or full transaction rollback after a file is promoted.

**Not now:** Area, web crawler, broad metadata indexing, embeddings, auto-promotion of intake/evidence content.

---

### 8. Automation / Triggers

**Current state:** `Automation` and `AutomationRun` models and CRUD API are implemented
(`app.automation`). `automation.create`, `automation.update`, and `automation.fire` are
`WIRED_DIRECT` actions enforced via `PolicyGateway`. Key properties:

- `Automation` carries `owner_user_id`, `agent_id`, `workspace_id`, `trigger_type` (manual only),
  `status` (active/paused/archived), `preflight_snapshot_json`.
- Automation creation requires `PreflightService` to pass with `trigger_origin="automation"`.
  Preflight snapshot is persisted on the row.
- Manual fire (`POST /spaces/{id}/automations/{id}/fire`) reruns preflight and creates a
  **queued** `Run(trigger_origin="automation")` plus an `AutomationRun` link row.
  The run is not executed automatically — the existing run worker picks it up.
- `automation.create/update/fire` require `admin` or `owner` role (enforced by `rule_automation`
  in `policy/rules.py`).
- `automation.create` and `automation.fire` use `record_failure_mode=FAIL_CLOSED` so audit
  records are mandatory.
- `AutomationService` must not directly write `MemoryEntry`, `Policy`, `Workspace` files,
  `Capability`, or `Credentials` — these invariants are tested.

**Invariants:**
  - Automation-origin credential use requires explicit approval (`rule_use_credential`).
  - Automation-origin CLI runs must use an explicit credential profile (no container fallback).
  - `incomplete_patch` is surfaced on proposals so partial changes are never silently accepted.

**Not implemented:**
  - External event trigger registry.
  - External event triggers.
  - Credential allowances for automation-origin runs.
  - Docker sandbox for critical-risk automation runs.

Automation schema is intentionally folded into canonical 0001 during foundation
hardening. No 0002 migration is expected for this branch.

**Why it matters:** Background work needs explicit ownership, policy, and audit. Hidden background mutations are dangerous.

**Risks:**
  - Credential fallback for automation-origin runs is blocked at preflight and at the
    `runtime.use_credential` gate (REQUIRE_APPROVAL for automation origin).
  - Runaway cost: no `max_runs_per_day` cap yet — deferred.
  - Cron and event triggers must not bypass the preflight + policy gate path.

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

`RunReflection` is not automatically created by `RunEvaluationService` or
`TaskEvaluationService`. Automation supports manual and schedule-triggered fire;
external triggers are not implemented.

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
- Scheduled and external Automation triggers until managed run flow is stable.
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
| Distributed multi-host DB locking | Current advisory lock is single-host; multi-host requires a real distributed lock service | Documented risk; single-process only for now |
| Distributed multi-process locking | Current advisory lock is single-host only | Documented risk; single-process for now |
| Cloud/offsite backup | No automated offsite replication | Manual GPG + offsite transfer documented; not automated |
| TestClient lifespan fixture | Some policy/proposal tests that request `cross_space_pair` can block while constructing the test client in this environment | Test environment limitation only; not a product architecture boundary |
| Full retention policy | Personal data retention and legal obligations | Lifecycle states defined; retention policy engine deferred |
| Broader policy enforcement | Some enforcement points are intentionally proposal-mediated or deferred | Memory create/update/archive are proposal-mediated; workspace.read is wired direct; capability/deployment/export actions remain deferred |
| Credential access grants | No per-run/per-tool credential scope; credential resolver is a single boundary | Resolver boundary set; grants deferred |
| Broad Intake/Evidence ingestion | External data can pollute trusted Memory without trust gates | Candidate-only lifecycle implemented; broad crawling/indexing deferred |
| Automation scope creep | Background work without ownership/policy can silently mutate data | `Automation`/`AutomationRun` models and CRUD API implemented; `automation.create/update/fire` WIRED_DIRECT via PolicyGateway.enforce() with durable audit; admin/owner role required; manual and schedule-triggered fire supported; broader credential scoping deferred |
| Self-evolution scope creep | Agents expanding their own permissions or target domain | Disabled by default; deployer-only gate |
| Code patch operational risk | Partial apply with rollback failure leaves filesystem inconsistent | Explicit compensation logic; partial-apply errors surfaced |
| Frontend exposing disabled surfaces | Planned-but-not-built modules appearing interactive | Registry `planned: true` pattern; "soon" badges enforced |
| External connector privacy risk | External data ingested without lifecycle/trust bounds | SourceConnection/IntakeItem/Evidence lifecycle exists; connector marketplace deferred |
| Actor identity migration cost | Many historical nullable user/agent fields across core tables | New surfaces use `actor_ref`; fields not migrated in bulk; actor_ref used for new records |
| Workspace console sessions / API keys | Feature-gated; operators cannot manage them through UI | 501-gated; manual operator action required |
