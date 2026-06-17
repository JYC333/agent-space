# TS Backend Target Architecture

> **Status: TARGET / forward-looking.** Unlike the other docs in
> `.agent/architecture/` (which describe *current* state), this document defines
> the **destination** of the Python→TypeScript backend re-platform: the domain
> layout and ownership model the TypeScript backend grows into as `backend/`
> (Python) is retired. It is authoritative for *direction*, not for what exists
> today. Current ownership is in
> [`TS_CONTROL_PLANE_OWNERSHIP.md`](TS_CONTROL_PLANE_OWNERSHIP.md); the phased path
> is in [`../reports/ts-backend-replatform-plan.md`](../reports/ts-backend-replatform-plan.md);
> the route/port inventory is in
> [`../reports/python-retirement-inventory.md`](../reports/python-retirement-inventory.md).
>
> This target preserves every standing invariant in
> [`../BOUNDARIES.md`](../BOUNDARIES.md) and the accepted decisions in
> [`../decisions/`](../decisions/). It does **not** invent a new product; it
> relocates authority for the existing one into TypeScript.

## 1. Strategic stance

1. **The existing `control-plane` is promoted to the full backend authority** over
   time. It is not replaced and not re-skeletoned. It already owns the two hardest
   domains end-to-end (providers/credentials, policy) plus run execution, memory
   apply, and a TS context builder.
2. **agent-space core owns the product.** Memory, context, policy, proposals,
   audit, activity, capabilities, workspace/sandbox governance, agents, runs,
   artifacts, automations, and UI-facing status are owned by the TS backend.
3. **Runtime systems are adapters, never the foundation.** Claude Code, Codex,
   Cursor, OpenCode, managed model APIs, and any future runtime are *runtime
   adapters* invoked by the `runs`/`runtimeAdapters` domains. They are replaceable
   and disableable (`.agent/BOUNDARIES.md` B38–B40).
4. **The Python module structure is not copied 1:1.** Several Python modules
   collapse into a smaller set of coherent domains (e.g. `me`/`home` → frontend
   aggregation; `credentials` + provider key handling → a credentials domain;
   `runtime_tool_bindings` + `runtime_adapters` + `runtimeHost`/`runtimeTools` →
   one `runtimeAdapters` domain).

## 2. Layered dependency direction (binding for the target)

```
HTTP request
  → gateway (routing, request context + validated identity, error envelope)
    → domain route handler
      → domain service            (business logic; the only layer with rules)
        → repository              (typed SQL over the owned tables)
          → db (pg pool + tx)
```

Cross-domain rules (enforced by review + tests, mirroring the Python invariants):

- **`domain service → policy service`** for any sensitive/consequential action.
  Policy is consulted, never inlined per-domain.
- **`domain service → proposal service`** for any *consequential change to governed
  state* (active memory, knowledge, agent config, policy, workspace patches,
  deployment). Domains create proposals; they do not mutate governed state directly.
- **`proposal apply → owning domain's registered applier`** via a TS
  `ProposalApplierRegistry` (the Python registry pattern is kept). Apply **fails
  closed** for any proposal type with no registered applier.
- **Repositories never cross domains.** A domain reads another domain's data
  through that domain's service/read-model, not by querying its tables.
- **Runtime adapters are leaves.** They are invoked *by* `runs`/`runtimeAdapters`
  and return results. They **must never** directly write `memory_entries`,
  `knowledge_items`, `policies`/`policy_decision_records`, real workspace files,
  or deployment state. All such effects flow back through proposals/services/policy.

### What must never be delegated to a runtime adapter (system-wide)

Grounded in `.agent/BOUNDARIES.md` B10/B13/B17–B19/B24/B38–B44:

- writing active **memory** or **knowledge** (only via proposal → approval → apply);
- making or recording **policy** decisions / audit;
- holding raw **credentials/secrets** (released only through broker channels,
  ADR 0010);
