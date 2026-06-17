# Module: Activity

## Status
**IMPLEMENTED** — see `server/src/modules/activity/` and `modules/activity-inbox.md` for full detail.

## Purpose
Intake boundary for raw inputs. Nothing bypasses this layer into active memory.

## Owns
- `ActivityRecord` model
- `ActivityService`
- `/api/v1/activity` routes
- Activity → proposal pipeline

## Key Model

```
ActivityRecord:
  id, space_id, user_id, workspace_id, agent_id
  source_type (user_input|imported_chat|web_capture|file_import|agent_run|task_log|manual)
  title, content
  source_run_id, source_task_id, source_session_id, source_url
  status (raw|processed|proposals_generated|archived)
  metadata_json, created_at, updated_at
```

## Invariants
- Raw input always creates an ActivityRecord first
- ActivityRecords go through the proposal workflow before becoming memory
- `source_activity_id` set on all derived `memory_update` proposals

## Related Files
- `server/src/modules/activity/`
- `server/migrations/`

## Related Decisions
- [0003-memory-proposal-flow.md](../decisions/0003-memory-proposal-flow.md)
