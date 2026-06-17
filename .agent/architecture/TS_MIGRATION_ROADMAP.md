# TS Migration Roadmap

> **Status:** current migration status and future backlog, refreshed
> 2026-06-16. This document is intentionally compact. The binding migration
> rules live in [`TS_MIGRATION_STRATEGY.md`](TS_MIGRATION_STRATEGY.md). Current
> route/context ownership lives in
> [`TS_CONTROL_PLANE_OWNERSHIP.md`](TS_CONTROL_PLANE_OWNERSHIP.md). Focused
> commands live in [`../COMMANDS.md`](../COMMANDS.md).

The TypeScript control plane is the default client-facing API entrypoint. The
Python backend remains the authority for schema migrations and every context or
command not explicitly owned by a control-plane module. DB-persisted API-key
storage remains disabled/deferred because the canonical schema has no `api_keys`
table; the TS auth module owns the current feature-gated API-key responses.

The original migration rule still holds: a command has exactly one authority at
any time. Shadow/parity paths must be read-only.

## 1. Current Status

The core migration is mostly complete. The TypeScript control plane is fixed
authority for:

- providers/credentials;
- session-cookie identity, Google OAuth login/callback/config,
  `/auth/introspect`, `/auth/keys`, `/me`, `/me/spaces`, `/auth/logout`,
  `POST /spaces`, `GET /spaces/{id}`, `GET /spaces/{id}/members`,
- policy enforcement;
- public session commands and latest-summary reads;
- run create/read/execute/stop/finalization for the migrated `agent_run` path;
- chat turn orchestration and TS context assembly;
- memory read/proposal-create/read logging and accepted memory proposal apply;
- proposal review/apply orchestration with registered memory appliers and
  fail-closed unregistered proposal types;
- artifact list/get/export;
- runtime adapter catalog/spec semantics.

The old `CONTROL_PLANE_*_AUTHORITY` migration switches for moved contexts have
been collapsed from config, compose, and env templates. Remaining Python-owned
contexts are documented ownership boundaries, not env-flipped rollback paths.

The remaining work is cleanup and boundary closure, not a reason to build new
features in Python first.

## 2. Completed Migration Work

| Area | Completed status |
|---|---|
| Protocol/control-plane foundation | `packages/protocol`, `control-plane`, module convention, config snapshots, and the temporary Python fallback proxy are in place. |
| Stage 1: read-only TS beachhead | Catalog read routes, canonical model event contracts, and config diagnostics shipped. |
| Stage 2: TS edge capabilities | Run-event SSE edge, frontend-support read facades, and allowlist-gated notification webhooks shipped without moving existing business authority. |
| Phase 2: auth/spaces/identity | Session-cookie identity, Google OAuth login/callback/config, `/auth/introspect`, feature-gated `/auth/keys`, `/me`, `/me/spaces`, `/auth/logout`, space create/read/member/invitation routes, invitation accept, and deterministic space-created default seeds are TS-owned. DB-persisted API-key storage remains disabled because the canonical schema has no `api_keys` table. |
| Stage 3: providers/credentials/runtime adapters | Provider reads/commands/invocation, credential pools, rotation/cooldown, fallback chains, per-task provider policies, CLI credential login/brokering/audit, internal runtime ports, and the `RuntimeAdapterSpec` catalog are TS-owned. Hermes H1/H2 are implemented here; provider shadow compare was deleted. |
| Stage 4: run execution commands | `POST /runs/{id}/execute`, `PATCH /runs/{id}/stop`, the internal execute port, and the `agent_run` worker are TS-owned. Verified scope is managed API no-tool plus run-scope ephemeral CLI. |
| Stage 5: policy | Policy enforcement and durable policy audit are TS-owned. |
| Stage 6: sessions/chat/context/memory | Public session commands, latest summary read, assistant chat turn orchestration, chat context selection + snapshot persistence, full-run context preparation, memory list/get/search, public memory create/update/archive proposal creation, `/memory` read logging, and accepted memory proposal apply are TS-owned. |
| Phase 6: proposals/artifacts | Proposal list/get/accept/reject/egress-approval routes, proposal apply orchestration, the TS applier registry, registered memory appliers, and artifact list/get/export routes are TS-owned. Unregistered proposal types fail closed. |

For exact route ownership, DB grants, and fail-closed
guards, use [`TS_CONTROL_PLANE_OWNERSHIP.md`](TS_CONTROL_PLANE_OWNERSHIP.md).

## 3. Remaining Migration Cleanup

These items are about closing remaining Python-owned seams or deciding that a
context intentionally stays Python-owned. They are distinct from future feature
development.

Phase 2 auth/space edges are no longer listed as remaining cleanup: their
current client-facing routes are TS-owned, and API-key storage is a disabled
schema capability rather than a Python-retained migration seam.