- mutating the **real workspace** (only sandbox/worktree → diff/artifacts →
  approval → apply);
- triggering **deployment** (only via approved proposal → deployer socket);
- deciding **identity / space membership** (auth domain only).

## 3. Domain catalog

Each domain below lists: **Responsibility · Key tables · Public API · Internal
service boundaries · Policy checks · Proposal/apply · Adapter prohibition · TS
seed.** "TS seed" names existing control-plane code that grows into the domain.
Table names are from `backend/app/models.py` (91 tables; Python/Alembic remains the
schema owner until Phase 10).

### 3.1 `auth`
- **Responsibility:** authenticate callers (cookie session, Google OAuth, and the
  feature-gated API-key surface), resolve `user_id`; issue/verify sessions.
  Session-cookie identity and Google OAuth now live in the TS control plane.
- **Key tables:** `users`, `auth_accounts`, `user_sessions`. The live path is
  session-cookie + Google OAuth (`UserSessionService` → `user_sessions`). DB-persisted
  **API keys are feature-gated and currently off** (`ApiKeyService` calls
  `feature_not_implemented("api_keys")` unless `API_KEYS_DB_PERSISTED`; there is no
  `api_keys` table) — treat as an optional capability, not a migration blocker.
- **Public API:** `/auth/introspect`, `/auth/keys`, `/auth/logout`,
  `/auth/google[/callback]`, `/auth/google-configured`.
- **Internal boundary:** an **auth middleware** in the gateway that produces a
  validated `{ userId }` on every request; downstream domains never re-parse tokens.
- **Policy checks:** authentication precedes policy; policy consumes the resolved
  actor identity.
- **Proposal/apply:** none.
- **Adapter prohibition:** adapters never resolve or assert identity.
- **TS seed:** `modules/auth`, `gateway/requestContext.ts`, and
  `gateway/internalAuth.ts`.

### 3.2 `spaces`
- **Responsibility:** the product isolation boundary (ADR 0001, B3–B5). Space
  lifecycle, per-space settings, execution planes, invitations.
- **Key tables:** `spaces`, `space_invitations`, `space_assistant_settings`,
  `execution_planes`.
- **Public API:** `/spaces`, `/spaces/{id}`, `/spaces/{id}/members`,
  `/spaces/{id}/invitations`, `/invitations/{token}/accept`, `/execution-planes`,
  `/agents/default-assistant/settings`.
- **Internal boundary:** Space-created hooks (TS registry) seed per-space defaults
  for `memory`, `knowledge`, `execution_planes` (mirrors Python
  `SpaceCreatedHookRegistry`).
- **Policy checks:** space creation/membership changes are sensitive actions.
- **Proposal/apply:** none typically.
- **Adapter prohibition:** adapters never create spaces or change membership.
- **TS seed:** `control-plane/src/modules/spaces`.

### 3.3 `users` / `memberships`
- **Responsibility:** person identity and space membership/role; the actor model.
  Separate from `agents` (B6–B7).
- **Key tables:** `users`, `space_memberships`, `actors`, `participation_records`.
- **Public API:** `/me`, `/me/spaces` (membership view); membership mutations via
  `spaces`.
- **Internal boundary:** `space_id` + role resolution consumed by every domain's
  authorization checks; `actors`/`participation_records` provide the actor-identity
  used in runs/audit.
- **Policy checks:** role changes are sensitive.
- **Proposal/apply:** none.
- **Adapter prohibition:** adapters act under a resolved actor, never define one.
- **TS seed:** `control-plane/src/modules/auth` and
  `control-plane/src/modules/spaces`.

### 3.4 `providers`
- **Responsibility:** model provider configuration, catalog, model lists,
  connection tests, per-task provider policy, provider resilience
  (pools/rotation/cooldown/fallback). A **ModelProvider** is distinct from a
  RuntimeAdapter.
- **Key tables:** `model_providers`, `provider_task_policies`,
  `model_provider_credentials` (secret material — co-owned with `credentials`).
