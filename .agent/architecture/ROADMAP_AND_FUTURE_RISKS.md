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

**Current state:** `PolicyEngine` loads active persisted Policy rows. One slice active: `memory.write_direct` with `deny` effect. Most enforcement points still use local route/service checks.

**Why it matters:** Scattered policy means bypasses are hard to detect as capabilities grow. Future automation and agent work need centralized auditable enforcement.

**Likely next steps:** Inventory remaining enforcement points. Add one additional persisted policy class (candidate: `runtime.execute`). Prove wiring with tests.

**What must be true first:** Current `memory.write_direct` enforcement is fully tested and stable.

**Risks if built too early:** Full RBAC/ABAC before the audit trail is solid creates false enforcement confidence.

**Not now:** Full enterprise RBAC/ABAC, user-facing policy editor, global route rewrite, connector/automation policy, credential access grants.

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

**Current state:** The data model is sufficient for the MVP control-plane loop. Core model supports:

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

**Design principle:** External runtime output is evidence, not truth. Long-term changes (memory, WorkspaceProfile, Capability, Policy) must go through proposals and require human approval. `ReflectionProposalBuilder` creates learning proposal candidates from `RunReflection` results. Apply handlers for these proposal types are not yet wired — accepting them raises `UnsupportedProposalTypeError`.

**Current target loop:**
```
User request
→ WorkspaceProfile
→ ContextSnapshot / rendered context
→ ExecutionPlane + RuntimeAdapter
→ Run
→ Artifact / ExternalRunRecord
→ ValidationRecipe
→ RunReflection
→ Proposal
→ approved Memory / WorkspaceProfile / Capability / Policy update
```

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
- Full native coding agent loop is not a current priority.
- Cloud Codex / Claude managed integrations are not current priority.
- Plugin marketplace is not current priority.

**Risk watch:**
- Proposal apply handlers are not wired yet; the learning loop does not close.
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
| Broader policy enforcement | Most enforcement points use local checks, not centralized PolicyEngine | One class wired; full inventory documented |
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
