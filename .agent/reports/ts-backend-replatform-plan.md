# TS Backend Re-platform Plan

> **Status:** temporary report (per `.agent/INDEX.md` §7). Not source of truth.
> Produced 2026-06-15. This is an **implementation plan, not code**. It sequences
> the controlled retirement of the Python backend (`backend/`) and the promotion of
> the existing TypeScript control plane into the full backend authority.
>
> Read with: [`python-retirement-inventory.md`](python-retirement-inventory.md)
> (what Python still owns), [`ts-reuse-in-replatform.md`](ts-reuse-in-replatform.md)
> (what TS to keep/cut), and
> [`../architecture/TS_BACKEND_TARGET.md`](../architecture/TS_BACKEND_TARGET.md)
> (the destination). Binding migration rules remain
> [`../architecture/TS_MIGRATION_STRATEGY.md`](../architecture/TS_MIGRATION_STRATEGY.md).

## Strategic stance (applies to every phase)

- **Freeze Python feature development.** New product work targets TS. Python gets
  bug/security fixes only.
- **Promote, don't rewrite.** The existing control plane becomes the full authority
  incrementally. No from-scratch backend.
- **Python fallback is not a long-term architecture.** It is a temporary bridge
  (`control-plane/src/pythonFallback/proxy.ts`), deleted **incrementally** as each
  domain migrates and fully gone by Phase 10.
- **Python stays only as reference** (behavior, route/domain inventory, schema
  history, invariants/tests) until each domain is TS-native.
- **Vertical slices over skeletons.** Prefer proving one complete flow end-to-end
  (request → service → repo → DB, with policy/proposal where due) over broad
  half-built domains. One command, one authority (Strategy Rule 1) holds throughout.

## Execution posture: no production yet, fast iteration

This plan is executed **solo, with no running production deployment, during rapid
iteration.** That changes what is worth doing. Most of the original migration's
safety apparatus (`*Authority` env switches kept as rollback levers, the fallback
proxy as a long-lived dual path, shadow-compare, TS-vs-Python parity fixtures) exists
to migrate a *live* system without downtime. Without prod, that machinery is mostly
cost, not safety — and the **end state deletes all of it anyway**.

So the per-phase **Rollback** and **Tests** entries below should be read through this
lens:

- **Rollback = fix-forward / `git revert`.** We do **not** maintain a Python path as a
  standing rollback lever. The escape hatch is the previous git commit (and, near
  Phase 10, a tagged pre-deletion release), not an env flip. Where a phase mentions
  `XAuthority=python`, treat it as a *transitional bridge while the slice is in
  progress*, not a button to keep around.
- **Parity → tests + dogfooding.** Replace "shadow-compare" and "TS-vs-Python parity
  fixtures" with TS behavioral tests plus real dogfooding. Keep **product-invariant**
  tests (proposal gating, credential isolation, sandbox routing, fail-closed) — those
  are correctness, not migration safety, and never get relaxed.
- **The fallback is a "not-migrated-yet" bridge, not a safety net.** It keeps the app
  working while you migrate domain-by-domain (a development convenience). Delete it
  aggressively per-domain as routes go TS; don't gate its removal on a full
  dogfooding cycle.

### Authority switches: collapse them as you go (don't carry them to the end)

At plan start, `control-plane/src/config.ts` carried **10 `*Authority` switches**
(providers, providers credentials, runs, policy, proposals, sessions, chat turn,
context, memory, memory apply) plus provider shadow-compare, and the Python side
carried `authority.py` fail-closed guards. These are leftover
incremental-migration scaffolding. **Clean them up as part of this work —
carrying them into the end state contradicts the goal.** Rules:

1. **Distinguish two kinds of flag.** *Migration authority switches* and
   provider shadow-compare scaffolding → **delete**. *Real product feature flags*
   (`enableNotificationWebhookEgress`, webhook allowlist, retention toggles) → **keep**.
   `config.ts` mixes both; separate them before deleting.
2. **Collapse a switch as the closing step of its domain's phase** — not in a
   separate big-bang. "Collapse" = remove the `if (config.XAuthority !== "ts") return;`
   guard so the module registers unconditionally, delete the env var + DAG validation
   + diagnostic in `config.ts`, drop the compose/ops passthrough, and delete the now
   dead Python route + `authority.py` guard.
3. **Already-TS-final domains can collapse early.** `providers`, `credentials`,
   `policy`, `sessions` depend only on identity (no `python*Ports` tail), so their
   switches can be removed as soon as you're not going to toggle them off — realistically
   right after Phase 2/3.
4. **Trap: deleting a switch ≠ removing the Python port.** The switch decides whether
   the TS module *claims the route*; a `python*Ports` client decides whether it *calls
   back into Python* mid-request. They are independent. Phase 5 collapsed
   `memoryAuthority` only after deleting the stage6/chat ports and retiring
   `context.prepare`; keep applying that order to later phases.
5. **Each switch touched in:** `config.ts` (parse fn / field / `validateConfigSemantics`
   / `KNOWN_ENV_KEYS` / diagnostic / `describeConfig`) → module `routes.ts` guard →
   `ops/env/.env*.example` → compose passthrough → `local-compose.sh` DB grants →
   Python `authority.py` guard + dead route.