- **Public API:** `/providers[...]`, `/providers/catalog`, `/{id}/models`,
  `/{id}/test`, `/chat`, `/litellm-providers`.
- **Internal boundary:** `providerInvocation` (text completion), `providerResilience`
  (pool/rotation), `providerCommandStore` (resolve effective provider). Consumed by
  `runtimeAdapters` (managed-API path) and `runtimeHost`.
- **Policy checks:** provider use can be gated by per-task/space provider policy
  (Hermes H3 is future).
- **Proposal/apply:** provider config changes are direct admin writes (not proposed)
  but are policy-gated.
- **Adapter prohibition:** adapters request a completion through the provider
  service; they never read raw provider keys.
- **TS seed:** `modules/providers/*` — **already TS-owned**, the reference domain.

### 3.5 `credentials`
- **Responsibility:** secret storage and release for both **provider API keys**
  (AES-256-GCM + `secret_ref`, disk master key) and **CLI login state** (per-vendor
  profiles). Channel isolation (ADR 0010, B45–B49). Credential audit.
- **Key tables:** `credentials`, `model_provider_credentials`,
  `cli_credential_events`, `automation_credential_grants`.
- **Public API:** `/credentials/cli/*` (profiles/detect/methods/login stream+input/
  status). Secret values are never returned (B49).
- **Internal boundary:** `cliCredentialBroker`, `cliLoginEngine` + per-vendor
  `cliLoginAdapters`, `secretRefCrypto`. The **only** component that decrypts/holds
  secrets; releases them solely into sanctioned broker channels.
- **Policy checks:** every grant/denial audited (B46); permission-bypass is
  policy-controlled (RUNTIME_ADAPTER_STANDARD).
- **Proposal/apply:** none (secrets never go through proposals).
- **Adapter prohibition:** **the** core prohibition — adapters receive a scoped
  profile dir/broker handle, never the backend HOME or `instance/secrets/` (B45,
  B47–B48). No ambient env-key fallback.
- **TS seed:** `modules/providers/cliCredentialBroker.ts`, `cliLoginEngine.ts`,
  `secretRefCrypto.ts` — **already TS-owned**.

### 3.6 `runtimeAdapters`
- **Responsibility:** first-class domain for *how a run executes* — the adapter
  registry, CLI tool install/status, adapter specs (credential mode, sandbox
  requirement, context target, invocation/parsing), and the in-process TS model
  runtime (`ts_agent_host`). Adapters are optional and disableable.
- **Key tables:** `runtime_tool_bindings`, `external_run_records`; (legacy
  `RuntimeAdapter` rows are read-only trace FKs per RUNTIME_ADAPTER_STANDARD).
- **Public API:** `/runtime-tools` (install/status), `/runtime-tool-bindings`
  (read). The old `/runtime-adapters` instance API stays **retired**.
- **Internal boundary:** `RuntimeAdapterSpec` + `adapter_type` define semantics;
  `runtimeHost` executes the managed/in-process turn; `runtimeTools` resolves
  binaries. Invoked **by** `runs`.
- **Policy checks:** sandbox level + permission-bypass enforced before invocation;
  `_SANDBOXED_ADAPTERS` always sandboxed (B13); high/critical paths fail closed.
- **Proposal/apply:** none directly.
- **Adapter prohibition:** this domain *defines the boundary* — adapters return
  results to `runs`; they do not write governed state.
- **TS seed:** `modules/runtimeHost/*`, `modules/runtimeTools/*`,
  `modules/runs/{managedApiAdapter,vendorCliAdapter}.ts` — **already TS**.

### 3.7 `agents`
- **Responsibility:** agent profiles and immutable versions; agent templates;
  default assistant; config changes via proposal. Agent ≠ User (ADR 0002).
- **Key tables:** `agents`, `agent_versions`, `agent_templates`,
  `agent_template_versions`.
