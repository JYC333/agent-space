# Module: Activity Inbox

## Status
**IMPLEMENTED** — model, service, and API routes live in `server/src/modules/activity/`.

## Purpose
Raw-input intake layer (L0). Everything entering the system lands as an `ActivityRecord` first — never directly as memory. External input must enter Activity before it can become memory.

## Owns
- `ActivityRecord` model
- `ActivityService` (CRUD, status transitions, source trust inference)
- Activity API routes
- Activity inbox UI (`ActivityInboxPage.tsx`)

## source_kind / source_trust Values

Canonical `source_kind` / `activity_type` values: `user_capture`,
`chat_message`, `external_chat`, `file_import`, `web_capture`, `run_event`,
`workspace_event`, `system_event`, `external_source`, and `intake`. Legacy input
aliases such as `user_input`, `manual`, `agent_run`, `task_log`,
`imported_chat`, `file_capture`, and `voice_capture` are normalized at ingest.

Default `source_trust` by kind:
- `user_capture`, `chat_message`, `external_chat`, `file_import` → `user_confirmed`
- `run_event`, `system_event`, `workspace_event`, `intake` → `internal_system`
- `web_capture`, `external_source` → `untrusted_external`
- Unknown/empty → `untrusted_external`

If `ActivityRecord.source_trust` is already set to a valid enum value, that value wins.

## Key Model

```
ActivityRecord:
  id, space_id, user_id, workspace_id, agent_id
  source_kind, source_trust, activity_type, title, content
  source_run_id, source_task_id, source_session_id, source_url
  subject_user_id
  status (raw|processed|proposals_generated|failed|archived)
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
        → Memory retrieval create-safety pre-dedupe
        → classifier → MemoryCandidateValidator → MemoryProposalProducer
        → reviewable Proposals created with provenance_entries
    → user approves proposals → ProposalApplyService writes MemoryEntry
    → ActivityRecord status updated
```

## Invariants
- `ActivityRecord` is L0 raw event layer; it is not active Memory
- ActivityRecords become memory only through the Proposal → ProposalApplyService path
- `agent_inferred` activities cannot produce active semantic memory or policy without explicit user accept
- Activity-derived proposals carry Activity provenance in `provenance_entries`
  and may include `source_activity_id` as a pending-proposal compatibility
  shortcut
- Consolidation is idempotent: visible Memory duplicate checks run before proposal
  creation, and duplicate proposals are blocked by `proposal_dedupe_key`

## Related Files
- `server/migrations/`
- `server/src/modules/activity/`
- `server/src/modules/memory/`
- `apps/web/src/modules/activity/ActivityInboxPage.tsx`

## Related Decisions
- [0003-memory-proposal-flow.md](../decisions/0003-memory-proposal-flow.md)