Each phase's **completion criteria** below includes collapsing the switches it owns,
so the switch count trends to zero and is **zero by Phase 10** (matching the
`config.ts` direction in `TS_BACKEND_TARGET.md`).

### Sequencing logic

The plan follows the **authority-switch dependency DAG** already encoded in
`control-plane/src/config.ts`, then extends past where the current migration
stopped. The deepest unmet dependency is **identity** — so after the foundation
(Phase 1), auth comes first (Phase 2). Phases 3–9 each cut one Python internal port
or Python-only domain. Phase 10 removes Python.

```
0 freeze/inventory ─ 1 DB+migration foundation ─ 2 auth/spaces/identity
                                                      │
        ┌─────────────────────────────────────────────┘
        3 providers/credentials/runtimeAdapters (mostly done — harden)
        4 runs vertical slice (create/read/finalize; cut execute's Python read dep)
        5 context vertical slice (cut context.prepare / stage6 ports)
        6 artifacts + proposals (per-type appliers; fail closed)
        7 activity / intake / knowledge / tasks
        8 jobs / schedulers / automations
        9 workspaces / sandbox / deployment
       10 remove Python
```

---

## Phase 0 — Freeze and inventory

- **Goal:** stop the bleeding and define "done." No new Python features; a
  fallback-disabled verification mode; a written Python deletion checklist.
- **Domains/files touched:** docs only — this report set;
  `control-plane/src/config.ts` (`enablePythonFallbackProxy` already exists as the
  off-switch); `ops/env/.env*.example` (add a fallback-disabled test profile).
- **Existing TS to reuse:** `enablePythonFallbackProxy=false` already returns
  `503 python_fallback_proxy_disabled` (`pythonFallback/proxy.ts`) — this is the
  verification lever.
- **Python reference:** `backend/app/modules/registry.py` (the authoritative module
  list), `models.py` (91 tables), this inventory.
- **Blockers:** none.
- **Tests required:** a CI job that boots control-plane with
  `enablePythonFallbackProxy=false` and asserts which routes 503 (i.e. still
  Python-dependent). This becomes the live "Python deletion checklist" — it shrinks
  every phase.
- **Completion criteria:** (1) freeze recorded in `current-focus.md`; (2)
  fallback-disabled CI profile runs and lists Python-dependent routes; (3) deletion
  checklist published (the set of routes/ports that must reach 0).
- **Rollback:** trivial — docs/CI only; flip the profile off.

---

## Phase 1 — TS DB and migration foundation

- **Goal:** TS can own and evolve the PostgreSQL schema. TS migration runner,
  baseline of the current schema, migration lock, transaction helper, drift check,
  empty-DB CI migration test.
- **Domains/files touched:** new `control-plane/src/db/` additions (migration
  runner, `tx` helper on top of `db/pool.ts`), a `control-plane/migrations/`
  directory; `ops/compose/*` and `ops/scripts/lib/local-compose.sh` (later wiring,
  read-only this phase).
- **Existing TS to reuse:** `db/pool.ts` (single `pg` Pool); `config.ts`
  `databaseUrl` validation; the least-privilege role provisioning already in
  `ops/scripts/lib/local-compose.sh`.
- **Python reference:** `backend/migrations/versions/0001_canonical_initial_schema.py`
  (the single consolidated baseline — copy its schema as the TS baseline),
  `backend/migrations/env.py`, `init_db` in `backend/app/db.py`.
- **Blockers:** Python/Alembic must remain the *runtime* schema owner until this is
  proven; the TS baseline must byte-for-byte match what Alembic produces.
- **Tests required:** empty DB → TS migrations → schema equals Alembic-produced
  schema (drift check, both directions); transaction-helper rollback test;
  migration-lock contention test.
- **Completion criteria:** TS runner reproduces the canonical schema on an empty DB;
  drift check is green against a live Alembic DB; CI runs the empty-DB test. **Alembic
  still runs in prod** (parity, not cutover).
- **Rollback:** TS runner is additive and not yet authoritative; disable it — Alembic
  remains the owner. Zero production impact.

---

## Phase 2 — Auth / spaces / identity

> **Status 2026-06-15:** implemented in the TS control plane. Session-cookie
> identity, Google OAuth login/callback/config, `/me`, `/me/spaces`, logout,
> space create/read/member/invitation routes, invitation accept, and deterministic
> space-created defaults are TS-owned. DB-persisted API keys remain a disabled
> canonical-schema gap; the TS API-key routes return the same feature-gated 501
> response instead of falling through to Python.

- **Goal:** TS owns identity natively. Remove the universal Python dependency
  (`/auth/introspect`) that blocks every other domain from standing alone.
- **Domains/files touched:** new `modules/auth/`, `modules/spaces/`,
  `modules/users/`; extend `gateway/requestContext.ts` to carry validated identity;
  retire `modules/providers/identity.ts`.
- **Existing TS to reuse:** `gateway/internalAuth.ts` (token compare),
  `requestContext.ts`, `@agent-space/protocol` `auth.ts` (introspection contract),
  `db/pool.ts`.
