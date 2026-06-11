# TypeScript-First Migration Strategy

> **Status:** forward-looking strategy + record of the seam work already done on
> `master` (2026-06-10). Source of truth for existing behavior is the Python code
> under `backend/app/`. Current TS artifacts live under `packages/protocol/` and
> `control-plane/`; neither owns existing business commands or writes.
>
> Companions: [`MODULES.md`](MODULES.md),
> [`MODULE_DEVELOPMENT_GUIDE.md`](MODULE_DEVELOPMENT_GUIDE.md),
> [`TS_MIGRATION_ROADMAP.md`](TS_MIGRATION_ROADMAP.md) (staged plan + PilotDeck/Hermes absorption),
> [`../decisions/0007-plugin-module-architecture.md`](../decisions/0007-plugin-module-architecture.md),
> [`../decisions/0010-credential-channel-isolation.md`](../decisions/0010-credential-channel-isolation.md).

---

## 1. Position: Python remains the authority — for now

The FastAPI/PostgreSQL backend under `backend/` (`backend/app/` for application
code) is, and remains, the
**single source of business authority**. Every command (memory write, proposal
apply, run execution, policy enforcement, credential brokering) is decided and
executed in Python. The web client under `apps/web/`, the TypeScript control
plane under `control-plane/`, and the shared protocol package under
`packages/protocol/` are clients/entrypoints/contracts around that authority
until a bounded context is explicitly migrated. `control-plane` is now the
default client-facing API entrypoint; existing Python-owned routes still execute
in Python through the temporary legacy proxy.

This document does **not** authorize moving any command to TypeScript. It
prepares the codebase so that such a move can later happen **one bounded context
at a time, safely**, and records the preparation that has already shipped.

Nothing here changes runtime behavior. The seams described in §3 are additive:
public facades and interface-only ports over the existing concrete services.

## 2. Why prepare now (without migrating)

The boundaries snapshot documents the obstacles that make a TS migration — or
any module extraction — risky today:

1. **Empty public surfaces.** Until recently no module published an intentional
   `__init__.py`; callers reached into each other's internal submodules, so any
   internal move was a breaking change everywhere.
2. **Few real ports.** Only `jobs.QueueService`, `providers.ProviderAdapter`,
   `runtimes.BaseRuntimeAdapter`, and `memory.MemoryProvider` were protocol
   seams. Everything else bound to concrete classes, so a TS (or fake)
   implementation had nowhere to plug in.
3. **Concrete/ad-hoc seams: now closed (2026-06-10).** The static import guard
   detects no obvious package cycles, and the formerly ad-hoc dispatch points all
   have explicit Python registries wired through `app.modules.registry`: scheduler
   lifecycle (`SchedulerRegistry`), job handlers (`JobHandlerRegistry`),
   space-created hooks (`SpaceCreatedHookRegistry`), run-finalized hooks
   (`RunFinalizedHookRegistry`), adapter/intent routing (`app.router`), and
   proposal apply dispatch (`app.proposals.applier_registry.ProposalApplierRegistry`
   — proposal-owning modules register appliers via `proposal_appliers.py` hooks;
   proposal target ownership is explicit before any TS module can own a proposal
   type). All Python-only; no ownership moved.

A TS migration that began before these were addressed would have to translate
files across cycle boundaries simultaneously — the failure mode this strategy
exists to avoid (§8).

## 3. The seam layer that has shipped

The following migration-oriented seams now exist. They are **interface and
re-export only**; the concrete Python services remain the sole implementation
and authority.

### 3.1 Public module facades (`__init__.py`)

Each of these modules now re-exports — and only re-exports — the symbols other
modules already imported from it, so callers depend on the module's public
surface rather than its internal file layout:

`auth`, `runs`, `memory`, `providers`, `proposals`, `policy`, `credentials`,
`capabilities`, `activity`, `projects`, `runtimes`.

Two of them — **`memory`** and **`runs`** — use a lazy (PEP 562 `__getattr__`)
facade rather than eager re-export: `memory` is still the documented import-cycle
hub, and `runs` (whose `tasks` and `runtimes` cycles are now both inverted) keeps
the lazy form so importing the facade never pulls its large service graph at
import time. Lazy resolution imports the exact submodule a direct
`from app.<mod>.<sub> import X` would, only on first attribute access, so the
public surface is available with **zero** new import-time edges and no change to
load order or behavior. The other facades re-export eagerly (their submodules
have no cycle back to themselves).

Call sites across the backend were migrated to the facade form
(`from app.runs import RunService` instead of `from app.runs.run_service import
RunService`) **only where mechanically safe** — i.e. where the imported names are
all published by the facade and collapsing the import path introduces no new
import-time risk.

### 3.2 Interface-only ports

Two new structural ports were extracted over existing concrete services. Each is
a `typing.Protocol` (`runtime_checkable`); the concrete class already satisfies
it structurally, so **no change to the implementation was required**:

