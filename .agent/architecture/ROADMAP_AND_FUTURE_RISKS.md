# Roadmap and Future Risks

This document is a roadmap and risk watch only. It should not duplicate current
implementation inventory. For current state, use the linked source-of-truth docs;
code and migrations still win over documentation.

---

## Source Pointers

| Area | Current-state source |
|---|---|
| Product boundaries | [PRODUCT_AND_BOUNDARIES.md](PRODUCT_AND_BOUNDARIES.md), [NON_GOALS_AND_DISABLED_SURFACES.md](NON_GOALS_AND_DISABLED_SURFACES.md) |
| Server ownership | [SERVER_FOUNDATION.md](SERVER_FOUNDATION.md), [SERVER_OWNERSHIP.md](SERVER_OWNERSHIP.md), [MODULES.md](MODULES.md) |
| Runtime, runs, artifacts | [EXECUTION_MODEL.md](EXECUTION_MODEL.md), [RUNS_AND_OUTPUTS.md](RUNS_AND_OUTPUTS.md), [ARTIFACTS.md](ARTIFACTS.md), [../modules/runtime-adapters.md](../modules/runtime-adapters.md) |
| Policy and security | [POLICY_ENFORCEMENT_INVENTORY.md](POLICY_ENFORCEMENT_INVENTORY.md), [SECURITY_AND_ACCESS_BOUNDARIES.md](SECURITY_AND_ACCESS_BOUNDARIES.md), [../modules/policy.md](../modules/policy.md) |
| Credentials | [CREDENTIAL_STORAGE.md](CREDENTIAL_STORAGE.md), [../modules/credentials.md](../modules/credentials.md), [../modules/provider-policy.md](../modules/provider-policy.md), [../decisions/0010-credential-channel-isolation.md](../decisions/0010-credential-channel-isolation.md) |
| Memory, context, provenance | [MEMORY_MODEL.md](MEMORY_MODEL.md), [MEMORY_CONTEXT_RUNTIME.md](MEMORY_CONTEXT_RUNTIME.md), [MEMORY_ACTIVITY_PROVENANCE.md](MEMORY_ACTIVITY_PROVENANCE.md), [MEMORY_EVOLUTION_PLAN.md](MEMORY_EVOLUTION_PLAN.md) |
| Intake and evidence | [INTAKE_EVIDENCE_FOUNDATION.md](INTAKE_EVIDENCE_FOUNDATION.md), [../modules/activity.md](../modules/activity.md), [../modules/activity-inbox.md](../modules/activity-inbox.md) |
| Proposals and tasks | [PROPOSALS.md](PROPOSALS.md), [TASK_BOARD_MODEL.md](TASK_BOARD_MODEL.md), [../modules/proposals.md](../modules/proposals.md) |
| Operations | [OPERATIONS_AND_SAFETY.md](OPERATIONS_AND_SAFETY.md), [DATABASE_AND_TRANSACTIONS.md](DATABASE_AND_TRANSACTIONS.md) |
| Frontend | [FRONTEND_INFORMATION_ARCHITECTURE.md](FRONTEND_INFORMATION_ARCHITECTURE.md), [../modules/product-shell.md](../modules/product-shell.md), [../modules/frontend-layout.md](../modules/frontend-layout.md) |
| Local/offline compatibility | [LOCAL_FIRST_COMPATIBILITY.md](LOCAL_FIRST_COMPATIBILITY.md), [../modules/sync-and-conflicts.md](../modules/sync-and-conflicts.md), [../modules/mobile-client.md](../modules/mobile-client.md) |

---

## Capability Roadmap

### 1. Dogfooding Stabilization

**Next work**
- Collect incidents from real personal/household use.
- Expand contract tests only where dogfooding exposes real gaps.
- Rehearse backup and restore on a schedule.

**Prerequisites**
- Current auth, backup, run, proposal, and memory boundaries remain green.

**Risk watch**
- Fixes made during dogfooding can bypass source-of-truth docs or policy gates.
- Backup confidence can drift if restore is not rehearsed.

**Not now**
- More users, remote hosting, public launch.

---

### 2. Runtime and Adapter Safety

**Next work**
- Design the `one_shot_docker` path before allowing critical-risk file execution.
- Add external webhook/cron trigger integration only behind preflight and policy gates.
- Decide whether cross-process subprocess termination is needed after more real CLI runs.

