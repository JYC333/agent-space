# TypeScript Reuse in the Re-platform

> **Status:** temporary report (per `.agent/INDEX.md` §7). Not source of truth.
> Produced 2026-06-15. Grounded in `control-plane/src/`, `packages/protocol/src/`,
> `apps/web/src/api/`, and `catalog/`. Companion to
> [`python-retirement-inventory.md`](python-retirement-inventory.md) and
> [`ts-backend-replatform-plan.md`](ts-backend-replatform-plan.md).
>
> Question answered: **for each existing TypeScript asset, do we keep it, move it,
> rewrite the concept, or delete it as migration glue** — and does it belong in the
> long-term TS backend core?

## Classification key

- **K** — *keep as-is*: sound, no Python dependency, fits the target.
- **M** — *keep but move/refactor*: good code, but its boundary/location changes
  (e.g. an "edge that forwards to Python" becomes a real domain service).
- **R** — *keep concept, rewrite TS-native*: the responsibility is right but the
  current implementation leans on a Python internal port; the logic must be
  reimplemented against the DB/TS services.
- **D** — *delete later (migration glue)*: exists only to bridge to Python; removed
  when the bridged domain is TS-native.

The default stance (strongly supported by the code): **the existing control-plane
is the correct foundation and should be promoted, not replaced.** It already has a
permanent gateway, a module convention, config/authority discipline, a DB pool, a
protocol contract package, and real domain logic (providers, policy, runs
execution, memory apply). The re-platform is *finishing* it, not restarting.

---

## 1. Gateway and service core (`control-plane/src/`, `gateway/`)

