# Module: Activity Inbox

## Status
**IMPLEMENTED** — model, service, and API routes live in `app/activity/`.

## Purpose
Raw-input intake layer (L0). Everything entering the system lands as an `ActivityRecord` first — never directly as memory. External input must enter Activity before it can become memory.

## Owns
- `ActivityRecord` model
- `ActivityService` (CRUD, status transitions, source trust inference)
- Activity API routes
- Activity inbox UI (`ActivityInboxPage.tsx`)

## source_kind / source_trust Values

`source_kind` values: `user_capture`, `chat_message`, `user_input`, `manual`, `run_event`, `system_event`, `workspace_event`, `agent_run`, `task_log`, `external_chat`, `web_capture`, `file_import`, `external_source`, `imported_chat`, `agent_inferred`

Default `source_trust` by kind:
- `user_capture`, `chat_message`, `user_input`, `manual` → `user_confirmed`
- `run_event`, `system_event`, `workspace_event`, `agent_run`, `task_log` → `internal_system`
- `external_chat`, `web_capture`, `file_import`, `external_source`, `imported_chat` → `untrusted_external`
- `agent_inferred` → `agent_inferred`
- Unknown/empty → `untrusted_external`

If `ActivityRecord.source_trust` is already set to a valid enum value, that value wins.

## Key Model

```
ActivityRecord:
  id, space_id, user_id, workspace_id, agent_id
  source_kind, source_trust, activity_type, title, content
  source_run_id, source_task_id, source_session_id, source_url
  subject_user_id
  status (raw|processed|proposals_generated|archived)
  lifecycle_status, consolidation_status
  payload_json, occurred_at, created_at, updated_at
```

## API Routes

```
POST   /api/v1/activity                    — ingest
GET    /api/v1/activity                    — list (filter: source_type, status, workspace)
GET    /api/v1/activity/{id}
PATCH  /api/v1/activity/{id}/review        — mark as reviewed (status-only; no proposals)
PATCH  /api/v1/activity/{id}/archive
POST   /api/v1/activity/{id}/consolidate   — run consolidation for this activity only (no body)
```

Batch / explicit ids: `POST /api/v1/memory/consolidation/run` with optional `activity_ids` and `batch_limit`.

## Flow

```
raw input → ActivityRecord (status=raw, source_trust assigned)
    → POST /activity/{id}/consolidate (or batch consolidation run)
        → classifier → MemoryCandidateValidator → MemoryProposalProducer
        → reviewable Proposals created with provenance_entries
    → user approves proposals → ProposalApplyService writes MemoryEntry
    → ActivityRecord consolidation_status updated
```

## Invariants
- `ActivityRecord` is L0 raw event layer; it is not active Memory
- ActivityRecords become memory only through the Proposal → ProposalApplyService path
- `agent_inferred` activities cannot produce active semantic memory or policy without explicit user accept
- `source_activity_id` set on all Proposals generated from an ActivityRecord
- Consolidation is idempotent: duplicate proposals are blocked by `proposal_dedupe_key`

## Related Files
- `core/backend/app/models.py`
- `core/backend/app/activity/service.py`
- `core/backend/app/activity/api.py`
- `core/backend/app/memory/consolidation/service.py`
- `frontend/src/modules/activity/ActivityInboxPage.tsx`

## Related Decisions
- [0003-memory-proposal-flow.md](../decisions/0003-memory-proposal-flow.md)
