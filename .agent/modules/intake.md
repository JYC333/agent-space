# Module: Intake

## Status

Implemented for built-in RSS, Atom, web page, arXiv (Academic source preset
with HTML-first extraction), manual URL, candidate evidence,
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
  `source_connection_scan` rows in `scheduler_tasks`; recurring source scan
  rules live on `source_connections.schedule_rule_json`.
- `IntakeItem` candidate records.
- `ExtractionJob` scan, extraction, snapshot, manual URL, and normalization
  jobs.
- `SourceSnapshot` records backed by artifacts.
- `ExtractedEvidence` candidate citable evidence.
- `EvidenceLink` relevance and context-selection links.
- Project-scoped `WorkspaceSourceBinding` routing.
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

Built-in source connections are seeded for RSS, Atom, web page, and arXiv
connectors. The extraction worker scans feeds and pages, creates candidate
items, queues follow-up extraction or snapshot jobs, writes artifacts for
captured content, and creates candidate evidence where appropriate.

### Academic source presets (arXiv)

Academic Sources is a UX grouping over normal `source_connections`, not a
database boundary. A code-defined preset registry (no table) is exposed under
`GET /api/v1/intake/source-presets`; v1 ships only the `arxiv` preset
(`category: academic`). `POST /api/v1/intake/source-presets/arxiv/preview`
runs a bounded arXiv Atom API query and returns parsed sample papers without
writing durable rows. `POST /api/v1/intake/source-presets/arxiv` validates the
query config (`mode`, `search_query` required/<=500 chars for `search` mode,
one or more `categories` required for `recent_by_category`, `max_results`
1..100, and `sort_by`/`sort_order` from the arXiv API enums), then creates a
normal active built-in connection with `connector_key='arxiv'`, `endpoint_url`
set to the generated `export.arxiv.org/api/query` URL, and the normalized
query config in `config_json` (`preset_id: "arxiv"`). `recent_by_category`
creates `cat:<category>` queries, or `cat:A OR cat:B` for multiple categories,
sorted by `submittedDate` descending, so daily scans behave like an arXiv
new-papers stream with normal Intake dedupe. Use one source for multiple
categories when they share the same schedule, capture policy, and project
binding; create separate sources only when those controls need to differ. Both
POST endpoints enforce the same `intake.connection_manage` policy action as
`POST /api/v1/intake/connections`. No credentials are accepted in v1.

arXiv-specific parsing lives in `connectors/arxiv.ts` (query URL building, Atom
response parsing, and id/URL normalization for abs/pdf/html URLs, `arXiv:`
prefixes, versioned ids, and legacy slash ids), deliberately outside the generic
feed parser. `connectors/arxivThrottle.ts` is a best-effort process-local polite throttle
(default 3s minimum interval, injectable clock/sleep for tests) that wraps
only arXiv network calls.

`connection_scan` for `connector_key='arxiv'` parses the Atom response into
paper records and upserts `feed_entry` items with the base arXiv id (no
version) as `source_external_id`, the canonical abs URL as
`canonical_uri`/`source_uri`, comma-joined authors, the abstract as excerpt,
and arXiv metadata (id/version/authors/categories/primary category/doi/
journal ref/comment/abs/html/pdf URLs) in `metadata_json`. Each scan fetches
the configured `max_results` and relies on item dedupe; incremental query
rewriting is not implemented.

Text extraction and snapshot jobs detect arXiv abs/pdf/html source URLs and
resolve content HTML-first: try `arxiv.org/html/<baseId>` (succeeds only when
structured reader extraction yields non-empty plain text), fall back to
`arxiv.org/pdf/<baseId>` (raw PDF artifact plus `pdf_text_v1` reader
document), then the original URL if distinct. Snapshots store the raw content
actually used. Created snapshots/reader artifacts record
`content_source_format`, `content_source_url`, `arxiv_id`, and
`fallback_from`/`fallback_reason` when PDF fallback occurred. Non-arXiv URLs
keep the existing single-fetch behavior.

The Intake page links to a dedicated `/intake/source-presets` page for preset
sources. That page groups presets by category; Academic v1 shows the arXiv
form with `Recent by category` and `Search query` modes plus name, max results,
frequency, and capture policy. Recent mode uses a multi-select category control
for the full official arXiv category taxonomy
(`https://arxiv.org/category_taxonomy`), grouped by archive/category family.
The taxonomy is source-preset-owned code in
`server/src/modules/intake/sourcePresets/arxivCategoryTaxonomy.ts`; the preset
list API returns it as `category_options`, and the backend validates requested
categories against that same value set.
Preview and create are wired to the preset API.
The main `/intake` Create Source card remains for Web/Feed source recipes.
Project binding still goes through the existing project-scoped workspace source
binding flow.

Scheduled source connections use frequency-specific rules rather than a raw
"next run" picker. Hourly schedules choose a minute, daily schedules choose
hour/minute, and weekly schedules choose weekday/hour/minute. The API stores
the normalized UTC rule in `source_connections.schedule_rule_json` and returns
it as `schedule_rule_json` alongside the computed `next_check_at`.
After each scheduled scan, the next run is recomputed from the rule so schedules
do not drift based on job completion time. The scheduler task owns only runtime
cursor/state (`next_run_at`, `last_run_at`, status, and operational metadata),
not the user-facing recurring rule. Source Detail can edit both
`fetch_frequency` and the schedule rule; manual sources have no recurring rule
and run only through explicit `Run now`/Scan actions.