- **Public API:** `/agents[...]`, `/agents/{id}/versions[...]`,
  `/agents/{id}/config-proposals`, `/agents/default-assistant`, `/agent-templates[...]`.
- **Internal boundary:** version immutability invariant; chat-turn orchestration
  lives at the agent edge but delegates context to `context` and execution to `runs`.
- **Policy checks:** config changes are sensitive; self-evolution gated (B20).
- **Proposal/apply:** `agent_config_update`, `prompt_update` (evolution) →
  registered appliers create new immutable versions.
- **Adapter prohibition:** adapters never alter agent config/version.
- **TS seed:** `modules/agents/*` (chat orchestration + `chatContextBuilder`).

### 3.8 `sessions`
- **Responsibility:** conversation sessions, messages, summaries; the chat
  transcript spine.
- **Key tables:** `sessions`, `messages`, `session_summaries`.
- **Public API:** `/sessions[...]`, `/sessions/{id}/messages`,
  `/sessions/{id}/reflect`.
- **Internal boundary:** `reflect` + `SessionCondenser.condense` (summary writes)
  are TS-native targets; latest-summary read already TS.
- **Policy checks:** standard space-scope auth.
- **Proposal/apply:** reflection may emit memory proposals (via `proposals`).
- **Adapter prohibition:** adapters never write sessions/messages directly outside a
  run's recorded turn.
- **TS seed:** `modules/sessions/*` — **already TS-owned**.

### 3.9 `runs`
- **Responsibility:** the server-authoritative execution record — create, read,
  execute, stop, finalize, evaluate; run steps/events; execution locks. Owns run
  lifecycle; invokes `runtimeAdapters`; consumes `context`, `policy`, `workspaces`,
  `credentials`.
- **Key tables:** `runs`, `run_steps`, `run_events`, `run_evaluations`,
  `run_finalizations`, `run_reflections`, `run_execution_locks`, `external_run_records`.
- **Public API:** `/runs`, `/runs/{id}`, `/{id}/status|steps|events|trace|activities|
  artifacts|proposals`, `/runs/preflight`, `/runs/{id}/execute`, `/stop`,
  `/finalize`, `/finalization(s)`, `/evaluation(s)`; `/agents/{id}/run[s]` (create).
- **Internal boundary:** orchestration (execute/stop) vs read-model vs finalization
  vs worker (`agent_run`). Run create is a service consumed by chat, tasks, jobs,
  automations.
- **Policy checks:** `policy.enforce` before execution (sandbox/credential/risk);
  `runtime.execute` and `runtime.use_credential` gated.
- **Proposal/apply:** runs *produce* proposals (memory/code_patch/etc.); they never
  apply them.
- **Adapter prohibition:** the adapter executes inside the run's sandbox and returns
  output; `runs` records evidence/artifacts. Adapter cannot persist runs or escape
  sandbox routing (B13).
- **TS seed:** `modules/runs/*` (execute/stop, jobWorker, adapters, materialization,
  evidence redaction) — **already TS for execution**; create/read/finalize are new TS.

### 3.10 `context`
- **Responsibility:** assemble runtime context — ContextBuilder (memory/source/
  workspace selection under budget), ContextSnapshotPopulator (persist what was
  used), ContextCompiler (render vendor files into the sandbox only), digests, and
  memory-injection logging. The "what the agent saw" authority.
- **Key tables:** `context_snapshots`, `context_snapshot_items`, `context_digests`
  (+ writes `memory_access_logs` for reads, in concert with `memory`).
- **Public API:** `/context/build`, `/context/digests/refresh` (mostly internal /
  run-driven).
- **Internal boundary:** consumed by `runs` (full run context) and `agents` (chat
  context). Reads `memory`/`knowledge`/`activity`/`workspaces`; **writes only
  context tables + access logs**.
- **Policy checks:** `context.render_for_runtime` gate; private-placement overlay;
  egress-context handling for personal-memory grants.