**Prerequisites**
- Existing `model_api`, `claude_code`, and `codex_cli` paths remain stable.
- Credential resolver, worktree sandboxing, RunStep/RunEvent evidence, and preflight stay tested.

**Risk watch**
- New adapters can duplicate or bypass credential, sandbox, and policy behavior.
- Critical-risk execution must fail closed until Docker isolation is actually implemented.

**Not now**
- Docker sandbox pool, production container infrastructure, broad runtime marketplace.

---

### 3. Policy and Governance Expansion

**Next work**
- Wire reserved actions only when their product surfaces exist: capability enable/update, tool binding, artifact/evidence export, deployment proposal/execute.
- Current credential baseline: ModelProvider keys and CLI login profiles are
  user-owned resources with explicit active-space grants. Add per-run or
  per-tool credential scoping only after this grant boundary remains stable.
- CLI runtime tool installs are instance-admin-managed shared binaries. Space
  policy chooses enabled/default/allowed installed versions; credential grants
  remain user-owned and separate from tool installation.
- Keep policy tests focused on fail-closed behavior and audit durability.

**Prerequisites**
- `proposal.apply`, runtime gates, workspace read/write gates, artifact persistence gates, and credential gates stay centralized through the policy module.

**Risk watch**
- Policy can become scattered if new surfaces authorize directly.
- Overbuilding RBAC/ABAC too early can obscure the simpler product approval model.

**Not now**
- Full enterprise RBAC/ABAC, policy editor UI, policy DSL, agent-to-agent delegation.

---

### 4. Memory, Context, Intake, and Evidence Quality

**Next work**
- Implement planned memory-quality phases from [MEMORY_EVOLUTION_PLAN.md](MEMORY_EVOLUTION_PLAN.md) only through proposal-safe flows.
- Extend connector-specific ingestion behind Intake/Evidence lifecycle.
- Add synthesis and gap-analysis loops only when citations and proposal review stay explicit.

**Prerequisites**
- Activity-first capture, provenance links, source trust, context assembly, and proposal apply boundaries stay intact.

**Risk watch**
- External evidence can pollute trusted Memory if candidate and proposal boundaries are skipped.
- Context quality work can become untestable if it mixes retrieval, synthesis, and durable writes.

**Not now**
- Broad web crawling, vector index over external corpora, auto-promotion of external content to Memory.

---

### 5. Automation and Triggers

**Next work**
- Design external trigger registry after manual and scheduled automation behavior is stable.
- Add run caps, cost guardrails, and user-facing credential allowance UX before broad background execution.
- Keep automation-origin runs on the same preflight and policy path as manual runs.

**Prerequisites**
- Automation create/update/fire gates, preflight snapshots, and credential behavior remain auditable.

**Risk watch**
- Background work can silently mutate data if ownership, policy, or proposal gates are weakened.
- Credential fallback in automation paths must stay blocked.

**Not now**
- Arbitrary background jobs, external event trigger marketplace, critical-risk automation without Docker isolation.

---

### 6. Operations, Backup, Retention, and Export

**Next work**
- Define offsite backup procedure, starting with manual encrypted archive transfer.
- Schedule restore rehearsal and record operator checklist gaps.
- Define bulk Memory export and retention/delete semantics.

**Prerequisites**
- Full-system backup/restore remains consistent across database and file storage.
- Artifact and memory lifecycle states remain stable enough to export.

**Risk watch**
- Local-only backups are a single-site data-loss risk.
- Hard-delete semantics can conflict with audit/provenance if not designed explicitly.

**Not now**
- Automatic cloud sync, automatic restore, global hard-delete automation.

---

### 7. Frontend Command Center

**Next work**
- Build review inbox aggregate and continue-working surfaces from runs, tasks, proposals, and artifacts.
- Resolve frontend/backend type contract drift before adding new UI workflows.
- Keep planned modules visibly disabled until backend surfaces are real.

**Prerequisites**
- Backend aggregate APIs are stable and documented.
- Shell/module registry remains the source of truth for active frontend surfaces.

**Risk watch**
- Frontend can imply capabilities that are not active if planned modules become interactive too early.
- Frontend-only business rules can drift from server policy.

**Not now**
- Native mobile app, advanced offline queue, frontend-only permission inference.

---

### 8. Learning Loop and Self-Evolution