- **Python reference:** `backend/app/auth/api.py` (API keys, Google OAuth, logout,
  introspect, `/me`), `backend/app/spaces/api.py`, `backend/app/me/api.py`,
  `feature_gates.API_KEYS_DB_PERSISTED`, `bootstrap.py` (default user/space seeding).
- **Blockers:** (1) the live auth path is **session-cookie + Google OAuth**
  (`UserSessionService` → `user_sessions`); DB-persisted API keys are feature-gated
  and currently off (`feature_not_implemented("api_keys")`, no `api_keys` table) — so
  port session/OAuth first and treat API keys as optional; (2) the OAuth callback is
  currently proxied verbatim (OAuth-safe) — TS must replicate redirect/cookie
  semantics exactly; (3) session cookie format parity.
- **Tests required:** introspection parity (same `space_id`/`user_id` resolution as
  Python for cookie sessions, plus the canonical feature-gated API-key response);
  OAuth login round-trip; `/me`/`/me/spaces` parity; a contract test that every TS
  module reads identity from the gateway, not a Python call.
- **Completion criteria:** all TS modules resolve identity through the TS auth
  middleware; `providers/identity.ts` deleted; auth/spaces/me routes TS-owned;
  fallback-disabled CI shows auth routes no longer 503. **Switch cleanup:** auth has
  no legacy switch to collapse, but landing native identity is what *unblocks*
  collapsing the early-TS switches (providers/credentials/policy/sessions) in Phase 3.
- **Rollback:** fix-forward / `git revert` to the previous commit. If identity parity
  is shaky, keep the `identity.ts` Python-introspection bridge in place a little
  longer (it is a transitional bridge, not a maintained dual path) and delete it once
  parity holds — do not ship a permanent `authAuthority=python` lever.

---

## Phase 3 — Providers / credentials / runtime adapters (harden + formalize)

- **Status:** completed. `modules/runtimeAdapters/` now owns the TS
  `RuntimeAdapterSpec` catalog; provider shadow compare and `shadow.ts` were
  deleted; providers/credentials, policy, and public sessions are unconditional
  TS authorities; the matching compose/config/Python guards were collapsed.
- **Goal:** finish the already-strong domain: keep TS provider/credential logic,
  cleanly separate **ModelProvider** from **RuntimeAdapter**, make `runtimeAdapters`
  a first-class domain, keep external CLIs as adapters only.
- **Domains/files touched:** `modules/providers/*`, `modules/runtimeHost/*`,
  `modules/runtimeTools/*`; new `modules/runtimeAdapters/` boundary that owns
  `RuntimeAdapterSpec`/`adapter_type` semantics and bindings; delete
  `modules/providers/shadow.ts`.
- **Existing TS to reuse:** nearly everything — `providerInvocation`,
  `providerResilience`, `secretRefCrypto`, `cliCredentialBroker`, `cliLoginEngine` +
  `cliLoginAdapters/*`, usage probes, `runtimeHost`, `runtimeTools`.
- **Python reference:** `backend/app/runtimes/` (`base.py`, `registry.py`,
  `adapter_metadata.py`, `specs.py`, `adapters/*`), `RUNTIME_ADAPTER_STANDARD.md`,
  `runtime_tool_bindings/api.py`, ADR 0010.
- **Blockers:** confirm `RuntimeAdapter` legacy rows are truly read-only trace FKs
  (RUNTIME_ADAPTER_STANDARD says so) before removing any write path; usage-probe
  parity (Claude Code quota is cached-only).
- **Tests required:** `test_runtime_provider_separation` parity; credential-channel
  isolation invariant (no key in subprocess env); secret_ref decrypt round-trip.
  (Drop provider shadow compare and its drift test under the no-prod posture; rely on
  the invariant tests + dogfooding.)
- **Completion criteria:** ModelProvider and RuntimeAdapter are distinct domains in
  TS; `shadow.ts` deleted. **Switch cleanup:** provider read/credential, policy,
  and public session authorities are unconditional TS foundations; their switches
  and Python switch guards are gone. Fewer than six `*Authority` switches remain
  after this phase.
- **Rollback:** fix-forward / `git revert`. These domains are the most proven in TS;
  shadow compare is dropped rather than re-enabled.

---

## Phase 4 — Runs vertical slice

> **Status 2026-06-16:** completed for the Phase 4 scope. TS now owns run creation via
> agent subresources and TS-context chat turns, top-level run list/detail/status/
> trace, execute/stop, deterministic post-run evaluation/finalization, and
> `agent_run` worker dispatch. `runsAuthority` and
> `CONTROL_PLANE_RUNS_AUTHORITY` were collapsed.
> Remaining run-adjacent work is intentionally in later phases: artifact/proposal
> child surfaces and appliers (Phase 6), task bridges (Phase 7), generic
> jobs/schedulers (Phase 8), and workspace/path-policy surfaces (Phase 9).

- **Goal:** TS owns run create/read/finalization (not just execute/stop). Remove the
  execute path's dependency on Python read-responses and run-create ports.
- **Domains/files touched:** `modules/runs/*` (add create/read-model/finalize
  services beside the existing executor); `modules/streaming/*` (already owns the
  event edge — point it at TS reads); cut TS-context chat's Python `create-run`
  usage.