- **Proposal/apply:** none (context is derived, not governed state).
- **Adapter prohibition:** vendor context files are written to the **sandbox only**,
  never the real workspace (B14, ADR 0004). Adapters consume context; they don't
  build it.
- **TS seed:** `modules/context`, `modules/agents/chatContextBuilder.ts`, and
  `modules/memory/contextSnapshotRepository.ts`; replaces the Python
  `context.prepare` / `context.build` ports for chat and full-run execution.

### 3.11 `memory`
- **Responsibility:** scoped long-term memory; read with mandatory access logging;
  write only via proposal → approval → apply; personal-memory grants/egress;
  consolidation and quality/evolution loops.
- **Key tables:** `memory_entries`, `memory_relations`, `memory_access_logs`,
  `personal_memory_grants`, `personal_memory_grant_events`.
- **Public API:** `/memory` (list/get/search), `/memory` POST/PATCH/DELETE (proposal
  create), `/memory/consolidation/run`, `/personal-memory-grants[...]`.
- **Internal boundary:** read model + read-access logging (B11); proposal creation;
  apply (the three memory types); consolidation job; evolution jobs.
- **Policy checks:** memory apply gate; egress guard for cross-space/personal grants.
- **Proposal/apply:** `memory_create`/`update`/`archive` (TS appliers, gated);
  egress/workspace/agent-scope cases must gain TS appliers (currently fail closed).
- **Adapter prohibition:** **B10 cornerstone** — no adapter/runtime writes active
  memory. Ever. Only the proposal-apply path.
- **TS seed:** `modules/memory/*` (read, proposal, **apply**, provenance) — strong
  existing TS; remaining tails are quality/evolution jobs and the explicit
  egress/workspace/agent-scope apply exceptions.

### 3.12 `activity`
- **Responsibility:** activity-first capture — raw inputs enter as `activity_records`
  before any governed state (B9, B12, B24); review/archive; consolidate into
  proposals; provenance.
- **Key tables:** `activity_records`, `source_pointers`, `provenance_links`.
- **Public API:** `/activity` (create/upload/list/get/review/archive/consolidate/
  summary-runs), `/source-pointers`.
- **Internal boundary:** intake/runs/sessions feed activity; consolidation emits
  proposals. The single front door for raw capture.
- **Policy checks:** capture is low-risk; consolidation→memory is proposal-gated.
- **Proposal/apply:** activity → `memory_consolidation` → memory/knowledge proposals.
- **Adapter prohibition:** adapters may emit activity records as evidence, but
  promotion to memory/knowledge is always proposal-gated.
- **TS seed:** none yet (new TS domain, Phase 7); `streaming` relates to run-event
  capture.

### 3.13 `intake`
- **Responsibility:** source connectors/connections; intake items; evidence
  extraction + normalization (`ExtractionJob`, separate from the generic queue);
  evidence links; workspace intake profiles/bindings. Feeds `activity`/`knowledge`
  with provenance.
- **Key tables:** `source_connectors`, `source_connections`, `intake_items`,
  `extraction_jobs`, `extracted_evidence`, `evidence_links`, `source_snapshots`,
  `sources`, `workspace_intake_profiles`, `workspace_source_bindings`.
- **Public API:** `/intake/*` (connectors/connections/items/jobs/evidence/
  evidence-links/workspace-profiles/summary-runs).
- **Internal boundary:** extraction/normalization executor (today synchronous via
  service); target should run these through the generic TS `jobs` queue. Evidence →
  proposals into knowledge/memory.
- **Policy checks:** broad automated intake is gated until provenance is stable
  (current-focus non-goal).
- **Proposal/apply:** evidence → knowledge/memory proposals.
- **Adapter prohibition:** intake never writes knowledge/memory directly.
- **TS seed:** none yet (Phase 7). See
  [`INTAKE_EVIDENCE_FOUNDATION.md`](INTAKE_EVIDENCE_FOUNDATION.md).

