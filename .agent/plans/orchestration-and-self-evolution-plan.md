# Orchestration + Self-Evolution — Remaining Work Plan

Date: 2026-07-13
Status: active follow-up backlog

This document is intentionally limited to work that is not complete. The
completed Phase 0/A/B/C/D implementation slice, its historical audit, commit
list, and settled architecture decisions are no longer repeated here.

Implementation truth remains the code. Current-state architecture belongs in
the documents under .agent/architecture/; accepted cross-cutting decisions
belong in .agent/decisions/. This file is only the forward-looking backlog
and its completion gates.

## How to use this plan

- Status OPEN means the item is still open.
- Status PARKED means the item is deliberately deferred, not current work.
- Every implementation item must update the relevant current-state
  architecture document and add focused tests.
- Database-backed behavior must use the shared real-PostgreSQL test
  infrastructure. A skipped local container is not evidence of completion.
- Proposal, policy, credential, space-isolation, and server-authoritative
  boundaries remain unchanged while these items are implemented.

## 0. Existing correctness gaps to close first

These are not new product features. They are remaining gaps in the current
implementation and must be closed before this plan can be considered fully
reconciled.

### H1 — Plan-node budget admission and source validation

- [ ] Make PgPlanRepository.scheduleReadyNodes perform the same budget-source
  admission used by the Task API before creating a child Run or inserting its
  task_runs link.
- [ ] Keep source validation, advisory-lock admission, Run creation,
  task_runs insertion, and queue enqueue in the same transaction.
- [ ] Validate node-level contract_json.budget_sources during Plan creation
  and revision; do not validate only top-level PlanVersion sources.
- [ ] Ensure exhausted Task, Automation, Workflow, or Plan sources cannot
  leave behind a queued Run or a task_runs row.
- [ ] Add shared-PostgreSQL coverage for exhausted node budgets, inherited
  budgets, concurrent manual-vs-Plan admission, and rollback after rejection.

Primary implementation areas:
server/src/modules/plans/repository.ts and
server/src/modules/runs/budgetEnforcement.ts.

### H2 — Strict Workflow budget-source ownership

- [ ] Make Workflow source validation require an approved version of an active
  Workflow asset.
- [ ] Enforce parent-asset ownership, space visibility, and version-scope
  consistency for caller-supplied Workflow Version IDs.
- [ ] Cover cross-space, stale/archived-asset, mismatched-scope, and
  system-visible Workflow cases with real-PostgreSQL tests.

Primary implementation area:
server/src/modules/runs/budgetEnforcement.ts.

## 1. Execution follow-ups

### A2.1 — Manual and model-based verification

- [ ] Implement the declared manual_review verifier lifecycle, including
  durable pending/approved/rejected state and its effect on completion.
- [ ] Implement model_judge with a separately selected verifier model, never
  silently reusing the generator model.
- [ ] Add policy, audit, retry, and API read-model coverage.

Constraint: deterministic Verification Engine results remain the completion
authority; model or human judgment must be an explicit verifier result.

### A3.1 — Runtime sessions and checkpoint/resume

- [ ] Persist runtime session references with ownership and provenance.
- [ ] Define checkpoint creation, resume, fork, and invalidation semantics
  across process restart.
- [ ] Define how checkpoint/resume interacts with RunAttempt retry, route
  reroute, cancellation, orphan recovery, and credentials.
- [ ] Add runtime-boundary and real workflow tests; do not infer resume
  success from an adapter-local session ID alone.

## 2. Workflow and automation lifecycle

### B3.1 — Replace or retire hardcoded business fires

- [ ] Migrate executeMaintenanceFire and the context review cycle to
  versioned system Workflow templates, or explicitly retire them as
  documented native targets.
- [ ] Preserve proposal, policy, credential, budget, and audit behavior during
  the migration.
- [ ] Add a guard that prevents new unregistered hardcoded business fires.
- [ ] Update ROADMAP_AND_FUTURE_RISKS.md when the decision is made.

### B4.1 — Complete Save Run as Workflow lifecycle

- [ ] Complete the proposal-gated path beyond draft extraction so an accepted
  save can be used through the normal approved Workflow lifecycle.
- [ ] Add end-to-end coverage from source Run to draft, approval, approved
  version, and subsequent launch.

