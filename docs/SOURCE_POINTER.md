# SourcePointer

Status: **implemented as metadata-only local provenance API**.

`SourcePointer` records that an object in one space references an object in another
space. It does not copy source content and does not grant read access to the source
space.

## Current API

Routes: `/api/v1/source-pointers`

| Method | Path | Boundary |
|---|---|---|
| `POST` | `/` | Caller must be an active member of both owner space and source space; source object must exist |
| `GET` | `/` | Caller sees pointers owned by the current space only |
| `GET` | `/{pointer_id}` | Caller must be in the owner space |
| `DELETE` | `/{pointer_id}` | Caller must be owner/admin in the owner space |

`owner_space_id` and `granted_by_user_id` are server-assigned from the authenticated
request context. Clients may only submit `source_space_id`, `source_object_type`,
`source_object_id`, `access_mode`, `expires_at`, and `metadata_json`.

## Metadata Rules

`metadata_json` is safe metadata only:

- max 16 KiB serialized JSON
- max depth 8
- max 256 object/list items
- max key length 128
- max string value length 2048
- content-bearing keys are rejected recursively
- grant-derived/personal-memory egress marker keys are rejected recursively

## Non-Goals

- SourcePointer does not activate `memory.cross_space_read`.
- SourcePointer does not bypass membership, visibility, or memory policy checks.
- SourcePointer does not implement federation, sync, remote fetch, or public publishing.
- SourcePointer does not persist raw memory text, summaries, context blocks, transcripts,
  patches, file content, or generated personal memory content.

`PersonalMemoryGrant` remains the explicit mechanism for allowing a shared-space run to
use a user's personal private memory as reasoning context.