### 3.14 `knowledge`
- **Responsibility:** knowledge items, relations, sources, entity links; notes and
  note collections; (spaced-repetition cards fold in here). Written only via
  proposals (B24); knowledge does not auto-enter memory/context.
- **Key tables:** `knowledge_items`, `knowledge_item_relations`,
  `knowledge_item_sources`, `entity_links`, `notes`, `note_collections`,
  `note_collection_items`, `cards`, `card_reviews`, `card_review_states`.
- **Public API:** `/knowledge/*`, `/notes/*`.
- **Internal boundary:** items/relations/sources; notes are user-authored (lighter
  gate than item proposals); cards reference knowledge.
- **Policy checks:** standard space-scope.
- **Proposal/apply:** `knowledge_create`/`update`/`archive`,
  `knowledge_relation_create`/`delete` → registered appliers.
- **Adapter prohibition:** no adapter writes knowledge directly.
- **TS seed:** none yet (Phase 7).

### 3.15 `proposals`
- **Responsibility:** the **universal governance gate**. Proposal lifecycle
  (create/list/get/accept/reject/expire/egress-approval); routes apply to the owning
  domain's registered applier; durable approval records.
- **Key tables:** `proposals`, `proposal_approvals`, `task_proposals`.
- **Public API:** `/proposals`, `/proposals/{id}`, `/{id}/accept|reject`,
  `/{id}/approvals/egress-granting-user`.
- **Internal boundary:** **`ProposalApplierRegistry`** (TS) — domains register
  appliers; the proposal service owns dispatch + the policy apply gate. **Fails
  closed** for unregistered types.
- **Policy checks:** `proposal-apply` policy gate before any applier runs;
  risk-level validation; incomplete-patch confirmation for `code_patch`.
- **Proposal/apply:** this *is* the apply authority; appliers live in owning domains.
- **Adapter prohibition:** adapters create proposals (as run output); they never
  accept/apply them.
- **TS seed:** `modules/proposals/*` (review/apply routes, apply service, registry)
  + `modules/policy/service.ts` apply gate; replaces `pythonProposalPorts`.

### 3.16 `artifacts`
- **Responsibility:** durable run/task outputs; storage paths in persistent storage
  (not sandbox); explicit export with egress guard (B-R3).
- **Key tables:** `artifacts`, `task_artifacts`.
- **Public API:** `/artifacts`, `/artifacts/{id}`, `/artifacts/{id}/export`.
- **Internal boundary:** artifact persistence (from run materialization) vs export.
  Paths point to `~/.aspace/artifacts/`, never sandbox dirs.
- **Policy checks:** export egress guard.
- **Proposal/apply:** none (artifacts are evidence, not governed state).
- **Adapter prohibition:** adapters write into the sandbox; `runs` materializes
  artifacts to persistent storage from there.
- **TS seed:** `modules/runs/materializationService.ts`,
  `modules/runs/evidenceRedaction.ts`.

### 3.17 `workspaces`
- **Responsibility:** workspace registry + profiles; project links; PathPolicy and
  WorkspaceManager; worktree/sandbox preparation/cleanup; workspace-console reads
  (policy-gated) and writes. Includes `projects` and `working_dirs`.
- **Key tables:** `workspaces`, `workspace_profiles`, `project_workspaces`,
  `projects`, `working_dirs`.
- **Public API:** `/workspaces[...]`, `/workspace-profiles/{id}`, `/projects[...]`,
  `/workspace-console/*` (console **session write** routes — create/run/stop — are
  currently stubs: `feature_not_implemented("workspace_console_sessions")`; reads are
  live and policy-gated).
- **Internal boundary:** `WorkspaceManager` + `PathPolicy` are the only file-access
  path (B17); worktree prep/cleanup feed `runs` sandboxes; console reads gated by
  `workspace.read` (B19A).
- **Policy checks:** `workspace.read`; system-core/external-root/restricted reads
  force durable audit; write flows require approval.
- **Proposal/apply:** workspace mutation via `code_patch` apply (diff → approval →
  patch), never direct (B19).