- **Existing TS to reuse:** `modules/runs/{orchestrationService,jobWorker,
  managedApiAdapter,vendorCliAdapter,ephemeralSandbox,materializationService,
  evidenceRedaction,processRegistry,repository}.ts`.
- **Python reference:** `backend/app/runs/{api.py,run_service.py,read_model.py,
  internal_api.py,adapter_resolution.py,runtime_bridge.py}`, `runs/lifecycle_hooks.py`,
  `RunFinalizedHookRegistry`, the `finalization.finalize` port operation.
- **Blockers:** none remaining for the Phase 4 scope. The stable TS run-create
  path exists for later consumers. Task-owned finalization bridge behavior is
  intentionally tracked with the tasks domain in Phase 7.
- **Tests required:** `test_run_execution_workflow` parity; run read-model contract
  tests; finalize idempotency; SSE edge reads from TS without gaps. Task bridge
  coverage belongs to Phase 7.
- **Completion criteria:** run create/read/finalize TS-owned; execute no longer
  reads Python responses for run state; `/runs/*` top-level read/finalization
  surfaces are off the fallback. The run authority switch is collapsed; the
  remaining Python tails are explicit later-phase contexts
  (artifacts/proposals/tasks/workspaces/jobs).
- **Rollback:** fix-forward / `git revert`. While the slice is in progress the
  unmigrated read/finalize paths still fall through the bridge to Python, so a partial
  landing stays working; that bridge is removed when the switch collapses.

---

## Phase 5 — Context vertical slice

> **Status 2026-06-16:** completed for the Phase 5 scope. Chat context candidate
> collection is native TS (`control-plane/src/modules/context/`:
> `ChatContextCandidateCollector` + `PgChatCandidateRepository`) and the stale
> chat builder comment that still referenced Python `context-candidates` was
> fixed. Full-run `context.prepare` is also native TS via `ContextPrepareService`,
> `PgRunContextRepository`, and `ContextCompiler`: it populates
> `context_snapshots`, logs `context_injection` memory reads, handles digest
> bundles, selects existing linked evidence with `used_in_context` audit links,
> handles personal-memory grant summaries, and renders vendor runtime files to
> the sandbox only (B14). Memory read/proposal-create routes are fixed
> TS-owned. `chatTurnAuthority`, `contextAuthority`, and `memoryAuthority` were
> collapsed from config/compose/ops; Python public chat/memory and the retired
> combined chat `prepare-run` path now fail closed by default. `pythonContextPorts.ts`
> remains only for later-phase artifact/proposal/workspace/finalization ports;
> TS run execution no longer calls its `context.prepare` operation.

- **Goal:** TS owns context assembly. Cut the two biggest port tails:
  `/internal/runs-context context.prepare` and `/internal/stage6-context`.
- **Domains/files touched:** new `modules/context/` (ContextBuilder,
  ContextSnapshotPopulator, ContextCompiler); extend `modules/memory/*` (read +
  proposal-create natively, memory-injection logging); stop using
  `modules/runs/pythonContextPorts.ts` for `context.prepare`; delete
  `modules/memory/pythonStage6Ports.ts`, `modules/agents/pythonChatContextPorts.ts`,
  and `modules/agents/pythonChatTurnPrep.ts`.
- **Existing TS to reuse:** `modules/agents/chatContextBuilder.ts` (real TS context
  builder for chat — generalize it), `modules/memory/contextSnapshotRepository.ts`,
  `modules/memory/memoryReadAuth.ts`.
- **Python reference:** `backend/app/memory/context_builder.py`,
  `memory/context_api.py` (`/context/build`, digests), the `context.prepare` and
  `context.build`/`memory.read`/`memory.proposal_create` port handlers,
  `MEMORY_CONTEXT_RUNTIME.md`, ADR 0004 (vendor files to sandbox only).
- **Blockers:** budgeting/dedup must match the chat builder *and* the full-run
  builder; ContextCompiler must write vendor files to the **sandbox only** (B14);
  memory access logging (B11) must fire on every read; private-placement overlay +
  personal-grant egress-context handling currently fail closed in TS memory apply.
- **Tests required:** context snapshot parity (same selected items/budget as Python);
  vendor-file-to-sandbox-only invariant; memory-read-trace written on every read;
  digest refresh parity.
- **Completion criteria:** `context.prepare`/stage6/chat prepare ports unused or
  deleted as appropriate; run + chat both use the TS context domain. **Switch
  cleanup:** collapse `contextAuthority`, `chatTurnAuthority`, and `memoryAuthority`
  now that their Python paths are closed.
- **Rollback:** fix-forward / `git revert`. This is the highest-logic slice (budget/
  dedup parity, vendor-file-to-sandbox, read logging) — lean on the invariant tests +
  dogfooding rather than a Python comparison path.

---

## Phase 6 — Artifacts and proposals

