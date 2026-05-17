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

**Current state:** `app.runtimes` is canonical. `echo` and `anthropic_messages` adapters are active. `app.agents` CLI stack is compatibility-only for existing CLI surfaces.

**Why it matters:** Supporting more runtimes expands useful agent work without compromising the control plane.

**Likely next steps:** Document compatibility status of `app.agents` CLI adapters. Define adapter contract for new additions. Clarify `one_shot_docker` path in current run execution.

**What must be true first:** Credential resolver, sandbox policy, and RunStep are stable and tested for existing adapters.

**Risks if built too early:** New adapters may duplicate policy, sandbox, and credential behavior, or bypass the credential resolver.

**Not now:** Broad CLI adapter deletion, Docker sandbox pool, production container infrastructure.

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

**Current state:** `ActivityRecord`, `ProvenanceLink`, `Proposal.payload_json` provenance entries, and `MemoryEntry.source_*` fields form the current provenance chain. The old `context_sources` table was removed from the schema. No first-class `Source` or `Evidence` table exists yet.

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

**Current state:** Jobs exist and `Run.trigger_origin` reserves `automation`. No `Automation` or `Trigger` model.

**Why it matters:** Background work needs explicit ownership, policy, and audit. Hidden background mutations are dangerous.

**Likely next steps:** Define automation invariants in documentation before any implementation. All automation must be proposal-producing or derived-cache-only until a model exists.

**What must be true first:** Policy engine, proposal review, and RunStep audit are stable. Actor identity is available on all new events.

**Risks if built too early:** Hidden background memory or policy writes. Runaway cost. No ownership or review path.

**Not now:** Cron scheduler, external source refresh triggers, broad event-driven automation.

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
| Actor identity migration cost | Many historical nullable user/agent fields across core tables | New surfaces use `actor_ref`; historical fields readable during compatibility |
| Workspace console sessions / API keys | Feature-gated; operators cannot manage them through UI | 501-gated; manual operator action required |