- **Adapter prohibition:** adapters access only their sandbox/worktree via the
  granted path; never arbitrary host paths (B17).
- **TS seed:** `modules/runs/ephemeralSandbox.ts` (run-scope); WorkspaceManager/
  PathPolicy are new TS (Phase 9).

### 3.18 `jobs`
- **Responsibility:** the generic durable queue + worker registry + stuck-job
  reclaim. One queue service; domains register handlers (the Python registry pattern
  kept).
- **Key tables:** `jobs`, `job_events`.
- **Public API:** `/jobs`, `/jobs/handlers`, `/jobs/{id}[/events]`, `/{id}/cancel`.
- **Internal boundary:** `QueueService` + `JobHandlerRegistry`; the TS `agent_run`
  worker already exists; `memory_consolidation`, `daily_capture_report`, and intake
  extraction/normalization become registered TS handlers.
- **Policy checks:** job enqueue inherits the enqueuer's authorization.
- **Proposal/apply:** jobs may drive runs that produce proposals.
- **Adapter prohibition:** jobs invoke domain services; adapters are reached only
  through `runs`.
- **TS seed:** `modules/runs/{jobWorker,jobRepository,workerRuntime}.ts` — generalize
  out of `runs` into a shared `jobs` service.

### 3.19 `automations`
- **Responsibility:** user-defined scheduled/triggered automations; automation runs;
  scheduler; daily-capture-report scheduler; trigger budgets/cooldowns (future
  Always-On governance).
- **Key tables:** `automations`, `automation_runs`, `automation_credential_grants`,
  `daily_capture_report_settings`.
- **Public API:** `/spaces/{id}/automations[...]`, `/{id}/fire`,
  `/daily-capture-report/*`.
- **Internal boundary:** a TS scheduler (mirrors Python `SchedulerRegistry`) that
  scans + enqueues `jobs`; `policy_preflight` before firing.
- **Policy checks:** automation firing is policy-gated; credential grants audited.
- **Proposal/apply:** automation outputs follow normal proposal gating.
- **Adapter prohibition:** automations enqueue jobs/runs; they do not invoke adapters
  directly.
- **TS seed:** `modules/notifications/*` (egress); scheduler is new TS (Phase 8).

### 3.20 `policy`
- **Responsibility:** canonical action registry; hard-invariant guard; rule engine;
  decision orchestration; durable audit (`policy_decision_records`). The single
  decision authority every domain consults.
- **Key tables:** `policies`, `policy_decision_records`.
- **Public API:** internal enforce + proposal-apply ports (no broad public surface);
  policy management may surface admin routes.