> **Status 2026-06-16:** completed for the Phase 6 control-plane boundary. TS now
> owns `GET /api/v1/artifacts`, `GET /api/v1/artifacts/{id}`, and
> `GET /api/v1/artifacts/{id}/export`; file-backed export resolves only under
> managed artifact storage and rejects sandbox/path escapes. Proposal
> list/get/accept/reject/egress-approval routes are TS-owned, and accept runs the
> TS `proposal.apply` policy gate before dispatching through the TS
> `ProposalApplierRegistry`. The registry currently registers
> `memory_create`, `memory_update`, and `memory_archive`; unregistered types
> fail closed. `modules/proposals/pythonProposalPorts.ts`,
> `modules/memory/memoryAcceptDispatch.ts`, `proposalsAuthority`, and
> `memoryApplyAuthority` were deleted from the active TS/ops path. Non-memory
> target appliers (`code_patch`, Knowledge, tasks, agent config, policy-change
> mutations, and similar owning-domain writes) remain deferred to their owning
> migration phases and fail closed until registered.

- **Goal:** TS artifact persistence/export/egress guard; a TS
  `ProposalApplierRegistry` with per-type appliers; **fail closed** for unsupported
  types. Cut `/internal/proposals-context`.
- **Domains/files touched:** new `modules/artifacts/`; extend `modules/proposals/*`
  with a TS applier registry; move memory/non-memory appliers into their owning
  modules; delete `modules/proposals/pythonProposalPorts.ts` and the Python
  `memory.apply_gate` dependency.
- **Existing TS to reuse:** `modules/runs/materializationService.ts`,
  `evidenceRedaction.ts`; `modules/memory/{memoryApplyRepository,
  memoryApplyProvenance}.ts` (apply the 3 memory types); `modules/policy/service.ts`
  (`enforceProposalApply`).
- **Python reference:** `backend/app/proposals/{api.py,internal_api.py,applier_registry.py}`,
  `proposals/ProposalApplyService`; all `*/proposal_appliers.py`
  (memory: memory_create/update/archive, policy_change, code_patch, follow_up_task,
  egress_review; agents: agent_config_update; knowledge: knowledge_*; evolution:
  prompt_update); `artifacts/api.py`; B-R3 export rules.
- **Blockers:** `code_patch` apply needs workspace patch (Phase 9) — gate it until
  then (keep failing closed); egress/workspace/agent-scope memory cases must get TS
  appliers or stay explicitly Python-retained; the apply policy gate must run before
  every applier.
- **Tests required:** `test_proposal_approval_boundary`, `test_memory_proposal_boundary`,
  `test_general_proposal_api` parity; **fail-closed test for an unregistered proposal
  type**; artifact export egress-guard test; apply-gate-before-applier test.
- **Completion criteria:** TS applier registry owns dispatch; registered memory
  types apply in TS; non-memory target appliers are explicit owning-domain
  follow-ups and fail closed until registered; `pythonProposalPorts` deleted;
  artifacts TS-owned; unsupported types provably fail closed. **Switch cleanup:**
  collapse `proposalsAuthority` and `memoryApplyAuthority`; migration authority
  switches are now zero in the active control-plane config.
- **Rollback:** fix-forward / `git revert`. **Never** relax fail-closed: an
  unregistered proposal type must error, not silently no-op — that is a product
  invariant, not migration safety.

---

## Phase 7 — Activity / intake / knowledge (+ tasks)

- **Goal:** TS owns the capture→evidence→knowledge/memory provenance chain and the
  activity inbox; tasks become a TS domain.
- **Domains/files touched:** new `modules/activity/`, `modules/intake/`,
  `modules/knowledge/`, `modules/tasks/`.
- **Existing TS to reuse:** `modules/streaming/*` (run-event capture relates to
  activity); the proposal applier registry from Phase 6 (knowledge/memory appliers).
- **Python reference:** `backend/app/activity/*` (capture/review/consolidate),
  `backend/app/intake/*` (`service.py` extraction/normalization, `ports.py`),
  `backend/app/knowledge/*`, `backend/app/tasks/*`, `source_pointers/*`,
  `INTAKE_EVIDENCE_FOUNDATION.md`, B9/B12/B24, current-focus non-goal (Task ≠ Job).
- **Blockers:** intake extraction/normalization currently runs synchronously via the
  service — porting cleanly wants the TS `jobs` queue (Phase 8), so either sequence
  intake after Phase 8 or keep synchronous execution initially; activity → memory
  consolidation depends on Phase 5/6; tasks must not collapse into jobs.
- **Tests required:** `test_activity_to_memory_workflow` parity; capture-creates-
  activity-first invariant (B24); knowledge-not-auto-into-memory invariant; intake
  evidence provenance; task-board model parity (`TASK_BOARD_MODEL.md`).
- **Completion criteria:** activity/intake/knowledge/tasks routes TS-owned;
  consolidation + knowledge appliers run in TS; provenance chain intact.
- **Implementation status 2026-06-16:** complete. Modules migrated in
  `control-plane/src/modules/activity/`, `intake/`, `knowledge/`, and `tasks/`;
  route ownership covered by fallback-disabled checklist and Phase 7 invariants.
  `follow_up_task` proposal applier registered in `tasks/proposalApplier.ts` and
  wired into `proposals/applierRegistry.ts`. `mark_reviewed` now sets
  `consolidation_status = 'skipped'` to match Python parity (Phase 7 consolidation
  job deferred to Phase 8). Intake extraction workers intentionally deferred to
  Phase 8 queue ownership; Phase 7 keeps extraction audit rows and candidate-only
  evidence/provenance behavior in TS. Pre-existing `boundaries.test.ts` failure
  (`context/repository.ts`, `proposals/applyService.ts` import `pg` directly) is
  a Phase 5/6 carry-over tracked separately.
