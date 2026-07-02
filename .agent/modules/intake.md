# Module: Intake

## Status

Implemented for built-in RSS, Atom, web page, manual URL, candidate evidence,
reader, structured reader document extraction, workspace/project routing flows,
Level 2 Source Recipe creation through Phase 8, and the Custom Source backend
create flow through Phase 8.
Source Recipe plan/create/dry-run/activate routes, proposal activation,
scan-worker materialization, the `/intake` Create Source card, Source Detail
normal/Advanced split, `source_runs` read model, and declarative-pipeline
bridge into `source_recipe_versions` are wired. Custom Source proposal
payloads/appliers, Intake frontend create/detail surfaces, and Space/Instance
Settings surfaces are wired. Custom Source repair/rollback (Phase 9) and
credentialed source support (Phase 10) are implemented backend-only (no
frontend surface yet). Phase 12 hardening (rate limiting, artifact retention,
an observability read model) is implemented; Phase 11 (browser/Python
evaluation) was deliberately skipped.

## Purpose

Intake is the canonical boundary for raw source material before it becomes
durable product knowledge, memory, tasks, or project state. It captures,
normalizes, extracts, snapshots, and links candidate material while preserving
proposal gates for durable writes.

## Owns

- Source connector catalog for intake connectors.
- Space-scoped `SourceConnection` configuration, consent, policy, trust, and
  scan behavior. Scheduler cursor/state for scans is stored as
  `source_connection_scan` rows in `scheduler_tasks`.
- `IntakeItem` candidate records.
- `ExtractionJob` scan, extraction, snapshot, manual URL, and normalization
  jobs.
- `SourceSnapshot` records backed by artifacts.
- `ExtractedEvidence` candidate citable evidence.
- `EvidenceLink` relevance and context-selection links.
- `WorkspaceIntakeProfile` and `WorkspaceSourceBinding` routing.
- Intake reader annotations and comments.
- Custom Source handler versions, handler runs, backend create/test/activate
  flow, and first scan-job integration.
- Source Recipe versions, deterministic planning, dry-run preview,
  activation/proposal flow, and recipe scan-job integration.

## Does Not Own

- Knowledge `Source` as curated wiki evidence.
- Memory writes.
- Wiki writes.
- Task writes.
- Project-owned source creation.
- Runtime adapter marketplace.
- Capability marketplace.
- General plugin marketplace.
- Credential storage.

## Current Implementation

Built-in source connections are seeded for RSS, Atom, and web page connectors.
The extraction worker scans feeds and pages, creates candidate items, queues
follow-up extraction or snapshot jobs, writes artifacts for captured content,
and creates candidate evidence where appropriate.

Custom Source backend support is implemented for draft connection creation,
deterministic handler generation, fixture testing, inside-envelope activation,
manual and scheduled scan queueing, handler-run history, and trusted endpoint
fetching into the handler input. `typescript_node` remains the generated-code
Level 3 fallback. Existing `declarative_pipeline_v1` handler versions remain
readable and executable for compatibility; operators can explicitly bridge one
into a new paused Level 2 recipe source and draft `source_recipe_versions`
row. New normal source creation uses Source Recipes, not pipeline-as-handler
rows.

Level 2 Source Recipe support is implemented for recipe-first source creation.
`source_connections.handler_kind = 'recipe'` rows point at
`source_recipe_versions` through `active_recipe_version_id`. The deterministic
planner can classify RSS, Atom, web-list, and web-page inputs, produce a fixed
recipe shape plus sample preview, create a paused recipe connection with a
draft version, dry-run the recipe without writing Intake output, and activate
it directly when the policy envelope stays inside approved bounds. Permission
deltas create a `source_recipe_activation` proposal; accepting the proposal
activates the recipe version through the proposal applier, and rejecting it
releases the version back to draft. Manual and scheduled recipe scans enqueue
Intake extraction jobs and materialize validated recipe output through the
shared Intake source materializer. Source Detail presents product tabs
(Overview, Plan, Preview, Items, Evidence, Runs) and keeps handler versions,
raw JSON, raw runs, and policy/sandbox details under Advanced.

Manual URL intake is a separate item creation route. It can optionally queue
content extraction.

### Reader and structured extraction

`extract_text` and the extracted side of `snapshot` jobs fetch source HTML and
materialize an `intake_reader_document` artifact. This artifact is JSON
(`canonical_format="reader_document_json"`) containing:

- `plain_text` for content hashes, text-range anchors, search/excerpts, and
  annotation verification.
- `content_json` as read-only Tiptap JSON for the Reader UI.
- `image_policy="remote_reference"`; image nodes keep resolved remote
  `http`/`https` URLs and do not download image binaries.
- `extraction_method="structured_html_v1"`.

The reader repository remains backward compatible with older `text/plain`
`intake_extracted_text` artifacts. New reader documents preserve common article
structure such as headings, paragraphs, lists, blockquotes, code blocks,
horizontal rules, links, and remote image references.