**Next work**
- Run managed dogfood flows against real workspaces before automating more of the loop.
- Validate RunReflection and proposal payload quality through human review.
- Define allowed self-evolution surfaces and evaluation gates before enabling capability lifecycle persistence.

**Prerequisites**
- Run finalization, task evaluation bridge, artifacts, proposals, and source monitoring remain auditable.
- Deployment remains host-deployer-only and proposal-gated.

**Risk watch**
- Self-evolution can expand scope or deployment authority if proposal and evaluation gates are bypassed.
- Learning proposals can become noisy if RunReflection quality is not validated against real tasks.

**Not now**
- Direct self-modifying agents, app-container deployment control, plugin marketplace, full native coding-agent loop.

---

## External Absorption Backlog

Items from the PilotDeck (P*) and Hermes (H*) review that are deferred, not
rejected. Each maps to a capability section above. Rejected items are listed
at the end.

| Item | Description | Maps to |
|---|---|---|
| H3 | Provider privacy/compliance policy: data-collection deny, provider allow/deny, required parameter rules. Add as space-scoped policy/provider-routing rules, not global config. | Capability 3 (Policy and Governance) |
| H4 | Durable apply rollback: pre-apply snapshots and user-facing rollback for proposal apply operations. Future workspace/proposal-apply hardening. | Capability 2 (Runtime and Adapter Safety) |
| P2 | Per-session chat concurrency guard. Add only if real chat ordering issues appear during dogfooding. | Capability 1 (Dogfooding Stabilization) |
| P3 | Full context engine: prompt assembly, message projection, token budgeting, graduated compaction, overflow recovery. Build TS-native on top of migrated context/session/memory seams. | Capability 4 (Memory, Context, Intake) |
| P6/P7 | Self-hosted TS agent loop (AgentSession/TurnRunner/AgentLoop), tool scheduler (sequential/concurrent with observability), MCP client integration. `RuntimeToolBinding` remains the authorization surface until then. | Capability 2 (Runtime and Adapter Safety) |
| P8 | Channel adapters: IM/email/channel ingestion with external-session mapping. Requires stable intake/evidence provenance and proposal boundaries first. | Capability 5 (Automation and Triggers) |
| P9 | Always-On governance: trigger budgets and cooldowns. Future automation/policy vocabulary. | Capability 5 (Automation and Triggers) |

**Explicitly rejected (not to be revisited without a new decision):**
- PilotDeck-style secrets in YAML or `${ENV}` substitution.
- Global single-scope config that ignores `space_id`.
- Gateway-as-plugin/event-bus architecture.
- Hermes local `auth.json` credential pool state.
- Hermes media stack, batch RL trajectory generation, and external memory provider backends as MVP work.
- OpenAI-compatible API server as a planned stage.

---

## Known Future Risks

| Risk | Why it matters | Watch / next action |
|---|---|---|
| Distributed DB locking | Single-host advisory locks do not cover multi-host deployments | Revisit only before multi-host operation |
| RunStep ordering under concurrency | `MAX()+1` style ordering can race with distributed writers | Consider DB sequence or distributed counter before multi-writer runs |
| Cloud/offsite backup | Local backups do not protect against host loss | Define manual encrypted offsite flow first |
| Retention and hard delete | Personal data deletion must preserve clear audit semantics | Design retention/export/delete together |
| Credential scoping | Current resolver is a single release boundary | Add per-run/per-tool grants only with audit and UX |
| Broad ingestion privacy | Connectors can import sensitive data at scale | Keep Intake/Evidence candidate-only and proposal-gated |
| Automation scope creep | Background runs can become hidden mutation paths | Require ownership, preflight, policy, and proposal boundaries |
| Self-evolution scope creep | Agents can gain deployment or permission authority | Keep disabled until lifecycle/evaluation/rollback are real |
| Code patch partial apply | File rollback failures can leave workspaces inconsistent | Keep partial-apply errors explicit and reviewable |
| Disabled surfaces exposed in UI | Users can rely on features that are not active | Keep `planned: true` modules non-interactive |
| Actor identity backfill | Historical nullable user/agent fields remain across tables | Use `actor_ref` on new surfaces; avoid bulk migration until needed |
| Workspace sessions / API keys | Operator-only surfaces can become accidental product APIs | Keep feature-gated until ownership and UX are designed |
