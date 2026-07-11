# Orchestration + Self-Evolution — Unified Audit and Implementation Plan

Date: 2026-07-11
Status: draft, pending owner review
Supersedes: `.agent/plans/self-evolution-implementation-plan.md` (its audit
findings and decisions are folded in here; the file is removed).

Scope: merges two instruction guides into one plan —
(1) the self-evolution guide (workflow-as-data, observations, eval harness,
evolution bundles) and (2) the task-planning/execution guide (task contract,
verification engine, plan/task graph, RunAttempt/supervisor, model-runtime
router, runtime hardening). They overlap heavily at the execution layer;
building them separately would create the dual-track orchestration and
dual-track verification this codebase has so far avoided.

---

## Part I — Audit

### 1. Evolution-layer audit (from v1 plan, condensed; all verified)

- **Run provenance is complete.** `runs` pins `agent_version_id`,
  `runtime_profile_snapshot_json`, `context_snapshot_id`,
  `model_provider_id`, `capabilities_json`, `trigger_origin`; evidence spine
  = RunStep/RunEvent/RunEvaluation/RunFinalization/TaskEvaluation +
  `/runs/{id}/trace`. Prompt usage recorded as version refs + hashes in step
  metadata (`prompts/provenance.ts`). `token_usage_events` has per-run cost.
- **Prompt versioning is complete** on `evolvable_assets` +
  `evolvable_asset_versions` (immutable) + pins + `prompt_deployment_refs`
  + scope-chain resolver; promotion only via
  `evolvable_asset_version_promote` proposal.
- **Capability lifecycle is complete** (versions/enablements/overlays/
  runtime bindings/skill import), proposal- and policy-governed. Native
  capability executor disabled.
- **Evolution foundation exists**: targets/signals/strategy_assets/
  selector_decisions/experiences; evolution runs are proposal-only by
  applier/policy boundary (hard) plus planner prompt (advisory).
  `evolvable_asset_evaluation_runs` is record-only — no executor.
- **True evolution gaps**: workflow-as-data + multi-step execution;
  save-run-as-workflow; automatic signal generation (signals are manual
  POST only); evaluation harness execution; evolution bundle with partial
  approval; artifact user-edit tracking; hardcoded automation business
  fires (`executeMaintenanceFire`, context review cycle).

### 2. Execution-layer audit (new; guide-2 assumptions verified)

**Assumption A — "agent-space already has a full agent loop": FALSE.**
Reality is an execution control plane: run orchestration + adapter
execution + materialization + deterministic status classification. There
is no planner, no atomicity evaluator, no router, no verification engine,
no supervisor. This is a good control plane to build on, not a loop.

**Assumption B — "task contract fields reach execution": FALSE.**
`tasks` schema has `acceptance_criteria_json`, `definition_of_done`,
`required_outputs_json`, `risk_level`, `max_runs`, `max_cost`,
`max_duration_seconds` ([tasks.ts:104-127](server/src/db/schema/tasks.ts)).
Consumers are tasks-module CRUD mappers only — nothing flows into run
creation, context, orchestration, or evaluation. **Schema-only.**