| Area | Current owner | Cleanup decision needed |
|---|---|---|
| Python fallback proxy | Control-plane fallback to Python | The strict original migration metric is deleting `control-plane/src/pythonFallback/`. That requires every client-facing `/api/v1/*` route to be either TS-owned, explicitly retired, or intentionally served through a non-fallback Python boundary. |
| Context digest refresh / memory quality loops | Mixed | Runtime context preparation and batch activity consolidation are TS-owned. Digest refresh, source-monitoring producers, evolver, and remaining quality loops still need either TS implementations or explicit retirement before Python removal. |
| Session reflect and summary writes | Python sessions | Public session commands and latest-summary reads moved. `reflect` and `SessionCondenser.condense` remain Python-owned because they are not independent public migration blockers. |
| Memory quality/evolution | Mixed | Consolidation is TS-owned through the generic jobs/worker path. Source-monitoring producers, digest refresh, evolver, and remaining quality loops still need either TS implementations or explicit retirement. |
| Memory apply exceptions | Mixed | TS memory apply fails closed for run/grant egress-context proposals, workspace/agent-scope memory, active-policy private-placement overlay, and digest invalidation. These need either TS implementations or explicit Python-retained ownership. |
| Proposal target appliers outside memory/knowledge/tasks | Mixed | Proposal review/apply orchestration, memory appliers, knowledge appliers, and task follow-up appliers are TS-owned. Any remaining unregistered proposal type must either move with its owning context or stay fail-closed. |
| Product contexts not listed as TS-owned | Python | Schema migrations, workspace write flows, deployment, session reflection/condense, and explicitly listed memory quality tails remain Python-owned until a later decision. Activity, intake, knowledge, tasks, artifacts, jobs/schedulers, automations, daily reports, and backups are no longer Python-owned migration blockers. |

## 4. Future Feature Backlog

The items below are **not** required to declare the existing TS migration work
complete. They are new capabilities or runtime expansions.

| Future capability | Source / reason | Status |
|---|---|---|
| Full context engine | PilotDeck P3: prompt assembly, message projection, token budgeting, graduated compaction, overflow recovery | Not implemented. Build TS-native on top of migrated context/session/memory seams. |
| Channel adapters | PilotDeck P8: IM/email/channel ingestion with external-session mapping | Not implemented. Requires stable intake/evidence provenance and proposal boundaries. |
| Always-On governance | PilotDeck P9: trigger budgets and cooldowns | Not implemented. Future automation/policy vocabulary. |
| Self-hosted TS agent loop | PilotDeck P6: AgentSession / TurnRunner / AgentLoop for managed API runtimes with tools | Not implemented. Future runtime capability, separate from Stage 4 run execution migration. |
| Tool scheduler | PilotDeck P6: sequential/concurrent tool execution with observability | Not implemented. Belongs with self-hosted TS agent loop. |
| MCP client integration | PilotDeck P7 | Not implemented. `RuntimeToolBinding` remains the authorization surface. |
| Managed API with tools | Runtime expansion | Not implemented. Would become a third execution path beside CLI-with-tools and managed API no-tool. |
| CLI sandbox scope ladder | Former Stage 9: session/project working directories, repo worktree/coding path, real cancel for that path | Future runtime capability. The schema exists, but provisioning, serialization, GC, worktree diff-to-`code_patch`, and cancel verification are not built. Treat this as new work, not migration completion. |
| Provider privacy/compliance policy | Hermes H3: data-collection deny, provider allow/deny, required parameter rules | Not implemented. Add as space-scoped policy/provider-routing rules, not global config. |
| Durable apply rollback | Hermes H4: pre-apply snapshots and user-facing rollback | Not implemented. Future workspace/proposal-apply hardening. |

## 5. External Absorption Ledger

Implemented absorptions:

- P1 canonical model event contracts.
- P4 config snapshots and diagnostics.
- P5 control-plane SSE edge.
- H1/H2 provider resilience: credential pools, rotation/cooldown, per-turn
  fallback, per-auxiliary-task provider chains.
- H5 explicit grants principle in TS-owned run/provider paths.
- H6 allowlist-gated outbound notification/webhook egress.

Deferred absorptions:

- P2 per-session chat concurrency guard. Still conditional dogfooding debt; add
  only if real chat ordering issues appear.
- P3 full context engine.
- P6/P7 self-hosted agent loop, tool scheduler, MCP.
- P8/P9 channel adapters and Always-On governance.
- H3 provider compliance vocabulary.
- H4 durable rollback snapshots.

Explicitly rejected:

- PilotDeck-style secrets in YAML or `${ENV}` substitution.
- Global single-scope config that ignores `space_id`.
- Gateway-as-plugin/event-bus architecture.
- Hermes local `auth.json` credential pool state.
- Hermes media stack, batch RL trajectory generation, and external memory
  provider backends as MVP work.
- OpenAI-compatible API server as a planned stage.

## 6. Completion Criteria

The migration cleanup is complete when:

1. every moved command has one active authority and its old Python command path
   is guarded, retired, or a thin caller of that authority;
2. the control-plane DB role has only the grants needed by TS-owned contexts;
3. focused protocol/control-plane/backend verification is green;
4. any remaining Python-owned contexts are documented as intentional ownership,
   not accidental fallback;
5. the Python fallback proxy is either deleted or narrowed to a formally
   documented compatibility boundary.
