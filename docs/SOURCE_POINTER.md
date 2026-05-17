# SourcePointer

## Purpose

A `SourcePointer` is a lightweight cross-space provenance record that points to content
in another space without copying it. It records that an object in one space references
an object in another space — it does not grant any read access to that other space.

```
SourcePointer = provenance metadata only.
SourcePointer does not grant access.
```

---

## Data Model

### `source_pointers`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key |
| `owner_space_id` | UUID FK spaces | The space that owns this pointer (referencing side) |
| `source_space_id` | UUID FK spaces | The space being referenced |
| `source_object_type` | TEXT | Type of the referenced object (e.g. `memory`, `artifact`) |
| `source_object_id` | UUID | ID of the referenced object in `source_space_id` |
| `access_mode` | TEXT | Intent label: `read \| subscribe \| federated` — not an access grant |
| `granted_by_user_id` | UUID | Server-assigned from authenticated user on create; not client-writable |
| `metadata_json` | JSON | Bounded safe metadata only; content-bearing keys rejected |
| `created_at` | TIMESTAMP | Creation time |

**`access_mode` values are intent labels only.** They do not activate cross-space reads,
do not implement federation, and do not enable public publishing. All reads still require
membership, visibility, and policy checks in the source space.

---

## Metadata Safety Rules

`metadata_json` is bounded safe metadata only. The service layer enforces:

- **Content-bearing key rejection:** keys matching content-bearing names are rejected
  recursively (case-insensitive key match; string values are not scanned).
- **Byte cap:** 16 KiB UTF-8 JSON maximum.
- **Depth limit:** maximum depth 8.
- **Item limit:** ≤ 256 total dict/list items.
- **Key length:** ≤ 128 characters.
- **String length:** ≤ 2048 characters per value.
- **Type restriction:** only JSON-compatible scalars, dicts, and lists. Tuples, sets,
  and bytes are rejected at the service layer.

**Grant-derived metadata is blocked for non-personal owner spaces.** Keys indicating
grant-derived content (`derived_from_personal_memory`, `personal_memory_grant_ids`,
`raw_private_memory_included`, `personal_summary_persisted`) are rejected in
`metadata_json` when `owner_space_id` is not a personal space.

---

## API

All endpoints are under `/api/v1/source-pointers`.

| Method | Path | Access requirement |
|---|---|---|
| `POST` | `/` | Member of both `owner_space_id` and `source_space_id` |
| `GET` | `/` | Member of `owner_space_id` |
| `GET` | `/{pointer_id}` | Member of `owner_space_id` |
| `DELETE` | `/{pointer_id}` | Admin or owner role in `owner_space_id` |

**Membership-gated:** All endpoints require verified space membership. There is no
public or unauthenticated access to SourcePointer data.

**`granted_by_user_id`** is server-assigned from the authenticated user on create.
It is not present in the request body (`extra=forbid` on request schema).

---

## What SourcePointer Does Not Do

- **Does not grant read access.** A SourcePointer to a memory in another space does not
  allow the `owner_space` to read that memory. `memory.cross_space_read` remains
  deny-by-default.
- **Does not bypass `can_read_memory()`.** All reads require membership, visibility,
  and policy checks in the source space regardless of any SourcePointer.
- **Does not implement federation.** Multi-deployment cross-instance federation is
  explicitly deferred.
- **Does not enable public publishing.** `visibility=public` is not implemented.
- **Does not carry grant-derived content.** SourcePointer rows never store raw memory
  text, generated personal summaries, or personal context blocks.

---

## Relationship to PersonalMemoryGrant

`PersonalMemoryGrant` is the separate, explicit mechanism for allowing a shared-space
run to use a user's personal-space private memory as reasoning context. SourcePointer
and PersonalMemoryGrant are independent:

- A SourcePointer to personal memory does not grant run access.
- A PersonalMemoryGrant does not create a SourcePointer.
- Grant-derived content cannot be written to SourcePointer metadata for non-personal targets.

See `docs/PERSONAL_MEMORY_GRANT.md` for the PersonalMemoryGrant model.

---

## Future Items (Deferred)

- **Federation / cross-instance SourcePointer:** multi-deployment federated pointer
  resolution is explicitly deferred. See `docs/FEDERATED_ACCESS_MODEL.md`.
- **Cross-space read activation:** explicit grants + federation + policy design required
  before `memory.cross_space_read` can be enabled for any source pointer.
- **`visibility=public` publish pipeline:** deferred. See `docs/PUBLISH_PROJECTION.md`.

---

## See Also

- `docs/TARGET_VIEW_MODEL.md` — SourcePointer in context of the full target model
- `docs/PERSONAL_MEMORY_GRANT.md` — explicit grant mechanism
- `docs/FEDERATED_ACCESS_MODEL.md` — federation (deferred)
- `docs/POLICY_AND_PRIVACY_BOUNDARIES.md` — `memory.cross_space_read` policy status
- `core/backend/app/source_pointers/` — implementation
- `core/backend/tests/contracts/test_source_pointer_api.py`
- `core/backend/tests/invariants/test_source_pointer_access_boundary.py`
