# Module: Automations

## Status

Implemented: manual, scheduled, and internal-event triggers; targets
`agent_run`, `knowledge_retrieval_maintenance`, `context_ops_review_cycle`;
optional project binding with intake delta cursor for `agent_run`.

## Purpose

Automations are the user-facing objects that fire runs without a live user
action: on demand (manual), on a cron schedule, or on an internal intake event.
Every automation-origin run goes through the same enforce/preflight/policy path
as a manual run — this is the roadmap red line for Capability 6.

## Owns

- `automations` rows (name, agent, optional workspace/project, trigger, config).
- `automation_runs` fire audit rows (`trigger_type`, preflight snapshot,
  `trigger_context_json` with event payloads and the proposed intake watermark).
- `automation_credential_grants` pre-authorization for unattended (schedule and
  event) fires; archiving revokes.
- The intake delta cursor (`automations.cursor_json.intake_watermark`) and its
  fire-time computation (`intakeDelta.ts`) and commit (`intakeCursor.ts`).
- Event trigger config parsing and cooldown (`eventTrigger.ts`) and the
  `automation_intake_event` job handler (`intakeEventHandler.ts`).

## Trigger model

`trigger_type` is the enum of peer trigger kinds:

- `manual` — fired by a user via `POST .../fire`.
- `schedule` — cron in `config_json`; due state lives in `scheduler_tasks`
  (`task_type='automation'`, `next_run_at`/`last_run_at`); the
  `automation_scheduler` heartbeat sweeps `listDue` and fires. There is no
  per-automation registration into the scheduler — it is a poll/sweep model.
- `event` — internal intake event (`intake.items_materialized`). Never swept by
  the heartbeat (`next_run_at` stays NULL); fired by the jobs-worker handler
  when a scan materializes new items. `config_json.event` carries `type`,
  optional `source_connection_ids` allowlist, `min_new_items` (default 1), and
  `cooldown_seconds` (default 900) enforced against `scheduler_tasks.last_run_at`.
  Requires the `agent_run` target and a scope (project binding or explicit
  connection ids). External/webhook triggers remain deferred (roadmap
  Capability 6).

## Project binding and intake delta

`project_id` is optional, `agent_run`-target only, and requires project writer
authority to bind. Fired runs carry the project, so run context pulls project
evidence/memory and outputs are project-attributed. Preflight fails closed if
the bound project was deleted.

For project-bound (or connection-allowlisted) automations, each fire computes
the intake delta — items with `(created_at, id)` above the committed watermark,
capped by `intake_delta_limit` (default 25, max 100) — injects a structured
digest into the run instruction, and records the proposed watermark on
`automation_runs.trigger_context_json`. Run finalization commits the watermark
into `automations.cursor_json` only for succeeded runs, with a monotonic guard;
failed runs re-read the same delta. `skip_when_no_new_items` (default true for
event fires, false otherwise) skips run creation on an empty delta.

Delta scope resolution: `config_json.intake_source_connection_ids` when set,
falling back to `config_json.event.source_connection_ids` for event
automations, otherwise the connections actively bound to the automation's
project. The cursor is initialized to the scope's current watermark at create
time (no historical backlog replay) and re-initialized whenever the scope
changes on update (a stale watermark would silently skip or replay items).
Event fires are additionally skipped with reason `run_in_flight` while a
previous fire's run is still queued/running, because the uncommitted cursor
would re-deliver the same delta.

Cross-module note (B33): `runs/repository.ts` calls
`automations/intakeCursor.ts` from run finalization — the recorded product
boundary is "run success commits the automation intake watermark". The reverse
direction (automations → runs) already exists for fire; both are file-level
acyclic.

## Related Files

- `server/src/modules/automations/`
- `server/src/modules/intake/automationEventEmitter.ts`
- `server/src/modules/intake/evidenceProjectLinker.ts`
- `server/src/modules/runs/finalizationService.ts`
- `server/src/modules/scheduler/`
- `apps/web/src/modules/automations/AutomationsPage.tsx`

## Related Architecture

- [PROJECTS.md](../architecture/PROJECTS.md)
- [Intake module](intake.md)
- [ROADMAP_AND_FUTURE_RISKS.md](../architecture/ROADMAP_AND_FUTURE_RISKS.md) — Capability 6