**Assumption C — "finalization judges real completion": FALSE.**
Adapter success is `returncode === 0 && !timed_out`
([vendorCliAdapter.ts:373](server/src/modules/runs/vendorCliAdapter.ts#L373));
RunEvaluation classifies from status/error codes/steps/events and
explicitly performs no acceptance-criteria checking and no LLM judging.
Code-patch validation is **deferred/skipped by design**
([codePatch.ts:179](server/src/modules/workspaces/codePatch.ts#L179)).
So: CLI exit 0 → run `succeeded` → outcome `passed` absent other signals.

**Assumption D — "new runtime = add a RuntimeAdapterSpec": FALSE.**
Dispatch is hardcoded in `invokeAdapterUnbounded`
([orchestrationService.ts:1044-1080](server/src/modules/runs/orchestrationService.ts#L1044)):
`model_api|ts_agent_host` → managed adapter; `claude_code|codex_cli` →
vendor CLI adapter; else fail. The spec registry describes runtimes but
does not dispatch them. (Mitigating: `executeVendorCliAdapter` is generic
over the spec, so a new local CLI is close — but the central enum must be
edited.)

**Assumption E — "CLIs can be restricted to single-agent": NOT DECLARED.**
`RuntimeAdapterSpec` has no fields for subagent support, delegation
controllability, structured output, checkpoint/resume, cancellation
reliability, observability, or side-effect level
([specs.ts:17-77](server/src/modules/runtimeAdapters/specs.ts#L17)).
Two delegation planes exist today:
- *System-level*: `agent.delegate`/`agent.wait_for_results` are exposed
  **only** to managed-API runs inside an AgentRunGroup, policy-gated by
  `run.spawn_child`. Vendor CLIs never see these tools. Guide-2's fear
  that delegation is "default exposed" is NOT confirmed.
- *Runtime-internal*: Claude Code / Codex internal subagents (e.g. Task
  tool) are invisible, undeclared, and uncontrolled. This half IS
  confirmed.

**Assumption F — "worktree is a sufficient high-risk sandbox": FALSE.**
Worktree scopes file writes only; no network/OS/resource isolation.
`one_shot_docker` exists only as a spec enum value — no adapter enables
it (**schema-only**). `permission_bypass` is spec- and config-gated
(`cliCommandRendering.ts:50-72`), driven by trusted-internal
`adapter_config`; no dedicated policy-module gate was found for it.

**Assumption G — "AgentRunGroup can become the task graph": NO.**
It is a chat-collaboration room with manager-mediated, runtime-initiated
delegation. It has no versioned plan, no dependency DAG beyond
wait-for-results, no verification per node. Keep it as a collaboration
surface; do not extend it into planning.

**Assumption H — "routing = choosing a model": FALSE today, agreed
target.** Today the launcher/user picks an Agent runtime profile at run
creation; model comes from profile/input (`runtimeProviderBinding.ts`).
There is no route decision object, no fallback chain, no history-informed
selection. (Evolution's `selector_decisions` audits *strategy* choice —
a good pattern to copy for route decisions.)

**Reliability findings:**
- **No RunAttempt.** No retry exists at any level for agent work;
  `jobs.attempts` is infrastructure-only dispatch retry. Run = one
  physical execution today (execution locks prevent concurrency), so the
  Run/Attempt split is a real but not-yet-bleeding gap.
- **Cancel** SIGTERMs via an **in-memory** process registry
  ([processRegistry.ts](server/src/modules/runs/processRegistry.ts)) and
  marks the run cancelled regardless of actual process exit
  (`process_terminated` is recorded best-effort; no `cancelling` state, no
  SIGKILL escalation on cancel, no cancel RunEvent — the event_type CHECK
  is closed). Server restart loses the registry → orphaned processes.
- **Timeout is real**: SIGKILL of the process group after
  `timeout_seconds` ([localCliExecution.ts:117](server/src/modules/runs/localCliExecution.ts#L117)).
- **No stall/no-progress detection, no checkpoint/resume, no runtime
  session reference.**
- **Best-effort evidence tension**: RunEvents are savepoint-isolated
  best-effort writes, yet RunEvaluation names them the primary
  classification source. Acceptable for classification; must NOT become
  the completion authority (that is the Verification Engine's job).

### 3. Verdicts (guide-2 §九)

1. System-level agent loop? **No — execution control plane only.**
2. Control plane vs supervisor? **Control plane, a solid one.**
3. Build own Planner/Router/Verification/Supervisor? **Yes — nothing
   occupies these seats; no dual-track risk in building them.**
4. Need RunAttempt? **Yes, when retry lands (Track A3) — not before.**
5. Task as Plan Node? **Yes — extend `tasks` (+`task_dependencies`,
   `task_runs`) rather than invent a parallel PlanNode table.**
6. AgentRunGroup as Task Graph? **No — keep as chat collaboration.**
7. Default-disable runtime subagents? **Yes as declared policy; today
   enforcement is only real for system-level delegation. CLI-internal
   subagents need per-runtime config (Claude Code: disable Task tool via
   settings) + conformance testing; where uncontrollable, cap trust
   level instead of pretending.**
8. OpenCode as runtime? **Yes—as the third optional CLI runtime after C1's
   registry dispatch + capability declarations. It is a peer of Claude Code
   and Codex, not a universal runtime or Router default.**
9. Full OMO integration? **No — benchmark/reference only (guide-2's own
   position; adopting its orchestration would dual-track Planner/Router/
   Supervisor).**
10. OMO mechanisms worth studying? **Completion/continuation enforcement,
    stall detection, recovery loops — as references for A3.**
11. Smallest most important slice? **Track A1 (task contract into runs) +
    A2 (verification engine) — they de-risk everything else and are
    prerequisites for both guides.**
12. Stop extending to avoid dual-track? **AgentRunGroup delegation
    features (freeze at current scope); hardcoded automation business
    fires (no new ones); WorkflowRunDraft single-run compilation (no new
    workflow features on the static-template path once B1 lands).**

### 4. High-priority confirmed issues (guide-2 §八 filter)

Confirmed and must be fixed by a named phase: exit-0-as-success (A2);
acceptance criteria/budget/risk not reaching execution (A1); patch
validation skipped (A2); no attempt identity (A3); cancel without exit
confirmation + in-memory-only registry + no orphan handling (A3);
one-shot docker schema-only / high-risk without strong isolation (C3);
spec-registry-vs-hardcoded-dispatch mismatch (C1); RuntimeTool/Extension/
Skill/Plugin naming audit (Phase 0); best-effort events as sole
classification source (documented A2 boundary). Not confirmed: delegation
default exposure (it is group-scoped managed-API only); timeout leaving
processes alive (SIGKILL works).

---

## Part II — Fusion Analysis (what merges, what stays separate)

### Must be built as ONE thing (separate builds would dual-track)

**F1. Workflow execution ≡ Plan/Task-graph execution.**
The v1 plan's `WorkflowRunCompiler` (W2) and guide-2's Plan/PlanVersion
executor (its Phase 3) are the same machine: expand a node graph into
parent/child runs with dependencies, per-node bindings, verification, and
checkpoints. Build **one graph-execution substrate**:
- `WorkflowVersion` = a *reusable, versioned template* of a task graph
  (evolvable asset, per v1 D1).
- `Plan/PlanVersion` = a *per-goal instance* of a task graph (dynamic,
  possibly LLM-planned, revisable).
- Both compile to the same runtime representation: parent run + Task
  nodes (+ `task_dependencies`) + child runs, executed by one scheduler.
  A workflow launch materializes a Plan instance from the template.

**F2. Verification Engine ≡ Evaluation-harness execution core.**
Guide-2's verifiers (command/test/lint/typecheck/file/diff/artifact/
schema/proposal/manual/model-judge) and the evolution eval harness both
"run checks against an execution and produce structured results". Build
the Verification Engine once; the eval harness is that engine applied to
(EvaluationCase fixture × candidate asset version) with baseline
comparison writing `evolvable_asset_evaluation_runs`.

**F3. One Router.**
Guide-2's Model–Runtime Router, workflow-step `model_routing_hint`, and
evolution strategy `routing_hint_json` are one component with three hint
sources. Route decisions get one audited record type (copy the
`evolution_selector_decisions` pattern).

**F4. One observation/signal pipeline.**
Evolution observations (E1) and supervisor telemetry (retry rates, stall
detections, verification failures, conformance violations) write to the
same `evolution_signals` stream — the supervisor emits signals as a
by-product, not a second metrics system.

### Can and should be SPLIT (independently shippable)

- **A1 Task contract snapshot** — pure plumbing, no design coupling.
- **C1 adapter registry dispatch + capability declarations** — mechanical,
  unblocks OpenCode later, needed by Router but shippable alone.
- **E1 rule-based signal emitters** — reads existing finalization/proposal
  events; independent of all planner work.
- **B1 workflow-as-data (definitions only)** — versioning + storage lands
  without the execution substrate (static fallback keeps working).
- **C3 sandbox hardening / one-shot docker** — orthogonal to planning.
- **D3 evolution bundles**, **B4 save-run-as-workflow**, **frontend
  consolidation** — deferred consumers of the above.
- **OMO evaluation** — separate benchmark-only track, no core dependency.

---

## Part III — Target Architecture (summary)

Written into `.agent/architecture/TASK_PLANNING_ROUTING_AND_EXECUTION.md`
as phases land (current-state rule). Core commitments:

- **Objects**: Goal → Plan → PlanVersion → Task (plan node; existing
  `tasks` + `task_dependencies`) → Run → (later) RunAttempt;
  RouteDecision; VerificationResult; SupervisorDecision. Workflow
  templates are evolvable assets whose approved versions materialize
  Plans.
- **Components**: Planner (LLM-backed, proposal-governed output = a
  PlanVersion, never direct execution), Atomicity Evaluator (hybrid:
  rules first, LLM assist), Router (deterministic rules + static
  capability matrix + history), Scheduler (deterministic TS), Executor
  (existing orchestration), Verification Engine (deterministic TS +
  optional verifier-model, distinct from generator model), Supervisor
  (deterministic policy over verification results: complete/retry/
  reroute/replan/review/fail; replan emits a new PlanVersion proposal).
- **Execution modes**: `strict_leaf` / `bounded_local` recorded per run;
  `system_coordinator` reserved for Planner-owned runs. Default
  `bounded_local` for coding CLIs, `strict_leaf` for model_api.
- **Boundary**: complex → decompose in agent-space; leaf → one runtime +
  one model; runtime-internal delegation declared per adapter and
  disabled where the runtime allows; undisableable ⇒ lower trust level,
  excluded from high-risk routes.
- **Leaf criteria** (atomicity contract): single primary goal;
  independently verifiable; explicit input/file scope; no system-level
  delegation needed; within one runtime/model budget; independently
  retryable; explicit dependencies. Depth/size caps: max decomposition
  depth 3, max tasks per PlanVersion 30 (config), insufficient-info ⇒
  explicit `exploratory` leaf task whose output is information for the
  next PlanVersion, not silent scope expansion.

---

## Part IV — Phased Plan

Tracks run in parallel where dependencies allow. Every phase: additive
migration, focused tests, doc update, separate commit. No old-model
deletion before migration proof.

### Phase 0 — Facts and naming (docs only)
- Update `EXECUTION_MODEL.md` / `RUNS_AND_OUTPUTS.md` /
  `CAPABILITY_WORKFLOW_SKILL_SYSTEM.md` where audit found drift
  (spec-registry-vs-dispatch; patch validation deferred; delegation
  exposure reality; one-shot docker unimplemented).
- Naming audit note: RuntimeBinary (runtimeTools) / RuntimeAdapter /
  RuntimeExtension (new concept, empty today) / RuntimeToolBinding /
  RuntimeSkillBinding / ProductPlugin — record the target glossary in
  `GLOSSARY.md`; no code rename yet.
- Mark schema-only fields (`tasks.max_*`, acceptance fields,
  `one_shot_docker`) as "declared, not enforced" in docs.

### Track A — Execution correctness (both guides' prerequisite)

**A1 Task Contract into Run.**
Immutable `contract_snapshot_json` on Run (acceptance criteria, required
outputs, definition of done, risk, budget caps, project, route hints)
populated at run creation from Task/Automation/Workflow source; TaskRun
creation path fixed to carry project/risk/budget; API mappers return the
contract fields. Enforcement in this phase: `max_duration_seconds` →
adapter timeout; `max_runs` guard at dispatch; cost cap recorded (hard
enforcement needs mid-run usage, comes with A3). Tests: snapshot
immutability, propagation from each origin.

**A2 Verification Engine.**
`verification_results` table (run-scoped, verifier type, status,
evidence refs, verifier version). Deterministic verifiers first:
command/test/lint/typecheck (reusing ValidationRecipe), file_exists/
file_changed/diff_scope, artifact_exists/artifact_schema, output_schema,
proposal_created, no_forbidden_change. Wire: code-patch validation stops
being skipped (replaces [codePatch.ts:179](server/src/modules/workspaces/codePatch.ts#L179)
deferral); RunEvaluation gains a verification-informed outcome input
(exit-0 alone no longer yields `passed` when a contract snapshot declares
checks); TaskEvaluation upgraded from status projection to
verification-backed. `manual_review` and `model_judge` verifier types are
declared but land later (model_judge must use a different model than the
generator). Root/integration verification arrives with B2.

**A3 RunAttempt + Supervisor MVP.**
`run_attempts` table (run keeps logical identity; attempt = one physical
execution; existing single-execution runs backfill as attempt 1).
Retryable-error classification over existing structured `error_code`s.
Supervisor as deterministic policy: same-route retry (capped) → reroute
(needs C2; until then, fail to review) → human review; replan added in
B2. Cancellation hardening: `cancelling` state, SIGTERM→wait→SIGKILL
escalation, confirmed-exit recording, orphan detection on startup (stale
running runs + lost registry ⇒ `orphaned` handling instead of silent
stale). Budget: cost aggregation across attempts, cap enforcement.
Stall detection: no-output/no-event watchdog for CLI attempts.

### Track B — Orchestration substrate

**B1 Workflow-as-data.** (= v1 W1)
`workflow_definition.v1` protocol schema (extends existing
`workflows.ts` shapes; node list with dependencies, capability/prompt/
agent bindings, verification recipe refs, approval checkpoints); built-in
research templates seeded as system evolvable assets; publish via
existing promotion proposal; `runs.workflow_version_id`. Static built-in
path stays as fallback and is frozen (no new features).

**B2 Unified graph execution.** (fusion F1; = v1 W2 + guide-2 Phase 3)
Plan/PlanVersion tables; Task rows as plan nodes (`plan_version_id`,
`node_kind` incl. `integration`, `superseded_by`); one scheduler
expanding graphs into parent+child runs via existing
`waiting_for_dependency` parking; per-node contract snapshots (A1) and
verification (A2); approval-checkpoint nodes park on proposals;
parent/root integration verification; plan revision = new PlanVersion
(completed tasks carry over, replaced ones marked superseded).
Workflow launch = materialize PlanVersion from WorkflowVersion.
Planner (LLM decomposition) ships behind proposal review with a
low-risk auto-approve threshold (decision N8): a generated PlanVersion
auto-approves only when every node is risk=low, node count ≤ threshold
(config, initial 8), aggregate budget within the declared cap, and no
node requires high/critical capabilities or permission bypass; all other
plans require human approval. Atomicity rules enforce leaf criteria +
depth/size caps.

**B3 Automation → workflow/plan.** (= v1 W3) Automation target
`workflow` with pin-vs-follow explicit; unattended triggers nudged to
pin; hardcoded maintenance fires frozen and documented (decision 1-B).

**B4 Save Run as Workflow.** (= v1 W4, resequenced after B2 so
extraction uses real graph/step data.) Extraction + sanitization
(inputs→schema, strip credentials/paths/run ids); always a draft.

### Track C — Routing and runtime hardening

**C1 Adapter registry dispatch + capability declarations.**
Replace the `invokeAdapterUnbounded` enum with spec-driven dispatch
(spec declares its executor family); extend `RuntimeAdapterSpec` with:
subagent_support + disable mechanism, delegation_controllability,
structured_output, checkpoint/resume, cancellation_reliability,
observability_level, side_effect_level, data_exposure, trust_level.
Declarations honest per runtime (Claude Code: subagents disableable via
config; Codex: verify; managed API: none). Enforce declared no-subagent
config in vendor CLI command rendering where supported.

**C1.5 OpenCode adapter.** (decision N11; researched 2026-07-11 against
opencode.ai docs) OpenCode (sst/opencode) fits the existing
`local_cli` spec shape and is notably the most controllable of the three
CLIs on paper:
- Headless: `opencode run "<prompt>"` with `--model provider/model`
  (model override), `--agent <name>` (agent selection), `--dir`
  (working directory), `--format json` (raw JSON event stream —
  structured output stronger than current stdout parsing).
- Sessions: `--session <id>` / `--continue` / `--fork` — the first CLI
  runtime with a usable session-resume primitive (candidate for A3
  checkpoint/resume experiments; store the session id as the runtime
  session reference).
- **Single-agent enforcement is real config, not hope**: per-agent
  `permission.task: {"*": "deny"}` removes subagents from the Task tool
  entirely; per-agent tool permissions (`edit`/`bash`/`webfetch` →
  allow/ask/deny) give declarative tool restriction. Context prep
  renders a per-run `opencode.json` into the sandbox defining a
  locked-down agent (same pattern as `codexProviderConfig.ts`).
- Credentials: `opencode auth` login state → `cli_profile` credential
  mode, same broker channel as Claude/Codex (ADR 0008 applies).
- Subscription compatibility: ChatGPT Plus/Pro may use OpenCode while official support
  remains available. Claude Pro/Max must stay on native Claude Code because OpenCode's
  official provider docs state Anthropic prohibits routing that subscription through
  OpenCode. Do not restore removed plugins or bypass that boundary.
- Implementation: one `LocalCliRuntimeAdapterSpec` entry + rendered
  config + auth profile plumbing after C1's dispatch cleanup; then run
  the C3 conformance MVP against it before allowing non-low-risk routes.
OMO (oh-my-openagent, ex-oh-my-opencode: Sisyphus orchestrator,
ultrawork, background/async subagents, automatic model overrides) is
confirmed to be exactly the dual-track orchestration guide-2 warns
about — never enabled in the default chain; benchmark-only (its LSP/
AST-grep tools remain candidate RuntimeExtensions later).

**C2 Model–Runtime Router MVP.** (fusion F3)
`RouteCandidate`/`RouteDecision` per guide-2 sketch; hard filters
(credential availability, capability/tool requirements, sandbox needs,
risk×trust_level, execution mode) → rule scoring (static matrix + cost/
latency estimates + historical verification pass rate from A2/A3 data) →
fallback chain. Route decisions persisted (selector-decision pattern) and
stamped on run/attempt. Hint sources: task contract, workflow node,
evolution strategy. No ML.

**C3 Conformance + sandbox hardening.**
Runtime conformance suite run per runtime×version; results feed the
router matrix and trust levels. MVP scope (decision N10) is five checks:
file-scope obedience, subagent-attempt detection, cancel reliability,
structured-output compliance, credential leakage. Second wave: forbidden
tools, premature completion, validation compliance, artifact production,
timeout behavior, cost/latency profiling. One-shot docker executor for
high/critical risk; high-risk without strong isolation fails closed
(policy). Network/resource policy for CLI attempts.

### Track D — Evolution loop (on top)

**D1 Rule-based signal emitters.** (= v1 E1; fusion F4) Finalization
failures/repeats, proposal rejected/request-changes, cost/latency
thresholds, verification failures (A2), supervisor outcomes (A3),
conformance violations (C3) → `evolution_signals` with dedup windows.
Independent; can start immediately.

**D2 Evaluation harness.** (= v1 E2; fusion F2; depends A2)
`evaluation_cases` (+create-from-run); executor job = Verification
Engine over candidate vs baseline in sandbox with read-only/mock
connectors; regression detection; results into
`evolvable_asset_evaluation_runs`; promotion proposals embed eval
summary (warn-only default, hard-gate switch per risk level — decision
2-B).

**D3 Evolution bundles + partial approval + rollback.** (= v1 E3)
Bundle grouping over ordinary proposals; combination rollback restoring
recorded version sets.

**D4 Frontend consolidation.** Workflows/Plans list+detail (structured
list, no canvas), Evolution Inbox (signals→bundles→evidence→eval→
approval), run detail: contract/verification/route/attempt panels,
save-as-workflow flow.

### Sequencing summary

```
Phase 0 ─┬─ A1 ── A2 ── A3 ──────────┐
         ├─ B1 ─────────── B2 ── B3 ─┴─ B4
         ├─ C1 ─────────── C2 ─────────── C3
         └─ D1 ──(A2)───── D2 ─────────── D3 ── D4
```
Recommended start order: Phase 0 → A1 + B1 + C1 + D1 (parallel, small) →
A2 → B2 + C2 → A3 → B3/B4/C3/D2 → D3/D4.

Pre-gate: the P0 week of
[hardening-blind-spot-remediation-plan.md](hardening-blind-spot-remediation-plan.md)
(CI, deployer invariants, backup fixes, minimal alerting, direction
decisions) runs BEFORE implementation commits start here; its P1 items are
folded into tracks C3 (egress), A1/A3 (budget), D1 (approval metrics), B3
(scheduler catch-up).

Explicitly deferred: OMO (benchmark-only after C3 exists), ML router,
artifact user-edit tracking (decision 3-B), native capability executor,
workflow canvas UI, AgentRunGroup extensions (frozen). OpenCode is NOT
deferred — it lands as C1.5 (decision N11).

---

## Part V — Decisions

**Status legend**: RECOMMENDED = my recommendation, still awaiting
explicit owner confirmation. CONFIRMED = owner decided (date noted).

Carried from v1 — all four owner-CONFIRMED 2026-07-11:
1-B freeze+document hardcoded automation fires; 2-B eval gate warn-only
with declared hard-gate switch condition; 3-B defer artifact edit
tracking, use proposal review signals as user-correction proxy; 4-A
deterministic parent/child execution, not AgentRunGroup. Note: 4-A is
subsumed by N1 (one graph-execution substrate) and the AgentRunGroup
verdict — it no longer exists as a separate choice. Long-lived
follow-ups from 1-B/2-B/3-B are recorded in
`.agent/architecture/ROADMAP_AND_FUTURE_RISKS.md` (Capability 6 and 9)
so they survive beyond this plan.

Architecture decisions taken in this plan (RECOMMENDED, structural):
- **N1** One graph-execution substrate for workflows and plans (F1) —
  the single most important anti-rework decision.
- **N2** Verification Engine is the completion authority; RunEvaluation
  remains harness classification; eval harness reuses the engine (F2).
- **N3** Task rows are the plan nodes; no parallel PlanNode table.
- **N4** RunAttempt lands with retry (A3), not speculatively.
- **N5** Router is one component with three hint sources (F3); route
  decisions are audited records.
- **N6** Runtime-internal subagents: declare per adapter, disable where
  possible, degrade trust where not; never assume.
- **N7** Planner output is proposal-governed (a PlanVersion to review),
  never direct child-run spawning.

Owner-CONFIRMED decisions (2026-07-11):
- **N8** Low-risk PlanVersions auto-approve under threshold (all nodes
  risk=low, node count ≤ config limit, budget within cap, no
  high/critical capability or permission bypass); everything else needs
  human review.
- **N9** Budget conflicts resolve by **explicit precedence declared at
  creation time**: each budget carrier (Task contract, Automation,
  WorkflowVersion) may declare a precedence level when its budget is
  set; the highest-precedence explicit budget wins. When no precedence
  is declared, fall back to strictest-of-all. Precedence and the
  resolved effective budget are recorded in the run contract snapshot.
- **N10** Conformance MVP = five checks (file-scope, subagent-attempt,
  cancel reliability, structured output, credential leakage); rest in a
  second wave.
- **N11** OpenCode joins as the third CLI runtime (phase C1.5) right after
  the C1 dispatch/declaration work, with a rendered per-run
  `opencode.json` enforcing `permission.task {"*": "deny"}` and tool
  permission lockdown. It must pass the N10 conformance MVP before the router may select it
  for non-low-risk tasks. No global preference is assigned; native Claude Code remains
  required for Claude Pro/Max subscription use. Full OMO stays out of the default chain
  (benchmark-only).

## Part VI — Open questions for owner

1. **N8 threshold parameters**: initial node-count limit (proposed 8)
   and the budget cap source (space-level default vs per-automation) —
   pick at B2 implementation time if not earlier.
