# TS Migration Roadmap (with PilotDeck & Hermes Absorption)

> **Status:** forward-looking plan, established 2026-06-11. This document is a
> roadmap, **not** an authorization: every authority move still requires an
> explicit per-context decision under
> [`TS_MIGRATION_STRATEGY.md`](TS_MIGRATION_STRATEGY.md) §8. Companions:
> [`TS_MIGRATION_STRATEGY.md`](TS_MIGRATION_STRATEGY.md) (binding rules),
> [`TS_CONTROL_PLANE_FOUNDATION.md`](TS_CONTROL_PLANE_FOUNDATION.md) (the service),
> [`CONTROL_PLANE_MODULE_CONVENTION.md`](CONTROL_PLANE_MODULE_CONVENTION.md)
> (module structure).
>
> External references: PilotDeck architecture
> (<https://pilotdeck.openbmb.cn/pilotdeck.github.io/docs/architecture/overview>)
> and Hermes Agent
> (<https://hermes-agent.nousresearch.com/docs/zh-Hans/user-guide/features/overview>)
> were reviewed 2026-06-11 as design sources for capabilities we have not built
> yet — agent-runtime internals (PilotDeck) and provider resilience (Hermes).
> §2 records what we absorb and what we explicitly reject.

---

## 1. Guiding principles

1. **New capability → TS-first.** Anything not yet implemented in Python is
   built as a control-plane module (or TS runtime host, §4 Stage 4) from the
   start. Building it in Python first and migrating later is double work and is
   the default we avoid.
2. **Existing capability → migrate by bounded context.** Never file-by-file
   translation. Order follows strategy §9 (ready/low-risk → medium → `memory`
   last). Each cut-over is one explicit decision, recorded as an ADR.
3. **Dogfooding-blocking fixes may still land in Python**, kept minimal, and
   flagged in this document as migration debt (§3 Stage 0).
4. **Strategy §8 invariants are binding throughout**: single command authority
   at every moment, facade + port before migration, credential-channel
   isolation (ADR 0010), proposal/activity flow for cross-context writes.
5. **The legacy proxy surface is the progress metric.** Each stage shrinks what
   `control-plane/src/legacy/pythonProxy.ts` forwards; the migration is done
   when the proxy is deleted.

## 2. Absorption maps

What we take from each reviewed system, where it is built, and at which stage.
Both reference systems are single-user agent runtimes; agent-space's governance
model (spaces, policy engine, proposal gate, ADR 0010) is the constant the
absorbed designs must fit into — never the other way around.

### 2.1 PilotDeck

| # | PilotDeck concept | What we absorb | Build where | Stage |
|---|---|---|---|---|
| P1 | Canonical model protocol (`CanonicalModelRequest/Event/Message/Usage`) | Unified **streaming event schema** across providers; request side is already normalized by litellm | `packages/protocol/` (TS types + Zod) | 1 |
| P2 | Per-chat concurrency guard ("one message processing blocks new messages in the same chat") | Per-session in-flight guard for assistant chat to prevent out-of-order replies | Python `sessions`/`agents` (migration debt) | 0 |
| P3 | Context engine: PromptAssembler / MessageProjector / TokenBudgetManager / CompactionEngine (auto-/micro-compaction, overflow recovery) | Token budgeting + graduated compaction + overflow recovery for long chats. Near term: minimal overflow guard on the existing `SessionCondenser`/`ChatContextBuilder`. Full engine is built TS-native when `memory`/`sessions` migrate | Minimal: Python `memory`/`sessions`. Full: TS, with the migrated context stack | 0 (minimal), 6 (full) |
| P4 | Config pipeline: immutable snapshot (version + content hash + timestamp), semantic cross-validation, diagnostics with severity + machine error codes, reload keeps last-good config | Snapshot-style config distribution to modules via `ModuleContext`; semantic checks; diagnostic codes | `control-plane/src/config.ts` + `gateway/` | 1–2 |
| P5 | Gateway streaming to channels | SSE/WebSocket **edge** terminated in the control plane, sourcing events from Python (no authority move) | Control-plane module | 2 |
| P6 | AgentSession → TurnRunner → AgentLoop layering; Concurrent/Sequential ToolScheduler | In-process agent loop with tool registry + scheduler, for `model_api`-style runs that need tools without a vendor CLI | **TS runtime host** invoked by Python `runs` through the existing runtime-adapter seam (`BaseRuntimeAdapter`-equivalent boundary) | 4 |
| P7 | MCP client integration | MCP as the standard tool source for the TS agent loop; authorization stays in `RuntimeToolBinding` (`external_type='mcp_server'`) | Part of the TS runtime host | 4 |
| P8 | Channel adapters (16+ platforms; per-channel: implementation + session mapping + rendering) | Channel adapter **module convention** for IM/email ingestion; session mapping extends to space + user + session | Control-plane `modules/<channel>/` | 7 |
| P9 | Always-On trigger budgets + cooldown | Budget/cooldown governance concept for future proactive triggers, as policy vocabulary | Concept only; lands with `automation` evolution | 7 |

### 2.2 Hermes

Hermes's strongest area is **provider resilience** — currently a gap in our
`providers`/`credentials` modules (no retry/rotation/fallback-chain logic in
the invocation path; one credential per `ModelProvider`).

| # | Hermes concept | What we absorb | Build where | Stage |
|---|---|---|---|---|
| H1 | Three-layer resilience, layers 1–2: **credential pools** (N keys per provider; fill_first / round_robin / least_used / random rotation; health + cooldown state) and **per-turn primary-model fallback**. Error taxonomy: 429 retry-same-key-once then rotate; 402 rotate immediately + 24h cooldown; 401 refresh token first, rotate only on refresh failure; quota-exhaustion pattern recognition distinct from transient `Retry-After` limits | `ModelProvider` 1→N encrypted Credentials with pool/health/cooldown state as **server-side DB records**; space-level shared pools (a multi-user capability Hermes lacks); per-turn fallback granularity (every new user message restarts on the primary model — no sticky degradation) | `providers`/`credentials` context — TS-native when it migrates; optional Python minimal version at Stage 0 if dogfooding hits rate limits | 3 (minimal: 0) |
| H2 | Three-layer resilience, layer 3: **per-auxiliary-task provider chains** (vision, compression, title generation, approval classification …) with a main-model safety net; compression degrades gracefully (drops middle rounds) instead of failing the session | Generalize `REFLECTOR_MODEL_PROVIDER_ID` into a per-auxiliary-task provider policy (reflector, condenser llm mode, future extraction/title tasks) with optional fallback chains and graceful degradation | `providers` context, together with H1 | 3 |
| H3 | Provider routing compliance flags: `data_collection: deny`, `require_parameters`, only/ignore provider lists | **Space-level** provider allow/deny and data-collection policy as policy-engine vocabulary (per-space governance instead of Hermes's global config) | Python `policy` vocabulary first; migrates with `policy` | 5 |
| H4 | Checkpoints: auto-snapshot before file changes + `/rollback` | Rollback points for **approved proposal apply** — snapshot before applying `code_patch`/workspace proposals so an approved apply stays reversible | Python `proposals`/`workspace` (apply authority is Python until Stage 5); migrates with `proposals` | ≤5 |
| H5 | Delegation/cron tasks do **not** inherit primary fallback config; explicit per-task provider overrides only | Design rule: child execution contexts (sub-runs, scheduled runs) receive **explicit config grants, never ambient inheritance** — consistent with the ExecutionContext philosophy | Principle; binds the Stage 4 runtime host and any future delegation | 4+ |
| H6 | Event hooks: outbound webhooks/alerts | Policy-gated **outbound notification/webhook egress** module (e.g. proposal-pending alerts to IM); our existing hook registries are all in-process | Control-plane TS module | 2+ |

### 2.3 Explicitly NOT absorbed

From PilotDeck:

- **Secrets in YAML / `${ENV}` substitution** — conflicts with ADR 0010;
  encrypted `ModelProvider` Credentials + broker remain the only channel.
- **Global single-scope configuration** — `space_id` scoping is the product's
  core isolation boundary; PilotDeck has no multi-user model.
- **Gateway as message bus / plugin system** — per
  `CONTROL_PLANE_MODULE_CONVENTION.md` the control-plane gateway stays a thin
  HTTP entry layer. Channels (P8) become **modules**, not gateway plugins.

From Hermes:

- **Local `auth.json` credential/pool state** — pool health, cooldowns, and
  request counts must be server-side DB records; encrypted Credentials +
  broker remain the only secret channel (ADR 0010).
- **Media stack** (voice, TTS, image generation, browser automation) —
  different product direction.
- **Batch processing / RL trajectory generation** — non-goal.
- **External memory-provider backends** (Honcho, Mem0, …) — validates our
  `MemoryProvider` port seam, but `LocalMemoryProvider` stays the only MVP
  provider; no follow-up planned.
- **OpenAI-compatible API server** — noted as a possible far-future
  control-plane module; not planned in any stage.

## 3. Stages

Stages are sequenced by entry criteria, not dates. They are distinct from the
already-shipped foundation phases (protocol package, control-plane service,
module convention Phase C).

**Status snapshot (2026-06-11):**

| Stage | Status |
|---|---|
| 0 | **Active / conditional.** Dogfooding fixes only; the per-session chat guard is still open, and overflow/provider-resilience guards start only if real dogfooding exposes those blockers. |
| 1 | **Shipped.** Read-only TS beachhead is in place. |
| 2 | **Ready to start.** Entry criteria are met; no Stage 2 capability is claimed as shipped yet. |
| 3 | **Not ready.** Requires at least one read context cut over cleanly plus per-context ADRs. |
| 4 | **Not ready.** Requires Stage 2 streaming edge to prove the canonical event protocol. |
| 5 | **Future.** Requires stable Stage 3 contexts and a proven Stage 4 host. |
| 6 | **Future / last core migration.** Requires memory inbound coupling cleanup. |
| 7 | **Future product expansion.** Requires stable provenance/proposal boundaries and core contexts migrated. |

### Stage 0 — Dogfooding fixes (Python, minimal, migration debt)

Runs in parallel with [`current-focus.md`](../tasks/current-focus.md); not migration work.

**Status: active / conditional, not complete.**

- Per-session concurrency guard for assistant chat (absorption P2).
- Only if real chats hit context limits during dogfooding: minimal overflow
  guard on `SessionCondenser` / chat context (absorption P3 minimal). Keep it
  small — the full engine is Stage 6, TS-native.
- Only if multi-key rate limiting becomes a real dogfooding pain: minimal
  provider resilience in the Python providers facade — the H1 error taxonomy
  plus single-layer key rotation (absorption H1 minimal). The full pool /
  fallback stack is Stage 3, TS-native.

**Debt rule:** anything added here must sit behind the module's existing facade
so it migrates with its context, and gets a `TODO(ts-migration)` marker.

### Stage 1 — Read-only TS beachhead

Entry: Phase C merged. No command authority moves.

**Status: shipped 2026-06-11** (implemented on the Phase C branch; lands with
its merge; verified locally with protocol/control-plane typecheck + tests).

- **`catalog` module** (`control-plane/src/modules/catalog/`): first TS-owned
  read surface over the top-level `catalog/` directory (already named the first
  candidate in the module convention). Shipped: summary + capabilities +
  agent-templates routes, advertised as `catalog_read`; missing catalog
  degrades to `catalog_available: false`.
- **Canonical model event types** in `packages/protocol/` (absorption P1):
  request/event/message/usage shapes for streaming, kept in lockstep with the
  Python provider facade output. Contracts only — no handlers. Shipped as
  `packages/protocol/src/model.ts` (`CanonicalModelRequest/Message/Usage`,
  `CanonicalModelEvent` discriminated union under `model.*` event types).
- **Config snapshot + diagnostics** in the control plane (absorption P4):
  immutable validated snapshot distributed via `ModuleContext`; machine error
  codes in startup diagnostics. Shipped: `ConfigSnapshot` (schema version +
  content hash + load timestamp), `ConfigError.code`, and
  `unknown_config_key` warnings for unrecognized `CONTROL_PLANE_*` variables.

### Stage 2 — TS-owned edge capabilities

Entry: Stage 1 shipped; canonical event types exist.

- **Streaming edge** (absorption P5): control-plane module terminates SSE
  (later WS) for run events / chat streaming, consuming Python as the event
  source. Python stays the authority for what the events *mean*; the control
  plane owns transport and fan-out only.
- **Outbound notification/webhook egress** (absorption H6): policy-gated
  control-plane module pushing e.g. proposal-pending alerts to external
  channels. New capability → TS-first; no Python equivalent exists.
- **Frontend-support read models** (`home`, `me`, `workspace_console`) become
  cut-over candidates here — they are aggregation-only. Each one still requires
  a per-context decision and a facade + port on the Python side first.
- Config **semantic validation** (absorption P4): cross-entity checks at the
  control-plane edge for the config it owns (never validating Python-owned
  business state).

### Stage 3 — First command contexts migrate

Entry: at least one read context cut over cleanly; per-context ADRs.

Strategy §9 "ready/low-risk" list, one at a time:
`providers` (cleanest port), `credentials`, `capabilities`, `projects`,
`activity`. For each context, the §7 sequence applies: protocol contract →
TS adapter calling Python → control-plane routing → single cut-over.

ADR 0010 note: when `credentials` and `providers` move, the broker and the
encrypted-secret handling move **as a whole context**; at no moment do Python
and TS both decide credential release.

The `providers`/`credentials` migration is also where the **Hermes resilience
layer** is built TS-native (absorptions H1 + H2): credential pools (1→N
encrypted credentials per provider; rotation strategies; health and cooldown
state as server-side DB records), the 429/402/401/quota error taxonomy,
per-turn primary-model fallback, and per-auxiliary-task provider chains
(generalizing `REFLECTOR_MODEL_PROVIDER_ID`) with graceful degradation.
Building the resilience layer during the migration avoids writing it twice;
only the Stage 0 minimal guard may precede it in Python.

The pools govern **ModelProvider API-key credentials only**. CLI login state
is a distinct credential class (see `CREDENTIAL_STORAGE.md`) and is neither
pooled nor rotated; the CLI credential broker migrates with this context but
keeps its separate channel.

### Stage 4 — TS agent runtime host (new capability, TS-first)

Entry: canonical protocol (Stage 1) proven by the streaming edge (Stage 2).
This is the first *business-logic-bearing* TS build, and it deliberately does
**not** take run authority.

- **Agent loop** (absorption P6): AgentSession/TurnRunner/AgentLoop layering,
  tool registry, sequential + concurrent tool scheduling.
- **MCP client** (absorption P7): tools sourced from MCP servers;
  `RuntimeToolBinding` records remain the authorization surface.
- **Explicit config grants, no ambient inheritance** (absorption H5): the
  host's runs — and any future sub-run delegation — receive provider, model,
  and fallback configuration explicitly per execution context, never
  inherited from the parent environment.
- **Boundary:** the host is a **runtime adapter implementation** — Python
  `runs` keeps run lifecycle/orchestration authority and invokes the TS host
  exactly as it invokes a CLI runtime today (injected ports for events and
  process handles). Same pattern, no dual authority.
- **Credentials:** the TS host receives provider keys from the credential
  broker over a sanctioned internal channel (the in-process API channel
  equivalent) — never via subprocess env, per ADR 0010.
- **CLI runtimes are not replaced:** vendor CLI adapters (`claude_code`,
  `codex_cli`, …) remain a permanent execution channel with their own CLI
  login credentials. The TS host adds a third path — API-channel runs *with*
  tools — alongside CLI-with-tools and `model_api`-without-tools. The ADR 0010
  dual-channel model (model-provider API channel vs CLI channel) is permanent,
  not a migration phase.

### Stage 5 — Medium contexts

Entry: Stage 3 contexts stable; Stage 4 host proven in real runs.

`policy` (has `PolicyPort`), `proposals` (applier registry makes proposal-type
ownership explicit), then `runs`. The `runs` migration absorbs the Stage 4
runtime host naturally: orchestration joins execution on the TS side as one
context.

Two Hermes items ride along with these contexts:

- **Provider privacy/compliance policy** (absorption H3): space-level provider
  allow/deny and data-collection rules as policy-engine vocabulary. May be
  added Python-side before the `policy` migration; migrates with it.
- **Proposal apply rollback points** (absorption H4): snapshot before applying
  approved `code_patch`/workspace proposals so an approved apply stays
  reversible. Built Python-side (apply authority remains Python until this
  stage); migrates with `proposals`.

### Stage 6 — Last: memory + sessions (the cycle hub)

Entry: inbound product coupling on `memory` (`intake`, `knowledge`,
`evolution`, `agents`, `sessions`) inverted per the boundaries cleanup;
`ContextBuilderPort` + `MemoryProvider` are the beachhead.

- Migrate `memory` + `sessions` contexts.
- Build the **full context engine** TS-native here (absorption P3): token
  budget manager, message projection, graduated compaction
  (micro → full), overflow recovery — the PilotDeck four-part blueprint —
  replacing the Stage 0 minimal guards.
- The memory-quality work absorbed from gbrain (weighted claims, hybrid
  retrieval, synthesis + gap loop, consolidation cycle) is tracked separately
  in [`MEMORY_EVOLUTION_PLAN.md`](MEMORY_EVOLUTION_PLAN.md). It lands
  Python-side behind the `app.memory` facade **before** this stage as product
  capability (not migration debt) and migrates with the context here.

### Stage 7 — Product expansion on the TS base

Entry: intake/evidence provenance and proposal boundaries stable (currently a
non-goal in [`current-focus.md`](../tasks/current-focus.md)); core contexts migrated.

- **Channel adapters** (absorption P8): `modules/<channel>/` convention with
  channel implementation + session mapping (external chat id → space + user +
  session) + rendering config. Per-chat ordering uses the Stage 0 guard's
  semantics.
- **Always-On governance** (absorption P9): trigger budgets + cooldown as
  policy vocabulary for proactive automations.

## 4. Per-context cut-over checklist

Every context migration (Stages 2–6) follows the same gate sequence; each gate
is verifiable:

1. Python facade + port exists, proven by a fake + contract test
   (strategy §8.3).
2. Wire contract for the context lives in `packages/protocol/` and is
   exercised by both sides' tests.
3. TS implementation exists behind an explicit control-plane module route,
   advertised in `/api/v1/control-plane/features`.
4. Optional read-only shadow compare (clearly non-authoritative).
5. Cut-over decision recorded as an ADR; routing flips for that context only;
   the legacy proxy stops forwarding those paths.
6. Python implementation for the context is retired (not kept as a second
   authority).

## 5. Standing risks

- **Scope creep into dual authority** — the §8.1 invariant fails silently if a
  "temporary" TS fallback writes anything. Shadow modes must be read-only.
- **Stage 4 boundary erosion** — the runtime host will be tempting to grow into
  run orchestration. It must stay an adapter until Stage 5 moves `runs`
  deliberately.
- **Stage 0 debt outliving its context** — Python-side guards/compaction must
  migrate with `sessions`/`memory`, not survive as parallel logic.
- **Channel adapters before provenance is stable** — Stage 7 entry criterion
  exists precisely because broad connectors are a current non-goal.
