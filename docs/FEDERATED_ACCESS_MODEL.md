# Federated Access Model (Deferred)

Status: **federation deferred** — local SourcePointer metadata API exists; no remote fetch.

## Scope

Federated access would let a local deployment hold a **pointer** to content that remains
authoritative on a **remote source instance**. Only local `SourcePointer` metadata is
implemented; remote fetch, sync, and cross-instance auth are not implemented.

## Principles

1. **Source instance is source of truth** — content and authorization decisions live at the origin.
2. **Local instance stores pointer metadata only** — SourcePointer metadata must never contain raw source content.
3. **Remote fetch requires source-side authorization** — tokens, trust chains, and revocation are future work.
4. **SourcePointer does not grant reads** — `access_mode=federated` is an intent label until grants and
   `memory.cross_space_read` (or successor domains) are explicitly implemented with policy checks.

## Local HTTP API

`/api/v1/source-pointers` manages local metadata only. It does not validate remote
instances, fetch remote content, sync updates, or authorize source-side reads.

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
