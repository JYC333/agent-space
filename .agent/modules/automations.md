# Module: Automations

## Status

Implemented: manual and scheduled triggers; targets `agent_run`,
`knowledge_retrieval_maintenance`, `context_ops_review_cycle`; optional project
binding for `agent_run`.

## Purpose

Automations are the user-facing objects that fire runs on demand (manual) or on
a cron schedule. Every automation-origin run goes through the same
enforce/preflight/policy path as a manual run — this is the roadmap red line for
Capability 6.

Scheduled fire failures emit a deduplicated, owner-private `operational_alert` Activity
record so unattended failures appear in Activity Inbox. Alert persistence is best-effort
and never replaces schedule advancement or the originating failure state.

Source post-processing is not an Automation trigger. Source-level
summaries, evidence extraction, proposal creation, item marking, and per-source
cursors are owned by the Sources module.

## Owns

- `automations` rows (name, agent, optional workspace/project, trigger, config).
- `automation_runs` fire audit rows (`trigger_type`, preflight snapshot,
  `trigger_context_json` when a target needs structured audit context).
- `automation_credential_grants` pre-authorization for unattended schedule
  fires; archiving revokes.
- Cron due state in `scheduler_tasks` for `task_type='automation'`.

## Trigger model

`trigger_type` is the enum of peer trigger kinds:

- `manual` — fired by a user via `POST .../fire`.
- `schedule` — cron in `config_json`; due state lives in `scheduler_tasks`
  (`task_type='automation'`, `next_run_at`/`last_run_at`); the
  `automation_scheduler` heartbeat sweeps `listDue` and fires. There is no
  per-automation registration into the scheduler — it is a poll/sweep model.
External/webhook triggers remain deferred (roadmap Capability 6).

## Project Binding

`project_id` is optional, `agent_run`-target only, and requires project writer
authority to bind. Fired runs carry the project, so run context pulls project
evidence/memory and outputs are project-attributed. Preflight fails closed if
the bound project was deleted.

Scheduled non-agent targets run as owner/admin operational work and save private
operational reports or packets according to each target's config. Agent-run
targets use the configured agent and optional configured prompt.

## Cross-Module Boundary

Sources materialization enqueues Sources-owned
`source_post_processing_event` jobs. Automations does not consume source item
deltas and does not own per-source cursors.

## Related Files

- `server/src/modules/automations/`
- `server/src/modules/projects/projectSourceRoutingService.ts`
- `server/src/modules/runs/finalizationService.ts`
- `server/src/modules/scheduler/`
- `apps/web/src/modules/automations/AutomationsPage.tsx`

## Related Architecture

- [PROJECTS.md](../architecture/PROJECTS.md)
- [Sources module](sources.md)
- [ROADMAP_AND_FUTURE_RISKS.md](../architecture/ROADMAP_AND_FUTURE_RISKS.md) — Capability 6