Capture policy behavior:

- `reference_only`: save the item record, source metadata, scan timestamps, and
  any feed/API excerpt; do not fetch the original page/document.
- `extract_text`: queue `extract_text` follow-up jobs after scans and store a
  reader document/plain text when extraction succeeds.
- `archive_original`: queue `snapshot` follow-up jobs, persist the original
  HTML/PDF snapshot, and derive reader text from that archived copy.

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

Manual URL intake is a separate item creation route. It can optionally attach
the saved URL to a `SourceConnection` and queue content extraction. A manually
saved URL may later change its attached source; source-scanned items keep their
original connection as provenance and are not source-reassignable.

### Reader and structured extraction

`extract_text` and the extracted side of `snapshot` jobs fetch source HTML and
materialize an `intake_reader_document` artifact. This artifact is JSON
(`canonical_format="reader_document_json"`) containing:

- `plain_text` for content hashes, text-range anchors, search/excerpts, and
  annotation verification.
- `content_json` as read-only Tiptap JSON for the Reader UI.
- HTML reader documents use `image_policy="remote_reference"`; image nodes keep
  resolved remote `http`/`https` URLs and do not download image binaries.
- `extraction_method="structured_html_v1"` for HTML and `pdf_text_v1` for PDF.

Reader documents preserve common article structure such as headings,
paragraphs, lists, blockquotes, code blocks, horizontal rules, links, and
remote image references. PDF URLs store the raw PDF as an
`intake_raw_snapshot` artifact (`mime_type="application/pdf"`, file-backed
`storage_path`) and derive a `pdf_text_v1` reader document from those bytes.

The Reader UI is a read-only workspace. It supports block-level reading rhythm,
selection toolbar annotation creation, annotation notebook/inspector, comment
threads, and proposal-gated downstream actions from existing annotations. It is
not an editable document surface.

Already extracted items may be re-extracted from the Intake list, item detail,
or Reader header. Re-extraction uses the existing `queue_content` item action
and `extract_text` job path; it creates a new extracted source snapshot/artifact
and updates `intake_items.extracted_artifact_id`.

Projects consume Intake through project-scoped workspace source bindings,
project filters, and evidence links. `WorkspaceSourceBinding.project_id` is
required, and the referenced workspace must already be linked to the project
through `project_workspaces`. Project pages can create these project-scoped
source bindings directly, save URLs into the project by attaching them to a
project-bound source, change the source for manually saved URL items, and link
back to Intake for source creation, scan state, and advanced management.
Projects do not own raw source connections.

An `IntakeItem` keeps one primary `connection_id`, but deduped items may have
`SourceSnapshot` rows from multiple source connections. Project filters and
evidence auto-linking treat both the primary item connection and same-item
snapshot connections as source provenance, so one paper or URL captured by
multiple bound sources remains visible to each bound project without duplicating
the raw item.

### Project automation integration

When a source connection has an active `workspace_source_bindings` row for a
project, and that binding's workspace is still linked to the project, all three
materialization paths (built-in scan, `extract_text`, custom/recipe materializer)
auto-create active `context_candidate` `evidence_links` targeting that project
(`evidenceProjectLinker.ts`). These links are idempotent via the partial unique index
`uq_evidence_links_active_dedupe` and are what run-context evidence selection
reads for project-bound agent runs.

For deduped items, auto-linking also considers `SourceSnapshot.connection_id`
rows for the same item, not only `IntakeItem.connection_id`.

After a scan materializes new items, the scan paths emit a best-effort
`automation_intake_event` job (`automationEventEmitter.ts`). The automations
module consumes it to fire `trigger_type='event'` automations. Emission is
at-least-once; the automation intake delta cursor makes duplicates harmless.
See [modules/automations.md](automations.md).

## Custom Source Boundary

Custom Source extends `SourceConnection` with generated, source-specific
handler versions. A handler run is a controlled way to produce candidate Intake
output, not a way to mutate core product state.

Generated/template handler expansion (`typescript_node`) is frozen as the
Level 3 advanced fallback — no new handler languages or arbitrary code
execution features; bug/safety fixes only. See
[Intake Custom Source Handlers](../architecture/INTAKE_CUSTOM_SOURCE_HANDLERS.md#level-3-freeze-2026-07-01)
for the Level 1/2/3 split.

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
default source policy, allowed domains, per-space download cap, credentialed
source policy, and whether same-envelope repair may auto-apply.

Instance Settings owns runner and sandbox safety such as whether the runner is
enabled, allowed languages, hard network denies, time/output/log/file limits,
browser automation availability, shell availability, and dependency
installation availability. The download cap is intentionally space policy, not
environment or instance config.

`GET/PUT /api/v1/intake/custom-source-settings/space` reads and updates only
the Space product policy, including `download_bytes_max`.
`GET/PUT /api/v1/intake/custom-source-settings/instance`
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
- Intake `WorkspaceSourceBinding` is project-scoped: `project_id` is required,
  creation requires project writer authority, and the workspace must be linked
  to that project.
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