- **Rollback:** fix-forward / `git revert`. These are leaf domains, so an
  unmigrated one simply keeps falling through the bridge to Python while you finish
  it — no dual-path maintenance, no per-domain rollback switch.

---

## Phase 8 — Jobs / schedulers / automations

> **Status 2026-06-17:** completed for the Phase 8 scope, including a post-audit
> parity pass against the deleted Python jobs/scheduler/automation/daily-report/
> backup files. The control plane now
> owns a generic TS job queue (`control-plane/src/modules/jobs/`), unified worker
> registry (`agent_run`, `memory_consolidation`, `daily_capture_report`),
> in-process schedulers (daily capture report, automation, memory access log
> retention, intake extraction polling, backup), and TS-owned routes for
> `/jobs`, `/spaces/{id}/automations`, `/daily-capture-report/*`, and
> `/system/backups`. Python `app.jobs`, `app.scheduler`, job/automation/daily-
> report schedulers, and backup scheduler startup were removed from the Python
> lifespan; backup execution moved to `control-plane/src/modules/backups/`.
> The parity pass restored scheduler validation/await semantics, public jobs API
> `payload`/`result` and event shapes, invalid-timezone skip behavior for scheduled
> daily reports, atomic scheduled automation fire + schedule advance, best-effort
> backup manifest version metadata, backup-root permission tightening, prune
> resilience, and backup-disabled warnings.

- **Goal:** a generic TS queue service + worker registry; TS automation + daily-report
  schedulers; retention/backup jobs; stuck-job reclaim parity.
- **Domains/files touched:** new `modules/jobs/` (generalized out of
  `modules/runs/jobWorker.ts`); new `modules/automations/`; scheduler runner in the
  service shell (mirrors Python `SchedulerRegistry`).
- **Existing TS to reuse:** `modules/runs/{jobWorker,jobRepository,workerRuntime}.ts`
  (already a working TS queue worker for `agent_run`); `modules/notifications/*`
  (egress).
- **Python reference:** `backend/app/jobs/{queue.py,registry.py,worker.py,handlers.py}`,
  `scheduler/registry.py`, `main.py` lifespan (daily_report/automation/
  memory-retention/backup schedulers), `automation/{scheduler.py,schedule.py,service.py,
  policy_preflight.py}`, `daily_reports/{scheduler.py,handlers.py}`, `backups/*`.
- **Blockers:** the worker must claim only job types it has handlers for
  (`claimable_job_types`); stuck-job reclaim semantics; schedulers must be
  single-instance safe (avoid double-fire across replicas) — confirm deployment
  topology; intake jobs (Phase 7) register here.
- **Tests required:** job dispatch + retry/`max_attempts`; stuck-job reclaim; handler
  registry fail-fast (missing handler); scheduler enqueue idempotency; automation
  fire policy-preflight.
- **Completion criteria:** generic TS queue owns `agent_run`, `memory_consolidation`,
  and `daily_capture_report` job types; intake extraction runs as a direct
  in-process scheduler poll on `extraction_jobs` (not via the generic `jobs` table —
  `extraction_jobs` is already a purpose-built queue with its own status tracking);
  TS schedulers run; Python worker + `SchedulerRegistry` no longer needed.
- **Implementation status 2026-06-17:** complete. See status block above.
- **Rollback:** fix-forward / `git revert`. The TS worker claims only its registered
  job types, so you *may* briefly run it alongside the Python worker during cutover if
  convenient — but under the no-prod posture, prefer a clean switch-over and revert
  the commit if a handler misbehaves rather than maintaining a parallel Python worker.

---

## Phase 9 — Workspaces / sandbox / deployment

- **Status (2026-06-17): Completed for the reduced Phase 9 scope.** TS now owns
  `/workspaces*`, workspace-console read routes/session stubs, PathPolicy,
  worktree prepare/cleanup, sandbox GC, code_patch collection/apply, and the
  deployment edge/socket client. Deployment job persistence/proposal flow remains
  a deferred feature because create/get are still `feature_not_implemented` API
  stubs and no deployment job table exists.
- **Goal:** TS `WorkspaceManager` + `PathPolicy`; worktree prep/cleanup; sandbox GC;
  deployer socket client; deployment proposal/job flow. Unlocks `code_patch` apply
  from Phase 6.
- **Domains/files touched:** new `modules/workspaces/`, `modules/deployment/`;
  extend `modules/runs/ephemeralSandbox.ts` into the general sandbox/worktree manager;
  wire `code_patch` applier to workspace patch.
- **Existing TS to reuse:** `modules/runs/ephemeralSandbox.ts` (run-scope ephemeral
  dirs), `config.ts` `sandboxRoot`/`agentSpaceHome`/`cliToolsRoot`.