Constraints: extraction stays sanitized; credentials, host paths, transient
Run IDs, and unreviewed mutable runtime state must not become Workflow
definition content. Always-draft behavior and standard proposal/promotion
gates remain in force.

## 3. Runtime hardening follow-ups

### C3.1 — Conformance second wave

- [ ] Add forbidden-tool detection.
- [ ] Add premature-completion detection.
- [ ] Add validation-compliance checks.
- [ ] Add artifact-production checks.
- [ ] Add timeout-behavior checks.
- [ ] Add cost/latency profiling.
- [ ] Feed the results into routing trust decisions without weakening the
  current fail-closed behavior.

### C3.2 — Reviewed egress-enabled execution profile

- [ ] If required, design and separately review an egress-enabled Docker
  profile with explicit destinations, credential channel rules, audit records,
  and resource limits.
- [ ] Add policy and runtime tests before exposing the profile to any route.

Constraint: networked provider-proxy execution remains disabled by default.

## 4. Evolution-loop follow-ups

### D1.1 — Remaining automatic signal generation

- [ ] Inventory the signal classes that are still emitted only by manual
  actions.
- [ ] Add automatic emitters at the authoritative durable event boundaries.
- [ ] Preserve deduplication, visibility, target resolution, severity, and
  dismiss/triage behavior.
- [ ] Add emitter and persistence tests for each newly automated class.

### D1.2 — Artifact user-edit tracking

- [ ] Record user edits to generated artifacts with actor, artifact version,
  source Run, and before/after provenance.
- [ ] Convert meaningful edit patterns into evolution evidence/signals without
  treating every edit as an automatic promotion or memory write.
- [ ] Add workspace, artifact, privacy, and cross-space isolation tests.

### D2.1 — Automatic candidate-run launch

- [ ] Allow an evaluation job to launch a candidate Run from
  EvaluationCase.input_json through the normal Plan/Run admission path.
- [ ] Persist candidate version pinning, launch provenance, verification
  results, baseline comparison, and failure state.
- [ ] Preserve warn-only versus hard-gate promotion policy and add real
  workflow coverage for launch, retry, failure, and promotion blocking.

Constraints: candidate output must remain system-produced; callers must not
submit candidate_output_json. Existing warn-only versus hard-gate promotion
policy must not be weakened.

## 5. Approval and budget policy follow-up

### N8.1 — Budget inheritance in auto-approval

- [ ] Define how space-level and Automation-level budget inheritance
  participates in the low-risk Plan auto-approval threshold.
- [ ] Specify precedence, effective-cap calculation, ownership, and the
  transaction boundary before implementation.
- [ ] Persist the resolved decision inputs and add approval-boundary tests.

## 6. Deliberately parked work

These items remain incomplete but are not part of the active implementation
sequence. They should not be silently pulled into the default orchestration
chain.

- PARKED — OMO / oh-my-openagent integration: benchmark/reference track only.
- PARKED — ML-based routing: the deterministic Router remains authoritative.
- PARKED — Native capability executor: keep disabled until separately designed and
  policy-gated.
- PARKED — Workflow canvas UI: structured Plan/Workflow views remain sufficient for
  the current scope.
- PARKED — AgentRunGroup extensions into a task graph: keep AgentRunGroup as a
  collaboration surface.

The companion hardening backlog remains in
hardening-blind-spot-remediation-plan.md; this document does not duplicate
its P1/P2 operational work.

## Recommended delivery order

1. H1 and H2 — close current correctness and isolation gaps.
2. A2.1, A3.1, and C3.1 — deepen execution correctness and runtime trust.
3. B3.1 and B4.1 — complete the Workflow lifecycle.
4. D1.1, D1.2, and D2.1 — complete the automatic evolution loop.
5. N8.1 — extend auto-approval only after the budget model is explicit.

## Plan completion and retirement criteria

This plan can be retired or deleted only when:

- all active OPEN items are complete, or explicitly moved to an architecture
  roadmap/decision record;
- each changed behavior has focused unit, route, invariant, or shared
  PostgreSQL workflow coverage as appropriate;
- current-state architecture documents no longer depend on this plan for
  implementation truth;
- the companion plan and ROADMAP_AND_FUTURE_RISKS.md no longer contain
  broken or ambiguous references to this file.

Until then, this file should remain a small remaining-work backlog rather than
another implementation history document.