| Port | File | Authority (unchanged) | Re-exported from |
|---|---|---|---|
| `ContextBuilderPort` | `memory/ports.py` | `memory/context_builder.py` `ContextBuilder` | `app.memory` |
| `PolicyPort` | `policy/ports.py` | `policy/gateway.py` `PolicyGateway` | `app.policy` |
| `RuntimeEventSink` | `runtimes/ports.py` | `runs/runtime_bridge.py` `RunEventRuntimeSink` (→ `runs/events.py`) | `app.runtimes` |
| `RuntimeProcessRegistry` | `runtimes/ports.py` | `runs/runtime_bridge.py` `RunProcessRegistryAdapter` (→ `runs/process_registry.py`) | `app.runtimes` |

These join the four pre-existing ports (`QueueService`, `ProviderAdapter`,
`BaseRuntimeAdapter`, `MemoryProvider`). They let callers type against the seam
and let tests substitute fakes (`tests/support/fake_context_builder.py`,
`tests/support/fake_policy.py`; contracts in `tests/contracts/`) without a
database. They are the natural insertion points for a future TS-backed
implementation behind a protocol/host boundary.

The two `runtimes` ports point the *other* way: they are how the lower-level
`runtimes` package emits run evidence and registers subprocess handles without
importing `app.runs` (the `runs` ↔ `runtimes` cycle is inverted; `runs` owns the
implementations and injects them via `RuntimeExecutionContext`). Python-only —
no runtime or run authority moved.

## 4. Phase 1: Shared Protocol Foundation

The first TypeScript migration artifact has shipped: **`packages/protocol`**, a
shared, framework-free package of wire contracts (DTOs + command/event envelopes).
See [`TS_PROTOCOL_FOUNDATION.md`](TS_PROTOCOL_FOUNDATION.md).

- `packages/protocol` is the **first TS migration artifact** in the repo. It
  contains schemas and types only (Zod + `z.infer`), with `zod` as its sole
  runtime dependency.
- **No business authority moved.** Commands are contracts, not handlers; events
  are contracts, not an event bus. Nothing in the package executes, routes to
  Python, or decides anything. Python remains the sole authority (§1, §8).
- **No dual command ownership.** Defining a `StartRun`/`ApproveProposal` envelope
  shape does not create a second decider for those commands — there is still
  exactly one (Python). The package describes the message; it does not own the
  command.
- DTO field names mirror the Python API JSON (snake_case) and are conservative
  subsets of existing `*Out` models — no new product model.
- **Next possible phases** (not part of this task): introduce the first low-risk
  TS-owned read-only module, preferably catalog-backed data. The vendor-neutral
  `model_api` runtime work is already complete in Python and did not move command
  authority. No local-host, desktop, mobile, plugin, MCP, or CLI-runner work is
  in this phase.

## 5. Phase 2: TS Control Plane Foundation

The second TypeScript migration artifact has shipped: **`control-plane`**
(`@agent-space/control-plane`), a small Fastify service that is the **default
client-facing TypeScript control plane** and the host for TS server features. See
[`TS_CONTROL_PLANE_FOUNDATION.md`](TS_CONTROL_PLANE_FOUNDATION.md). (It was
initially prototyped as `gateway-ts`; that name is gone.)

- The **control plane is the default client-facing TS API service** — a client-facing
  entrypoint and TS server-module host, not a temporary gateway. The **`gateway`
  module inside it is permanent** (the entry/routing layer: request context +
  route registration). It serves TS-owned routes (`/health`,
  `/api/v1/control-plane/health`, `/api/v1/control-plane/features`).
- The **legacy Python proxy is temporary** (`src/legacy/`). It proxies everything
  under `/api/v1/*` the control plane does not own, verbatim, to Python — and may
  be deleted in the future once those endpoints are owned by control-plane modules
  or retired. The control-plane service itself remains.
- **Current behavior is proxy-first.** Any path the control plane does not
  explicitly own falls through to the Python backend (method, path, query, body,
  safe headers preserved). Introducing the control plane changes no endpoint's
  behavior.
- **Python remains the authority** for existing business writes and commands. The
  control plane makes no business decision, holds no database, and applies no
  policy/memory/proposal/run logic. The `x-agent-space-control-plane: ts` marker
  is trace metadata, not trust.
- **New TS features should be added as explicit control-plane modules** after this
  phase — behind explicit control-plane-owned routes, advertised in
  `/api/v1/control-plane/features`. The default for any unclaimed path stays
  "proxy to Python." The internal module structure (gateway route registry,
  request context, error envelope, `src/modules/<module_name>/` layout) was
  normalized in Phase C — see
  [`CONTROL_PLANE_MODULE_CONVENTION.md`](CONTROL_PLANE_MODULE_CONVENTION.md).
  Phase C moved no business authority to TypeScript.