The Reader UI is a read-only workspace. It supports block-level reading rhythm,
selection toolbar annotation creation, annotation notebook/inspector, comment
threads, and proposal-gated downstream actions from existing annotations. It is
not an editable document surface.

Already extracted items may be re-extracted from the Intake list, item detail,
or Reader header. Re-extraction uses the existing `queue_content` item action
and `extract_text` job path; it creates a new extracted source snapshot/artifact
and updates `intake_items.extracted_artifact_id`.

Projects consume Intake through workspace source bindings, project filters, and
evidence links. Project pages link back to Intake for management. Projects do
not own raw source connections.

## Custom Source Boundary

Custom Source extends `SourceConnection` with generated, source-specific
handler versions. A handler run is a controlled way to produce candidate Intake
output, not a way to mutate core product state.

Generated/template handler expansion (`typescript_node`) is frozen as the
Level 3 advanced fallback — no new handler languages or arbitrary code
execution features; bug/safety fixes only. See
[Intake Custom Source Handlers](../architecture/INTAKE_CUSTOM_SOURCE_HANDLERS.md#level-3-freeze-2026-07-01)
and `.agent/plans/intake-source-levels-plan.md` for the Level 1/2/3 split.

Handler code may only read `input.json`, write `output.json`, write files under
sandbox `files/`, and emit captured logs. It must not write
database rows, Memory, Knowledge, Wiki, Tasks, Project state, policy,
credentials, source repository files, or files outside `output.json` and
sandbox `files/`.

The server validates handler output and materializes only accepted data into
Intake-owned tables and artifacts.

## Policy

Source consent and source policy govern readers, subjects, agents, model
egress, retention, derived writes, trust, and allowed import targets.

Custom Source policy adds a handler policy envelope for network origins,
credentials, runtime language, browser automation, shell, dependency
installation, resource limits, output limits, and log retention.

Space Settings owns product policy such as who can create custom sources,
default source policy, allowed domains, credentialed source policy, and whether
same-envelope repair may auto-apply.

Instance Settings owns runner and sandbox safety such as whether the runner is
enabled, allowed languages, hard network denies, time/memory/output/download
limits, browser automation availability, shell availability, and dependency
installation availability.

`GET/PUT /api/v1/intake/custom-source-settings/space` reads and updates only
the Space product policy. `GET/PUT /api/v1/intake/custom-source-settings/instance`
requires instance-admin authority; it stores the runner availability toggle in
Instance Settings with default `runner_enabled=true`, while hard sandbox limits
remain instance-level server safety config.

Policy envelope behavior:

- Inside approved envelope: activation can be automatic when Space policy allows.
- Policy delta: activation creates a `custom_source_*` proposal, marks the
  tested handler version `pending_approval`, and binds the version to the
  proposal. Accepting the proposal activates the version through the Intake
  Custom Source applier; rejecting the proposal releases the version back to
  `draft`.
- Credentialed source: a draft references a pre-created Custom Source
  credential by `credential_id`, never a raw secret. First activation
  auto-activates only when Space policy allows credentialed sources,
  otherwise a `custom_source_credentialed_source` proposal is required.
- Repair: regenerates a handler version (never mutates the active one in
  place) from the active version's manifest plus overrides; auto-activates
  only when the envelope is unchanged and Space policy allows same-envelope
  repair auto-apply, otherwise creates a proposal. Rollback activates a
  previously-active version directly, no proposal.
- Source Recipe: dry-run-tested recipe versions activate directly when the
  policy envelope is within bounds; envelope broadening creates a
  `source_recipe_activation` proposal and binds the recipe version to it until
  accepted or rejected.

## Invariants

- Raw external source material enters through Intake before becoming durable
  Knowledge or Memory.
- Intake `SourceConnection` is not Knowledge `Source`.
- Custom Source handlers never directly write durable product objects.
- Projects do not create a second source model.
- Source-derived Memory and Knowledge writes remain proposal-gated.
- Evidence selected for run context goes through `EvidenceLink`; Knowledge
  `Source` is not selected directly into run context.
- Generated handler execution fails closed when runner support is unavailable or
  disabled.
- Source Recipe execution uses server-owned primitives, not untrusted code, and
  still fails closed through the same policy/output validation boundary.

## Related Files

- `server/src/modules/intake/`
- `server/src/modules/jobs/`
- `server/src/modules/scheduler/`
- `server/src/modules/policy/`
- `server/src/modules/proposals/`
- `server/src/modules/artifacts/`
- `apps/web/src/modules/intake/`
- `apps/web/src/modules/projects/ProjectDetailPage.tsx`
- `packages/protocol/src/`
- `server/migrations/`

## Related Architecture

- [Intake And Evidence Foundation](../architecture/INTAKE_EVIDENCE_FOUNDATION.md)
- [Source Connector Consent](../architecture/SOURCE_CONNECTOR_CONSENT.md)
- [Source Provenance Matrix](../architecture/SOURCE_PROVENANCE_MATRIX.md)
- [Intake Custom Source Handlers](../architecture/INTAKE_CUSTOM_SOURCE_HANDLERS.md)
