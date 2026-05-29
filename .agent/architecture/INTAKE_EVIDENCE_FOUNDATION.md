# Intake And Evidence Foundation

The intake layer is the canonical boundary for raw external and internal inputs.
It is intentionally separate from Memory, Knowledge, policy, tasks, files, and
capabilities.

There is no Area concept in this foundation.

## Model

- `SourceConnector` is the connector catalog.
- `SourceConnection` is a space-scoped configured connection with endpoint,
  credential reference, consent, policy, trust, and connector config.
- `IntakeItem` is raw candidate material. Every item belongs to exactly one
  `Space`. It does not require a workspace or project, and general space intake
  is valid.
- `SourceSnapshot` records immutable captures of raw/extracted/summary material
  stored in `Artifact`.
- `ExtractionJob` audits scans, manual URL intake, extraction, snapshots, and
  internal normalization jobs.
- `ExtractedEvidence` is the citable context unit derived from intake, activity,
  artifacts, run events, files, logs, or documents.
- `EvidenceLink` links one evidence item to multiple targets such as space,
  workspace, project, user, agent, run, proposal, artifact, memory, knowledge,
  or task. Service-layer validation requires each non-space target to exist in
  the same space. `target_type="space"` may omit `target_id`; it is normalized
  to the current `space_id`.
- `WorkspaceIntakeProfile` configures workspace observation and routing policy.
- `WorkspaceSourceBinding` binds a workspace-scoped source stream to a
  space-level source connection without duplicating raw source data or
  credentials. `binding_key` distinguishes multiple filtered bindings over the
  same workspace/connection. If a binding carries `project_id`, that project
  must already be linked to the workspace through `ProjectWorkspace`.

Projects do not own raw intake. Project relevance is expressed primarily with
`EvidenceLink(target_type="project")`.

## Source References

`source_uri` is only for external `http`/`https` URLs and is validated through
the intake URL validator. Internal sources use `source_object_type` and
`source_object_id`.

Valid internal intake sources include:

- `ActivityRecord` via `source_object_type="activity_record"`.
- `Artifact` via `source_object_type="artifact"`.
- `RunEvent` via `source_object_type="run_event"`.

Internal normalization for these sources is item/evidence-idempotent. Repeating
normalization of the same `ActivityRecord`, `Artifact`, or `RunEvent` reuses
the same `IntakeItem` and the same active/candidate `ExtractedEvidence`.
Repeated manual normalization may create an additional skipped
`ExtractionJob` for traceability. This is acceptable because it does not
duplicate active/candidate evidence and does not mutate durable Memory,
Knowledge, policy, tasks, files, or capabilities.

Internal display references belong in metadata such as
`metadata_json.internal_ref`, not in fake `run://`, `artifact://`,
`activity://`, or `file://` URIs.

## Boundaries

Intake and evidence may create candidate records, artifacts, snapshots, jobs,
and links. They must not directly create active Memory, Knowledge, policy,
tasks, files, or capabilities. Durable changes still go through proposals and
their existing apply gates.

Run context selection reads only explicitly linked active evidence through the
evidence selector. Runs do not read directly from the whole intake pool. Selector
inputs are relevance/context candidate links only: `context_candidate`,
`supports`, `mentions`, and `provenance`. Selected evidence references are
frozen in `ContextSnapshot.included_evidence_refs_json` and in
`source_refs_json`.

When selected evidence is used in a run context, the original relevance link
(`context_candidate`, `supports`, `mentions`, or `provenance`) remains
unchanged, and an additional active `EvidenceLink` is recorded:

- `target_type="run"`
- `target_id=<run_id>`
- `link_type="used_in_context"`
- `created_by_run_id=<run_id>`

This makes context use auditable without broadening the evidence selector.
`used_in_context` is audit-only. It must not cause evidence to be selected into
future contexts merely because it was used before.

## Provenance

`EvidenceLink` is the relevance/context/provenance eligibility link between
evidence and targets. It controls whether evidence may be selected for a run
context.

`ProvenanceLink` is the durable accepted-object audit chain, especially after a
proposal is applied. It may point back to `activity`, `proposal`, `artifact`,
`run_step`, `run_event`, `intake_item`, `source_snapshot`, or
`extracted_evidence`, but it is not the selector for candidate evidence.

## Trust

Intake/Evidence uses provenance trust: `trusted`, `normal`, and `untrusted`.
Action risk uses `risk_level` (`low`, `medium`, `high`, `critical` in policy
contexts). Runtime/run/artifact trust uses execution trust values such as
`high`, `medium`, `low`, and `unknown`. These vocabularies are mapped explicitly
when they cross a boundary; they are not interchangeable strings.

## API

The canonical API surface is `/api/v1/intake/*`. Intake is registered only
through `app.intake`.
