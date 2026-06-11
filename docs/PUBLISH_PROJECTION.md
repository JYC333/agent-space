# Publish Projection (Deferred)

Status: **documented only** — no publish apply path (Phase 7B-1 adds SourcePointer metadata API only).

## Purpose

PublishProjection is the future pipeline by which a user or space intentionally publishes
internal content as a redacted, public-facing artifact. Publication must always be
proposal-gated and audit-trailed.

## Pipeline (target)

```
Internal source object
  → publish proposal (reviewed)
  → redaction / transformation
  → public artifact (new object)
  → external / public channel
  → SourcePointer provenance back to source (metadata only)
```

## Future publish proposal payload shape

```json
{
  "source_object_type": "memory",
  "source_object_id": "<uuid>",
  "target_visibility": "public",
  "redact_fields": ["selected_user_ids", "sensitivity_level"],
  "transform": "summary_only"
}
```

`target_visibility: "public"` is illustrative for the future model. **Phase 7A does not
enable `visibility=public`**, public routes, or proposal apply for type `publish`.

## Proposal type `publish`

Registered as **future / deferred** only. Executable accept types remain:
`memory_create`, `memory_update`, `memory_archive`, `policy_change`, `code_patch`
(see `app.proposals.ProposalApplyService.supported_types()`).

## Not implemented

- `visibility="public"` on memories or artifacts
- Publish proposal create/accept/apply
- Public artifact storage or external URLs
- Automatic SourcePointer creation on publish (may be added when apply exists)

Phase 7B-1 SourcePointer API may record provenance manually (metadata only; `granted_by_user_id`
server-assigned; bounded safe `metadata_json` with recursive forbidden-key and size caps).
SourcePointer does not grant read access or copy source content. It does not implement publish apply.

## Related docs

- `docs/TARGET_VIEW_MODEL.md` — PublishProjection concept
- `docs/SPACE_MODEL.md` — visibility and private memory rules
- `docs/FEDERATED_ACCESS_MODEL.md` — cross-instance publication (deferred)