- **Internal boundary:** `enforce(action, …)` and `enforceProposalApply(…)`;
  fail-closed audit-persist (a blocked action whose audit can't persist returns 500).
- **Policy checks:** *is* the policy service.
- **Proposal/apply:** gates every applier; `policy_change` proposals mutate `policies`.
- **Adapter prohibition:** adapters never make or read policy decisions.
- **TS seed:** `modules/policy/*` — **already a full TS port**; the model domain.

### 3.21 `capabilities`
- **Responsibility:** capability lifecycle (draft → proposed → testing → approval →
  enabled, B20–B21); code+manifest+prompts+tests; overlays; validation recipes.
- **Key tables:** `capability_versions`, `capability_overlays`, `validation_recipes`.
- **Public API:** `/capabilities[...]`, `/capabilities/reload`; catalog reads via
  `catalog`.
- **Internal boundary:** registry loads `catalog/capabilities/*`; lifecycle changes
  go through capability proposals.
- **Policy checks:** capability enable/self-evolution gated.
- **Proposal/apply:** capability proposals → appliers.
- **Adapter prohibition:** adapters use capabilities; they don't define/enable them.
- **TS seed:** `modules/catalog/*` (read); lifecycle is new TS.

### 3.22 `deployment`
- **Responsibility:** host-level deploy actions via the deployer Unix socket only
  (B41–B44); deployment jobs; allowlisted job types.
- **Key tables:** none yet — deployment **job create/get are stubs**
  (`feature_not_implemented("deployment_jobs")`); the working pieces are the
  deployer host process (`deployer/deployer.py`) and `DeployerClient` socket caller.
  Decide the persistence model (likely the generic `jobs` table with allowlisted
  deployment job types) when this domain is actually built.
- **Public API:** `/deployments/jobs[...]` (currently mostly stubbed).
- **Internal boundary:** TS deployer **socket client**; app container never
  self-restarts; only allowlisted job types (`rebuild_agent_space`,
  `restart_agent_space`, `health_check`).
- **Policy checks:** deployment requires a human-approved proposal (B43).
- **Proposal/apply:** deploy proposal → approval → deployer job.
- **Adapter prohibition:** adapters/agent code cannot trigger deployment.
- **TS seed:** none yet (Phase 9); `deployer/` (Python) stays as a separate host
  process unless separately re-platformed — confirm.

### 3.23 `frontend aggregation / home summary`
- **Responsibility:** read-only cross-domain aggregation for UI surfaces (home,
  today, me, server status). No tables of its own; composes domain read-models.
- **Key tables:** none (reads across domains).
- **Public API:** `/home/summary`, `/me/summary|timeline|tasks|pending`, server
  status descriptors.
- **Internal boundary:** calls domain services (never their repositories). The only
  domain allowed to fan out across domains by design.
- **Policy checks:** inherits per-domain read auth.
- **Proposal/apply:** none.
- **Adapter prohibition:** N/A (read aggregation).
- **TS seed:** `modules/frontendSupport/*` (today forwards to Python; becomes native
  aggregation), `modules/system/*` (status/features).

### 3.24 Additional existing domains (not in the required list, but real)

- **`tasks`** — product Tasks/Boards (`tasks`, `task_runs`, `task_artifacts`,
  `task_proposals`, `task_dependencies`, `task_evaluations`, `boards`,
  `board_columns`). A first-class domain that drives `runs`; Task ≠ Job
  (current-focus non-goal forbids collapsing them). Migrate as its own domain
  (Phase 7-adjacent).
- **`evolution`** — self-evolution targets/signals (`evolution_targets`,
  `evolution_signals`). **Future/deferred**; `prompt_update` applier stays inert
  until evaluation gates + deployment job persistence exist.

## 4. Domain → seed/maturity map (at re-platform start)

| Maturity | Domains |
|---|---|
| **TS-native today (keep & extend)** | providers, credentials, runtimeAdapters (runtimeHost/runtimeTools), policy, sessions; memory (read/proposal/apply); runs (execute/stop/worker) |
| **TS edge, Python core (cut the port)** | proposals, agents/chat, context, memory-context, frontend aggregation, streaming |
| **Python-only (build TS)** | auth, spaces, users/memberships, activity, intake, knowledge, artifacts, workspaces, jobs (generalize), automations, capabilities, deployment, tasks |
| **Deferred (future feature)** | evolution; full context engine; channel adapters; self-hosted TS agent loop + tool scheduler + MCP; managed-API-with-tools; CLI sandbox scope ladder |

## 5. Invariants this target must not regress

- B4/B5 space isolation; `space_id` required on every entity; ContextBuilder refuses
  context without explicit `space_id`.
- B10/B24 proposal-gated writes to memory/knowledge; raw input via activity first.
- B11 every memory read logged.
- B13/B17–B19 sandbox routing, PathPolicy, no direct workspace mutation.
- B38–B40 runtime-agnostic core; adapters disableable; no vendor as source of truth.
- ADR 0010 credential channel isolation; no ambient provider key in subprocess env.
- B31 UUID PKs preserved (no integer PKs) for sync compatibility.
- Fail-closed everywhere: unknown proposal type, missing applier, unpersistable
  policy audit, high/critical sandbox path — never silently downgrade.
