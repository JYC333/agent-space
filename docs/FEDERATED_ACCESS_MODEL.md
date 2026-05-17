# Federated Access Model (Deferred)

Status: **documented only** — Phase 7B-1 adds local pointer metadata API; no remote fetch.

## Scope

Federated access lets a local deployment hold a **pointer** to content that remains
authoritative on a **remote source instance**. Phase 7B-1 adds a membership-gated local
`SourcePointer` HTTP API (metadata only); it does not implement remote fetch, sync, or
cross-instance auth.

## Principles

1. **Source instance is source of truth** — content and authorization decisions live at the origin.
2. **Local instance stores pointer + optional digest** — never raw source content in `source_pointers`.
3. **Remote fetch requires source-side authorization** — tokens, trust chains, and revocation are future work.
4. **SourcePointer does not grant reads** — `access_mode=federated` is an intent label until grants and
   `memory.cross_space_read` (or successor domains) are explicitly implemented with policy checks.

## HTTP API (Phase 7B-1)

Routes under `/api/v1/source-pointers`:

- **POST** — create pointer; caller must be a member of both `owner_space_id` and
  `source_space_id`. `granted_by_user_id` is set server-side from the authenticated user.
  `metadata_json` forbids raw-content keys at any nesting depth and enforces bounded safe
  metadata (byte/size/depth/item caps; tuple/set/bytes rejected at service layer). Does not
  validate or return source object content. SourcePointer does not grant read access.
- **GET** (list) — pointers for owner spaces the user belongs to; optional `owner_space_id`
  filter returns 403 when not a member.
- **GET** `/{id}` — metadata when user is a member of `owner_space_id` (source-space
  membership not required to view the pointer row).
- **DELETE** `/{id}` — admin/owner of `owner_space_id` only; hard-deletes pointer metadata.

## `access_mode` values (Phase 7A–7B)

| Mode | Phase 7A behavior |
|------|-------------------|
| `read` | Metadata only; no automatic read grant |
| `subscribe` | Deferred — future push/notification channel |
| `federated` | Deferred — future cross-instance fetch |

## Future requirements (not built)

- Distributed identity and instance trust
- Revocation and audit across instances
- Federation API and remote cache policy
- Cross-instance `source_instance_id` (optional metadata field may be added later)

## Related

- `docs/TARGET_VIEW_MODEL.md` — SourcePointer definition
- `docs/PUBLISH_PROJECTION.md` — public publication pipeline (also deferred)
- `.agent/architecture/POLICY_ENFORCEMENT_INVENTORY.md` — `memory.cross_space_read`