- **Python reference:** `backend/app/workspace/*` (`sandbox_manager.py`, PathPolicy),
  `workspace_console/api.py`, `workspaces/api.py`, `workspace_profiles/*`,
  `projects/*`, the `workspace.prepare`/`workspace.cleanup` port ops,
  `deployment/api.py`, `deployer/deployer.py`, B17–B19/B19A/B41–B44.
- **Blockers:** PathPolicy is a security surface — port with parity tests, no
  shortcuts; worktree diff → `code_patch` is the Stage 9 deferred work (provisioning,
  GC, diff-to-patch, cancel are not built); deployer socket access is filesystem-perm
  gated (B42) — confirm the TS service can reach the socket; decide whether
  `deployer/` (Python host process) is re-platformed or kept as a separate process
  (recommend: keep the deployer process, give it a TS client — it is not part of the
  app container, B41). **Reduced scope:** deployment job create/get and
  workspace-console session writes are currently `feature_not_implemented` stubs, so
  there is little Python *behavior* to port there — the real work is the TS
  `WorkspaceManager`/`PathPolicy`, worktree lifecycle, the deployer socket client,
  and the deployment proposal flow, not those stub routes.
- **Tests required:** PathPolicy allow/deny parity incl. system-core/external-root/
  restricted + forced-audit cases (B19A); worktree prepare/cleanup; sandbox GC;
  deployer allowlist (only `rebuild`/`restart`/`health_check`); code_patch apply
  through approval.
- **Completion criteria:** workspace reads/writes + console + deployment TS-owned;
  `workspace.prepare`/`cleanup` port ops unused; `code_patch` applies in TS through
  approval; `deployer/` reached only via the TS socket client.
- **Rollback:** fix-forward / `git revert`. Keep `code_patch` apply **failing closed**
  if the TS patch path regresses (correctness invariant, not a rollback lever).

---

## Phase 10 — Remove Python

- **Goal:** delete the Python backend and the bridge.
- **Domains/files touched:** delete `control-plane/src/pythonFallback/`,
  `ports/pythonHttp.ts`, all `python*Ports.ts` and Python `authority.py` guards;
  remove the `backend` service from `ops/compose/*`; cut control-plane over to the
  TS migration runner; remove the Python `internal_api.py` port routes; update
  `README.md`, `.agent/` docs (fold `TS_BACKEND_TARGET.md` into current-state docs),
  `CLAUDE.md`/`AGENTS.md`.
- **Existing TS to reuse:** the whole control plane is now the backend.
- **Python reference:** none after this — `backend/` is removed (retain in git
  history as reference).
- **Blockers:** the Phase 0 fallback-disabled CI must show **zero** Python-dependent
  routes; the TS migration runner (Phase 1) must be the sole schema owner; the TS DB
  role must be promoted to full app role; all schedulers/jobs/hooks running in TS.
- **Tests required:** full suite green with `enablePythonFallbackProxy=false` and no
  `backend` service running; empty-DB → TS migrations → full app boot; all invariant
  + contract + workflow suites ported/green against the TS backend.
- **Completion criteria:** `backend/` deleted; `pythonFallback/` and all port glue
  deleted; compose has no `backend`; Alembic runtime dependency gone; docs updated;
  the five completion criteria in `TS_MIGRATION_ROADMAP.md` §6 satisfied.
- **Rollback:** the **last** rollback point is "before deletion." Tag a pre-deletion
  commit with Python intact and the fallback enabled; if a regression appears after
  deletion, `git revert` the deletion commit or redeploy that tag. The only gate
  before entering Phase 10 is **fallback-disabled CI green** (zero Python-dependent
  routes) — no extended dogfooding-cycle gate is required when there is no prod, but
  the tagged escape hatch is cheap, so keep it.

---

## E. Final summary

### E.1 Top 10 blockers to deleting Python

1. **Identity introspection** (`/auth/introspect`, `/me`, `/me/spaces`) — every TS
   module calls Python to resolve `space_id`/`user_id` (`providers/identity.ts`).
   The deepest blocker. (Phase 2)
2. **Schema ownership** — Alembic + the single canonical `0001` migration is the sole
   schema owner; no TS migration runner exists yet. (Phase 1)
3. **Non-memory proposal target appliers** — proposal review/apply orchestration
   is TS-owned; memory and Knowledge appliers are registered. Task, agent config,
   policy-change rows, and workspace-backed `code_patch` still need their owning
   domains to migrate/register appliers. Until then they fail closed. (Phases 8–9)
4. **Run-adjacent child surfaces** — top-level run create/read/finalize and the
   run-finalization → task-evaluation bridge are TS-owned. Remaining run
   activity/proposal child read surfaces and preflight stay as later cleanup.
5. **Generic durable job queue** — TS control plane owns the queue, worker,
   schedulers, and backup ticks after Phase 8. (done)
6. **Activity/intake/knowledge/tasks** — migrated to TS for Phase 7 route
   ownership; intake extraction workers and consolidation jobs run in TS after
   Phase 8. (done)
7. **Workspace governance** — `WorkspaceManager`/`PathPolicy`, worktree prep/cleanup,
   `code_patch` apply, workspace-console writes are Python. (Phase 9)