- **Command authority migration requires an explicit per-command decision** (the
  §8 invariants). It is *not* performed here: no command is handled in TS, and no
  command has dual ownership.
- **Local-host remains deferred.** No local-host, desktop, mobile, plugin, MCP, or
  CLI-runner code is introduced in this phase.
- Wired directly into the **dev / test / prod** compose files (no optional
  overlay): apps/web calls same-origin `/api` and dev/test Vite proxying routes
  that traffic through the control plane (`:8010` in dev, `:8110` in test), while
  prod points nginx `/api` at the control plane with Python behind the legacy
  proxy (Python not exposed directly). Python stays present as the legacy
  authority in every environment.

## 6. Recommended next phase

The modularization closeout verifies the Python backend boundaries needed before
any authority split: scheduler, job, space-created, run-finalized, routing,
runtime/provider, and proposal-applier dispatch are all explicit registries or
ports. No business authority has moved to TypeScript.

The next recommended phase is:

1. Add the first TS-owned module only for a low-risk read-only surface, preferably
   catalog-backed data (`catalog/` definitions exposed through an explicit
   control-plane route).
2. Keep all existing commands, writes, policy decisions, proposal approval/apply,
   runs, credentials, jobs, schedulers, database migrations, and model/provider
   invocation authority in Python until a later per-command migration decision.

## 7. What can be introduced after that

Once a bounded context has a clean facade + port, a TS layer can be introduced
*beside* Python in this order, still without moving authority until the final
cut-over of that one context:

1. **A protocol definition** — a versioned wire contract (e.g. JSON-RPC / typed
   schema) for one bounded context's commands, generated from or kept in lockstep
   with the Python schemas (`app/schemas.py`, the per-module `schemas.py`).
2. **A TS caller/adapter behind an explicit boundary** — it *calls* the Python
   authority over that protocol. It owns no business decision; it is a typed
   client/adapter.
3. **Control-plane routing** — a routing/edge layer that can direct a command either to the
   Python authority or (later, per context) to a TS implementation.

Only after a context's protocol, host, and gateway routing are proven does that
*single* context's authority move to TS. Every other context still resolves to
Python.

## 8. Invariants for the migration

These are binding for any future migration work:

1. **No command may have dual authority during migration.** At every moment a
   given command (memory write, proposal apply, run execute, policy enforce, …)
   is decided in **exactly one** place — Python *or* TS, never both. A gateway
   may *route*, but it must route each command to one authority. Shadow/compare
   modes must be read-only and clearly non-authoritative.
2. **Migrate by bounded context / command, not by file translation.** The unit
   of migration is a whole command or bounded context behind a port — not a
   line-by-line rewrite of a `.py` into a `.ts`. Translating files individually
   would reproduce today's import cycles across the language boundary and create
   exactly the dual-authority hazard invariant (1) forbids.
3. **A context may not be migrated until it has a facade + port.** No public
   surface or no seam ⇒ not ready. Extract the seam first (as `ContextBuilderPort`
   and `PolicyPort` were), prove it with a fake and a contract test, *then*
   consider migration.
4. **Credential-channel isolation (ADR 0010) survives the migration.** Whatever
   process decides a command, secrets reach a runtime only through the sanctioned
   channel — no provider/API key in a CLI subprocess env. A TS host is bound by
   the same rule.
5. **Cross-context writes still go through the proposal / activity flow** (B10 /
   B24 / B9 / B12). A TS host does not get a side door into memory or knowledge.

## 9. Order of contexts (suggested, not committed)

A reasonable extraction order follows decoupling readiness, lowest-risk first:

- **Ready / low-risk:** `providers` (clean port already), `credentials`,
  `capabilities`, `projects`, `activity` — small, cohesive, now faced.
- **Medium:** `policy` (now has `PolicyPort`), `proposals` (the
  `ProposalApplierRegistry` makes proposal-type apply ownership explicit and
  module-registered — a prerequisite for any future TS module owning a proposal
  type; approval/apply authority itself is still Python), `runs` (facade; both
  documented cycles are now inverted, Python-only with no authority moved — the
  `runs`↔`runtimes` cycle via `app.runtimes.ports` implemented by
  `app.runs.runtime_bridge`, and the `runs`↔`tasks` cycle via the runs-owned
  `app.runs.lifecycle_hooks.RunFinalizedHookRegistry` with the tasks-owned
  `task_evaluation_bridge` hook registered through the module registry; the
  dependency direction is `tasks -> runs` facade only).
- **Last:** `memory` — the cycle hub; only after its inbound product coupling
  (`intake`, `knowledge`, `evolution`, `agents`, `sessions`) is inverted per the
  boundaries-doc cleanup. `ContextBuilderPort` and `MemoryProvider` are the
  beachhead.

This ordering is advisory; the binding rules are §8.
