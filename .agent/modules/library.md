# Module: Library

## Status

**IMPLEMENTED** — frontend reading surface lives in
`apps/web/src/modules/library/`. Backend reads are served by Sources item and
post-processing endpoints under `/api/v1/sources/items*` and
`/api/v1/sources/briefings*`.

## Purpose

Library is the per-user reading home for Sources-derived content inside a
space. It owns the user experience for source item streams, Library-level
digests, and the single-item reader route, while Sources continues to own the
source pipeline, subscription model, data model, and API.

## Owns

- Library shell (`/library`): Shell scene sidebar navigation for reading
  sections; defaults to `/library/items`.
- Per-user item stream (`/library/items`): source-scanned items from sources
  the current user follows, plus manually saved unconnected URLs created by the
  current user. Library uses `source_item_user_states.library_status` and
  `source_item_user_states.read_status`; absent state rows render as
  `new/unread`.
- Item type views under All Items:
  - `/library/items/articles`
  - `/library/items/emails`
  - `/library/items/videos`
  - `/library/items/podcasts`
  - `/library/items/pdfs`
  These are soft read-time filters over source metadata, URL/domain hints, and
  MIME/content-type hints. They are not source import requirements and do not
  create hard schema categories.
- Library digests (`/library/digests`, `/library/digests/:connectionId/:date`):
  one followed source connection x local-day entry per successful
  post-processing output group when the current user's subscription has
  `digest_enabled=true`, with rendered digest markdown, item decision groups,
  per-item summaries, and links into the item reader.
- Single-item reader routes:
  - `/library/items/:itemId`
  - `/library/digests/:connectionId/:date/items/:itemId`

## Does Not Own

- Source connection configuration, scan schedules, or post-processing rules
  (`modules/sources.md`).
- Source recommendation/subscription decisions (`modules/sources.md`).
- Activity Inbox notification lifecycle (`modules/activity-inbox.md`).
- Sources reader annotation storage/APIs; Library composes the shared reader UI
  with Sources-owned annotation endpoints.

## Flow

```
source_connection_user_subscriptions (subscribed + digest_enabled)
  + source_post_processing_runs/artifacts/decisions
  -> GET /api/v1/sources/briefings
  -> /library/digests
  -> /library/digests/:connectionId/:date detail
  -> /library/digests/.../items/:itemId reader

source_connection_user_subscriptions (subscribed + library_enabled)
  + source_items
  + source_item_user_states
  -> GET /api/v1/sources/items
  -> /library/items or /library/items/:type
  -> /library/items/:itemId reader
```

Activity Inbox points into Library through daily aggregate rows with
`activity_records.aggregate_key = source:briefing:<source_connection_id>:<date>`.
Those rows contain only counts and a short preview; full digest and item
content stay in the Library/Sources read model.

Source recommendation inbox rows point back to Sources Pending. Reviewing or
archiving the Activity row only clears the notification pointer; Follow,
Dismiss, Mute, and Unsubscribe are stored in
`source_connection_user_subscriptions`.

## Related Files

- `apps/web/src/modules/library/`
- `apps/web/src/components/reader/`
- `server/src/modules/sources/postProcessing/`
- `server/migrations/0001_baseline.sql`

## Related Docs

- [activity-inbox.md](activity-inbox.md)
- [sources.md](sources.md)