8. **Python-owned run production tails** — artifact read/export is TS-owned, but
   artifact production for Python-owned run paths remains with those Python
   execution paths until their owning domains move. (Phases 8–9)
9. **Memory quality/evolution and digest refresh jobs** — consolidation runs in
   TS; digest refresh, evolver, and quality loops may still be Python-only.
   (partial — consolidation done in Phase 8)
10. **The fallback proxy itself + Python fail-closed guards** — `pythonFallback/proxy.ts` is
    still the default for every unowned route; deleting it is the completion metric.
    (Phase 10)

### E.2 Top 10 TS assets to preserve

1. **`modules/policy/*`** — full TS policy port (action registry, rule engine,
   decision orchestration, durable audit). Reference-quality core.
2. **`modules/providers/*`** — provider config/invocation/resilience/command store;
   the proof TS can own a hard domain end-to-end.
3. **Credential stack** — `cliCredentialBroker`, `cliLoginEngine` + `cliLoginAdapters/*`,
   `secretRefCrypto` (AES-GCM `secret_ref`); ADR 0010 channel isolation in TS.
4. **`gateway/*`** — route registry + `ControlPlaneModule` convention, request
   context, error envelope, logging hygiene. The permanent service spine.
5. **`config.ts`** — fail-fast config + authority DAG + immutable `ConfigSnapshot` +
   diagnostics.
6. **`@agent-space/protocol`** — contracts-only Zod package shared by both languages;
   becomes the TS backend's internal + frontend contract.
7. **`modules/runs/*` execution** — orchestration, jobWorker, managed/vendor adapters,
   ephemeral sandbox, materialization, evidence redaction.
8. **`modules/runtimeHost/*` + `runtimeTools/*`** — in-process model runtime + CLI
   tool registry; the runtimeAdapters seed.
9. **`modules/context/*` + `modules/memory/*` apply** — real TS context assembly
   and proposal apply (with provenance); the memory/context seeds.
10. **`db/pool.ts`** — the single `pg` access point that grows into the repository/tx
    substrate.

### E.3 Remaining pieces of migration glue to delete

1. `control-plane/src/pythonFallback/proxy.ts` — the catch-all fallback. (Phase 10)
2. `control-plane/src/ports/pythonHttp.ts` — Python authority forward port. (Phase 10)
3. `modules/runs/pythonContextPorts.ts` — artifact/proposal/workspace/finalize
   client; its `context.prepare` use is retired. (Phase 9/10)
4. Python-side glue: the `internal_api.py` port routes (`runs`, `sessions`, `agents`,
    `proposals`) and the `authority.py` fail-closed guards — deleted with `backend/`.
    (Phase 10)

### E.4 Recommended first implementation slice (after this prep)

**Phase 1 (DB + migration foundation), then the Phase 2 identity slice.**

Concretely, the first code slice is: a TS migration runner that baselines the
canonical `0001` schema with an empty-DB CI drift test (Phase 1), immediately
followed by **native TS identity** — `GET /auth/introspect` parity + gateway
identity middleware (Phase 2 first step). Rationale:

- Identity is the **single dependency every other module shares**; until TS resolves
  `space_id`/`user_id` itself, no domain can be deleted from the fallback and the
  proxy can never go away.
- It is a **small, well-bounded, high-leverage** slice with an existing contract
  (`@agent-space/protocol auth.ts`) and a clear parity oracle (the Python
  introspection response).
- It proves the full target stack on a real flow (gateway → auth service → repo →
  DB) without touching the riskier context/proposal machinery.

Do **not** start with a broad skeleton of all domains. Prove identity end-to-end
first; it de-risks everything downstream.

### E.5 Promote, replace, or refactor the current TS control plane?

**Promote it — with targeted refactors. Do not replace it.**

The control plane already owns the two hardest domains (providers/credentials,
policy) end-to-end, plus real run execution, memory proposal apply with provenance,
and a working TS context builder. It has a permanent gateway, a disciplined module
convention, fail-fast config diagnostics, a config snapshot engine, a DB pool, and a
shared protocol package. That is a foundation, not a prototype — a from-scratch
rewrite would discard proven, security-sensitive code (secret_ref crypto, credential
channel isolation, durable policy audit) for no benefit.

The required work is **finishing**, not restarting:

- **Build** the Python-only domains in TS (auth, spaces, activity, intake, knowledge,
  tasks, jobs/automations, workspaces, deployment).
- **Cut** the port tails (`python*Ports.ts`, `identity.ts`, fallback proxy) as each
  replacement lands.
- **Refactor** a few boundaries: `frontendSupport` forward→native aggregation;
  generalize `runs/jobWorker` into a `jobs` domain; carry identity in
  `requestContext`; keep genuine product feature flags while deleting migration
  scaffolding as each remaining Python domain moves.
- **Cleanup posture (no prod):** rollback is fix-forward / `git revert`; the fallback
  proxy and `*Authority` switches are transitional bridges removed per-domain, not
  standing rollback levers; parity/shadow are replaced by tests + dogfooding. See
  "Execution posture" above.

The Python backend's value from here is **reference only** — behavior, route/domain
inventory, schema history, and the invariant/contract/workflow test corpus that each
TS domain must pass before its Python counterpart is retired.
