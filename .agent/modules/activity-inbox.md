# Module: Activity Inbox

## Status
**IMPLEMENTED** — model, service, and API routes live in `app/activity/`.

## Purpose
Raw-input intake layer. Everything entering the system lands as an `ActivityRecord` first — never directly as memory.

## Owns
- `ActivityRecord` model
- `ActivityService` (CRUD, status transitions, proposal generation)
- Activity API routes
- Activity inbox UI (`ActivityInboxPage.tsx` — stub)

## source_type Values
`user_input` | `imported_chat` | `web_capture` | `file_import` | `agent_run` | `task_log` | `manual`

## Key Model

```
ActivityRecord:
  id, space_id, user_id, workspace_id, agent_id
  source_type, title, content
  source_run_id, source_task_id, source_session_id, source_url
  status (raw|processed|proposals_generated|archived)
  metadata_json, created_at, updated_at
```

## API Routes

```
POST   /api/v1/activity               — ingest
GET    /api/v1/activity               — list (filter: source_type, status, workspace)
GET    /api/v1/activity/{id}
PATCH  /api/v1/activity/{id}/process
PATCH  /api/v1/activity/{id}/archive
POST   /api/v1/activity/{id}/proposals — generate memory update proposals
```

## Flow

```
raw input → ActivityRecord (status=raw)
    → POST /activity/{id}/proposals → memory update proposals created
    → ActivityRecord (status=proposals_generated)
    → user approves proposals → Memory created
    → ActivityRecord (status=processed)
```

## Invariants
- ActivityRecords never become memory directly — always via proposals
- `source_activity_id` set on all proposals generated from an ActivityRecord

## Related Files
- `core/backend/app/models.py`
- `core/backend/app/activity/service.py`
- `core/backend/app/activity/api.py`
- `frontend/src/modules/activity/ActivityInboxPage.tsx`

## Related Decisions
- [0003-memory-proposal-flow.md](../decisions/0003-memory-proposal-flow.md)