| Item | Path | Responsibility | Python dep | Class | Target domain | Reuse / change | Core? |
|---|---|---|---|---|---|---|---|
| Process entry | `index.ts` | config load, listen, shutdown | none | **K** | service shell | reuse | yes |
| Composition root | `server.ts` | builds Fastify, opaque body parser, delegates routing | none | **K** | service shell | reuse | yes |
| Config + authority switches | `config.ts` | `CONTROL_PLANE_*` parsing, fail-fast validation, authority DAG, `ConfigSnapshot`, diagnostics | none | **M** | deployment/config | keep the validation+snapshot engine; **collapse the 10 `*Authority` migration switches incrementally as each domain migrates** (not only at the end — see the plan's "Execution posture"), keeping genuine product feature flags (`enableNotificationWebhookEgress`, etc.) | yes |
| Route registry | `gateway/routeRegistry.ts` | `ControlPlaneModule` contract, registration order, `ModuleContext` | none | **K** | gateway | reuse; drop the "proxy registered last" step when fallback is deleted | yes |
| Request context | `gateway/requestContext.ts` | request-id continuity, safe header access, marker header | none | **M** | gateway/auth | keep; **extend** `buildRequestContext` to carry validated identity (user/space/actor) once TS owns auth — today it explicitly does not parse auth | yes |
| Error envelope | `gateway/errorEnvelope.ts` | uniform error shape, 5xx redaction | none | **K** | gateway | reuse | yes |
| Logging hygiene | `gateway/logging.ts` | logger options, secret redaction | none | **K** | gateway | reuse | yes |
| Internal auth | `gateway/internalAuth.ts` | `timingSafeEqual` service-token check | none | **M** | auth/internal | keep for any residual internal service calls; most uses disappear with the ports they guard | partial |
| DB pool | `db/pool.ts` | single `pg` Pool per URL | none | **M** | persistence | keep; grows into the shared repository/transaction substrate (add a transaction helper + typed query layer) | yes |

---

## 2. Python bridge layer — the glue (`pythonFallback/`, `ports/`, `modules/*/python*.ts`)

This is the layer the re-platform **deletes**. Everything here exists to reach
Python.

| Item | Path | Responsibility | Python dep | Class | Removed in phase | Notes |
|---|---|---|---|---|---|---|
| Fallback proxy | `pythonFallback/proxy.ts` | catch-all `/api/v1/*` → Python | total | **D** | Phase 10 | Deleting this is the strict migration-completion metric. |
| Python authority port | `ports/pythonHttp.ts` | forward a TS-owned edge route to Python authority + sanitized transport errors | total | **D** | Phase 10 | Last user is likely `identity.ts`; dies with native auth. |
| Identity introspection | `modules/providers/identity.ts` | `GET /auth/introspect` caller; resolves `space_id`/`user_id` | total | **R** | Phase 2 | Concept (resolve caller identity) stays; rewrite as **native TS auth middleware**. The single most-depended-on glue file. |
| Providers shadow compare | `modules/providers/shadow.ts` | read-only TS-vs-Python divergence logging | total | **D** | Phase 3 | Parity scaffold. Under the no-prod posture, **drop it now** (rely on tests + dogfooding) rather than maintaining a comparison path. |
| Run context ports | `modules/runs/pythonContextPorts.ts` | calls `/internal/runs-context` (`artifact.persist`, `proposal.create`, `workspace.*`, `finalization.finalize`; `context.prepare` retired) | total | **R** | Phases 6, 9 | Remaining operations become TS services (artifact store, workspace manager, finalizer). |
| Stage-6 ports | ~~`modules/memory/pythonStage6Ports.ts`~~ | calls `/internal/stage6-context` (`context.build`, `memory.read`, `memory.proposal_create`, `session_summary.get_latest`) | total | **R** | Phase 5 | Deleted; replaced by TS context build + memory read/proposal services. |
| Chat context ports | ~~`modules/agents/pythonChatContextPorts.ts`~~ | chat candidate reads via `/internal/agents-chat` | total | **R** | Phase 5 | Deleted; replaced by TS candidate selection. |
| Chat turn prep | ~~`modules/agents/pythonChatTurnPrep.ts`~~ | `prepare-run` / `create-run` for chat | total | **R** | Phase 5 | Deleted; replaced by TS context/run creation. |
| Proposal ports | `modules/proposals/pythonProposalPorts.ts` | `proposal.accept/reject/egress_approval`, `memory.apply_gate` | total | **R** | Phase 6 | Replaced by TS per-type applier registry + apply gate. |

> All `python*Ports.ts` files and `identity.ts` are **R, not D**: their *clients*
> die, but the *behavior* they invoke must be reborn in TS first. Sequencing
> matters — delete the port only after its TS-native replacement passes parity.

---

## 3. Domain modules that are real TS logic today

These hold genuine business logic already and seed their target domains. Most are
**K/M**; the ones still calling a Python port for part of their flow are **M with an
embedded R** (the glue inside them, listed in §2, is what gets cut).

### 3.1 Provider / credential / runtime stack — strongest reuse

| Module | Path | Responsibility | Python dep | Class | Target domain | Core? |
|---|---|---|---|---|---|---|
| providers | `modules/providers/*` (service, routes, providerInvocation, providerResilience, providerCommandStore/Routes, secretRefCrypto, db/dbReader, cliCredentialBroker, cliLoginEngine + `cliLoginAdapters/*`, usage probes/readers/scheduler, claudeOAuthUsageProbe, protocolRuntime, hostPath) | identity only | **M** | providers + credentials | **yes** |
| runtimeHost | `modules/runtimeHost/*` | in-process provider-backed model runtime (`ts_agent_host`); normalized adapter result | none (Python `runs` calls *it*) | **K** | runtimeAdapters | **yes** |
| runtimeTools | `modules/runtimeTools/*` | CLI binary install/status registry, tool definitions, resolver port | none | **K** | runtimeAdapters | **yes** |

> This stack is the **proof that TS can own a hard domain end-to-end**: AES-GCM
> `secret_ref` crypto, credential pools/rotation/cooldown, per-task provider
> policy, CLI login engine with per-vendor adapters, usage probes. It is the model
> to copy for every other domain. Only `identity.ts` (auth) and `shadow.ts` are
> glue; the rest is keep/move.

### 3.2 Runs execution — large, real, but context-coupled to Python

| Module | Path | Responsibility | Python dep | Class | Target domain | Core? |
|---|---|---|---|---|---|---|
| runs (commands) | `modules/runs/routes.ts`, `orchestrationService.ts` | `execute`/`stop` commands, internal `/internal/runs/execute` | `pythonContextPorts` | **M+R** | runs | yes |
| run job worker | `modules/runs/jobWorker.ts`, `workerRuntime.ts`, `jobRepository.ts` | TS `agent_run` worker, claim/dispatch | reads via Python in places | **M** | jobs + runs | yes |
| adapters | `modules/runs/managedApiAdapter.ts`, `vendorCliAdapter.ts`, `ephemeralSandbox.ts` | managed-API no-tool path; vendor CLI path; run-scope ephemeral sandbox | partial | **M** | runtimeAdapters + workspaces | yes |
| materialization | `modules/runs/materializationService.ts`, `evidenceRedaction.ts`, `processRegistry.ts`, `repository.ts` | run output materialization, evidence redaction, process tracking, run reads | reads via Python | **M** | runs/artifacts | yes |
| context glue | `modules/runs/pythonContextPorts.ts` | (see §2) | total | **R** | context | — |

> Verified scope today (per roadmap Stage 4): managed-API no-tool + run-scope
> ephemeral CLI. The execution skeleton is reusable; what is *not* yet TS is the
> **context preparation** it calls Python for, and the run **read model / create /
> finalize** surfaces. Keep the executor; build the context + read/create/finalize
> services beside it (Phases 4–5).

### 3.3 Policy — clean TS port, keep

| Module | Path | Responsibility | Python dep | Class | Target domain | Core? |
|---|---|---|---|---|---|---|
| policy | `modules/policy/*` (actionRegistry, decisionCore, decisions, gateway, auditWriter, sanitizer, service, routes) | canonical action registry, hard-invariant guard, rule engine, decision orchestration, durable audit to `policy_decision_records`; internal enforce + proposal-apply ports | identity only | **K** | policy | **yes** |

> This is a full TS port of the Python `policy` context and writes its own durable
> audit. It is reference-quality core. Keep as-is; it becomes the policy service the
> whole TS backend consults.

### 3.4 Proposals / memory / sessions / agents — TS edge + TS apply

| Module | Path | Responsibility | Python dep | Class | Target domain | Core? |
|---|---|---|---|---|---|---|
| proposals | `modules/proposals/*` (routes, repository, applyService, applierRegistry) | list/get/accept/reject/egress review routes; TS transaction boundary; registry dispatch; unregistered proposal types fail closed | none for the current proposal route | **K+M** | proposals | yes |
| memory | `modules/memory/*` (repository, proposalRepository, memoryReadAuth, memoryApplyRepository, memoryApplyProvenance, contextSnapshotRepository, sourceMonitoring) | `/memory` reads, read-access logging, proposal create, **memory proposal apply**, snapshot persistence | none for current read/proposal/apply routes | **K+M** | memory + context | **yes** |
| sessions | `modules/sessions/*` (routes, repository) | list/get/create sessions, list/add messages, latest-summary read | identity only | **K** | sessions | yes |
| agents | `modules/agents/*` (routes, repository, chatContextBuilder) | Personal Assistant chat turn orchestration + TS `ChatContextBuilder` (budget/dedup/snapshot) | none for chat path | **K+M** | agents + context | yes |

> `memory` contains **real apply logic** (`memoryApplyRepository`,
> `memoryApplyProvenance`) and `agents` already contains a real **TS
> ChatContextBuilder** (`chatContextBuilder.ts`). These are the seeds of the TS
> context/memory engine — keep them and extend, do not restart. Remaining
> `python*Ports` tails are for later domains, not the proposal/memory route.

### 3.5 Edge / facade modules

| Module | Path | Responsibility | Python dep | Class | Target domain | Core? |
|---|---|---|---|---|---|---|
| system | `modules/system/*` | health + `/api/v1/control-plane/features` descriptors | none | **K** | system/deployment | yes |
| catalog | `modules/catalog/*` | read-only surface over top-level `catalog/` (agent templates, capabilities) | none (reads files) | **K** | capabilities/agents | yes |
| streaming | `modules/streaming/*` | run-event SSE transport edge | reads events from Python | **M** | runs/activity | yes |
| notifications | `modules/notifications/*` | allowlist-gated outbound webhook egress (TS-first capability) | none | **K** | automations/egress | yes |
| frontendSupport | `modules/frontendSupport/*` | forwards `/home/summary`, `/me/*`, `/workspace-console/*` reads to Python | total (forwards) | **M→D** | frontend aggregation | partial |

> `frontendSupport` is special: as a *concept* (a frontend aggregation/home-summary
> domain) it stays, but its current implementation is **pure forwarding glue**. As
> each underlying domain (home, me, workspace_console) goes TS-native, its forwards
> become native reads or are removed. Treat the routes as **M** (the aggregation
> domain survives) and the forwarding bodies as **D**.

---

## 4. Protocol package (`packages/protocol/src/`) — keep, it is the contract spine

`@agent-space/protocol` is contracts-only (Zod schemas + types), shared by both
languages. It is **K** wholesale and is **core**.

| File | Covers | Class |
|---|---|---|
| `index.ts`, `common.ts`, `schemas.ts` | shared primitives, envelope, pagination | K |
| `auth.ts` | identity introspection response contract | K (grows when TS owns auth) |
| `model.ts`, `events.ts` | canonical model event contracts (P1 absorption) | K |
| `providers.ts`, `providersDb.ts`, `providerCredentialsRuntime.ts`, `credentials.ts` | provider/credential wire + DB read contracts | K |
| `policy.ts` | policy decision contracts | K |
| `proposals.ts` | proposal contracts | K |
| `memorySessions.ts` | memory/session contracts | K |
| `runOrchestration.ts`, `runContextPorts.ts`, `runtimeHost.ts` | run orchestration, context port, runtime host contracts | K (the *port* shapes may simplify when ports die, but the contracts stay) |
| `commands.ts`, `dto.ts` | command + DTO shapes | K |

> Recommendation: as Python is retired, the protocol package shifts from a
> *cross-language wire contract* to the *internal type contract of the TS backend*
> plus the *frontend API contract*. It does not shrink — it becomes more central.
> Note `apps/web/src/types/api.ts` currently duplicates many DTOs; consolidating the
> frontend onto `@agent-space/protocol` is a worthwhile (separate) cleanup.

---

## 5. Catalog (`catalog/`) — data, not code; keep

`catalog/agent_templates/*` and `catalog/capabilities/*` are file-based definitions
read by the TS `catalog` module and the Python capability registry. They are
runtime-agnostic content. **K.** The only Python tie is `catalog/capabilities/__init__.py`
and the Python `capabilities`/`agent_templates` DB registries that load them — those
move with their domains (Phase 7-ish), but the catalog content itself is reused
unchanged.

---

## 6. Frontend API client (`apps/web/src/api/client.ts`) — keep, no re-platform churn

The frontend speaks `BASE = '/api/v1'` to the control plane and is **deliberately
unaware** of the TS/Python split (the gateway hides it). This is the payoff of the
control-plane-as-entrypoint design: **the re-platform should be invisible to the
frontend.** No frontend rewrite is in scope. The only frontend-facing risk is
contract drift during a domain flip — covered by keeping `@agent-space/protocol`
authoritative plus contract tests + dogfooding on each flip (no prod, so no
shadow-compare path is maintained).

---

## 7. Summary: what the existing TS earns

- **Promote, don't replace.** The control plane already demonstrates TS ownership of
  the two hardest domains (providers/credentials, policy) end-to-end, plus real run
  execution, memory apply, and a TS context builder. That is a foundation, not a
  prototype.
- **Keep (core):** gateway stack, `config` engine, `db/pool`, `@agent-space/protocol`,
  `catalog`, and the providers/credentials/runtimeHost/runtimeTools/policy/sessions
  modules.
- **Move/refactor:** `frontendSupport` (forward → native aggregation), `streaming`,
  `runs` executor (decouple from context port), `memory`/`agents`/`proposals` (cut
  the port tails), `requestContext` (carry identity), `config` authority switches
  (collapse the 10 migration switches incrementally per domain — not at the end —
  keeping real product feature flags).
- **Rewrite TS-native (concept kept):** identity (`identity.ts` → auth middleware),
  every `python*Ports.ts` operation (context.prepare, memory.read, proposal apply
  gate, chat candidates/run-create, workspace prep/cleanup, finalize).
- **Delete (glue):** `pythonFallback/proxy.ts`, `ports/pythonHttp.ts`,
  `providers/shadow.ts`, and all `python*Ports.ts` clients — **after** their
  replacements land.

Exact sequencing and per-phase reuse are in
[`ts-backend-replatform-plan.md`](ts-backend-replatform-plan.md). The target
ownership model is in
[`../architecture/TS_BACKEND_TARGET.md`](../architecture/TS_BACKEND_TARGET.md).
