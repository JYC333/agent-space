# Module: Sources

## Status

Implemented for built-in RSS, Atom, web page, arXiv (Academic source preset
with HTML-first extraction), manual URL, candidate evidence,
reader, structured reader document extraction, workspace/project routing flows,
Level 2 Source Recipe creation through Phase 8, and the Custom Source backend
create flow through Phase 8.
Source Recipe plan/create/dry-run/activate routes, proposal activation,
scan-worker materialization, the `/sources` Create Source card, Source Detail
normal/Advanced split, `source_runs` read model, and declarative-pipeline
bridge into `source_recipe_versions` are wired. Custom Source proposal
payloads/appliers, Sources frontend create/detail surfaces, and Space/Instance
Settings surfaces are wired. Custom Source repair/rollback (Phase 9) and
credentialed source support (Phase 10) are implemented backend-only (no
frontend surface yet). Phase 12 hardening (rate limiting, artifact retention,
an observability read model) is implemented; Phase 11 (browser/Python
evaluation) was deliberately skipped.

## Purpose

Sources is the canonical boundary for raw source material before it becomes
durable product knowledge, memory, tasks, or project state. It captures,
normalizes, extracts, snapshots, and links candidate material while preserving
proposal gates for durable writes.

The frontend module id is `sources`, the route is `/sources`, and API paths use
`/api/v1/sources/*`. Sources owns source pipeline configuration (connections,
scan schedules, screening rules), recommendation/subscription state, and
delivery permissions; it does not own the reading experience. Reading
Sources-derived content (item streams, item full-text plus annotations, digests,
screened items) lives in the separate Library module (`/library`):
`apps/web/src/modules/library/LibraryItemReaderPage.tsx` is the single-item
reader, gaining prev/next across a day's briefing items when reached from
`/library/digests/:connectionId/:date`, and falling back to a standalone
`/library/items/:itemId` route with no day context. The shared
annotation/inspector/selection-toolbar capability components live under
`apps/web/src/components/reader/` so Library does not import UI from
`modules/sources`.

The normal Sources frontend should not render source item feeds, extracted
evidence feeds, or run-history tables. It may show scan/configuration status
needed to manage subscriptions; detailed run rows remain backend audit/state
for jobs, rules, and troubleshooting.

## Owns

- Source connector catalog for source connectors.
- Space-scoped `SourceConnection` configuration, consent, policy, trust, and
  scan behavior. Scheduler cursor/state for scans is stored as
  `source_connection_scan` rows in `scheduler_tasks`; recurring source scan
  rules live on `source_connections.schedule_rule_json`.
- Source connection ownership, visibility, and per-user delivery state:
  `source_connections.owner_user_id`, `source_connections.visibility`, and
  `source_connection_user_subscriptions`.
- `SourceItem` candidate records.
- `ExtractionJob` scan, extraction, snapshot, manual URL, and normalization
  jobs.
- `SourceSnapshot` records backed by artifacts.
- `ExtractedEvidence` candidate citable evidence.
- `EvidenceLink` relevance and context-selection links.
- The producer side of the Projects routing hook. Project-owned
  `ProjectSourceBinding` and `ProjectSourceItemLink` rows are managed by the
  Projects module; Sources only hands newly materialized items/evidence to the
  hook.
- Sources reader annotations and comments.
- Per-user source item read state (`source_item_user_states`), used by Library
  and the reader.
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

### History import / backfill

Sources owns durable `source_backfill_plans`, ordered segments, and quota
buckets. Preview is deterministic and non-durable; creating a plan is
idempotent per space. Starting a plan is proposal-gated, and segment execution
reuses ordinary `extraction_jobs`, so existing item/evidence dedupe and the
Projects routing hook remain the only materialization path. Quota exhaustion
pauses a plan until `next_eligible_at`; the Sources scheduler reconciles
completed extraction jobs and resumes eligible plans. Project-initiated plans
may link to a ProjectOperation for product-level progress.

The Source Detail `History import` tab consumes these read models: it previews
date windows and quota without writing, creates an idempotent draft, shows
segment/item rollups and `next_eligible_at`, and offers propose-start and
owner/admin pause/resume controls. Raw extraction-job and segment diagnostics
remain an Advanced concern. Start remains proposal-gated:
`source_backfill_start` -> `ProposalApplyService` -> internal
`source.backfill.start`; agents can invoke only the proposal-producing action.

Built-in source connections are seeded for RSS, Atom, web page, and arXiv
connectors. The extraction worker scans feeds and pages, creates candidate
items, queues follow-up extraction or snapshot jobs, writes artifacts for
captured content, and creates candidate evidence where appropriate.

### Academic source presets (arXiv)

Academic Sources is a UX grouping over normal `source_connections`, not a
database boundary. A code-defined preset registry (no table) is exposed under
`GET /api/v1/sources/source-presets`; v1 ships only the `arxiv` preset
(`category: academic`). `POST /api/v1/sources/source-presets/arxiv/preview`
runs a bounded arXiv Atom API query and returns parsed sample papers without
writing durable rows. `POST /api/v1/sources/source-presets/arxiv` validates the
query config (`mode`, `search_query` required/<=500 chars for `search` mode,
one or more `categories` required for `recent_by_category`, `max_results`
1..100, and `sort_by`/`sort_order` from the arXiv API enums), then creates a
normal active built-in connection with `connector_key='arxiv'`, `endpoint_url`
set to the generated `export.arxiv.org/api/query` URL, and the normalized
query config in `config_json` (`preset_id: "arxiv"`). `recent_by_category`
creates `cat:<category>` queries, or `cat:A OR cat:B` for multiple categories,
sorted by `submittedDate` descending, so daily scans behave like an arXiv
new-papers stream with normal Sources dedupe. Use one source for multiple
categories when they share the same schedule, capture policy, and project
binding; create separate sources only when those controls need to differ. Both
POST endpoints enforce the same `source.connection.manage` policy action as
`POST /api/v1/sources/connections`. No credentials are accepted in v1.

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

The Sources page links to a dedicated `/sources/source-presets` page for preset
sources. That page groups presets by category; Academic v1 shows the arXiv
form with `Recent by category` and `Search query` modes plus name, max results,
frequency, and capture policy. Recent mode uses a multi-select category control
for the full official arXiv category taxonomy
(`https://arxiv.org/category_taxonomy`), grouped by archive/category family.
The taxonomy is source-preset-owned code in
`server/src/modules/sources/sourcePresets/arxivCategoryTaxonomy.ts`; the preset
list API returns it as `category_options`, and the backend validates requested
categories against that same value set.
Preview and create are wired to the preset API.
The main `/sources` Create Source card remains for Web/Feed source recipes.
Project binding happens through the Project Sources surface and direct
`project_source_bindings`.
The Academic Research Project preset (`academic_research`) reuses this same
arXiv source preset. The Project preset does not create another source model or
another academic plugin route; its Project Sources section feeds the Project
Corpus and the core Graph `academic_citation_v1` project lens when source
items/evidence/object links are materialized.
Source health is exposed as read models instead of raw run tables:
`/sources/source-health` reports source-level health for visible connections.
Project binding health is Project-owned at
`/projects/{projectId}/sources/health`.

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
draft version, dry-run the recipe without writing Sources output, and activate
it directly when the policy envelope stays inside approved bounds. Permission
deltas create a `source_recipe_activation` proposal; accepting the proposal
activates the recipe version through the proposal applier, and rejecting it
releases the version back to draft. Manual and scheduled recipe scans enqueue
Sources extraction jobs and materialize validated recipe output through the
shared Sources materializer. Source Detail presents product tabs
(Overview, Plan, Preview, Post-processing, Advanced). It keeps handler
versions, raw JSON, and policy/sandbox details under Advanced; user-facing item
reading and brief review happen in Library.

Manual URL source capture is a separate item creation route. It can optionally attach
the saved URL to a `SourceConnection` and queue content extraction. A manually
saved URL may later change its attached source; source-scanned items keep their
original connection as provenance and are not source-reassignable.

### Reader and structured extraction

`extract_text` and the extracted side of `snapshot` jobs fetch source HTML and
materialize an `source_reader_document` artifact. This artifact is JSON
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
`source_raw_snapshot` artifact (`mime_type="application/pdf"`, file-backed
`storage_path`) and derive a `pdf_text_v1` reader document from those bytes.

The Reader UI is a read-only workspace. It supports block-level reading rhythm,
selection toolbar annotation creation, annotation notebook/inspector, comment
threads, and proposal-gated downstream actions from existing annotations. It is
not an editable document surface.

Already extracted items may be re-extracted from the Library item stream or
Reader header. Re-extraction uses the existing `queue_content` item action and
`extract_text` job path; it creates a new extracted source snapshot/artifact and
updates `source_items.extracted_artifact_id`.

Projects consume Sources through Project-owned `project_source_bindings`,
`project_source_item_links`, project filters, evidence links, and the
Project-owned `project_corpus_items` read model.
`ProjectSourceBinding.project_id` is required and does not depend on
`project_workspaces`. Project writers directly bind existing active Sources;
agent-initiated bindings remain proposal-first. Project Sources pages can create
or save URLs into a project collection through an already-bound source, run scans,
backfill existing source items/evidence, and inspect source health. Projects do
not own raw source connections.

Removing a Project binding disconnects it from normal Project reads and UI. The
row is retained as an internal archive for operation/backfill/proposal history;
re-adding the same Source restores that archived binding.

An `SourceItem` keeps one primary `connection_id`, but deduped items may have
`SourceSnapshot` rows from multiple source connections. Project filters and
evidence auto-linking treat both the primary item connection and same-item
snapshot connections as source provenance, so one paper or URL captured by
multiple bound sources remains visible to each bound project without duplicating
the raw item.

### Project linking and source post-processing

When a source item matches an active `project_source_bindings` row for a
project, materialization writes an active `project_source_item_links` row. The
Projects-owned `ProjectSourceRoutingService` then creates active
`context_candidate` `evidence_links` targeting that project. Item links are idempotent
through `uq_project_source_item_links_binding_item`; evidence links remain
idempotent through `uq_evidence_links_active_dedupe` and are what run-context
evidence selection reads for project-bound agent runs.

The same materialization pass syncs Project corpus rows in
`project_corpus_items`: source-item rows, source-object rows when
`source_items.source_object_id` is available, evidence rows, and evidence
source-object rows. Corpus sync does not move source item decisions into a new
decision table. `source_post_processing_item_decisions` remains the
source-item-level post-processing record; Project corpus rows may point to the
latest decision and map its relevance into project `triage_status` while keeping
project `read_status` separate from the personal Library state.

For deduped items, auto-linking also considers `SourceSnapshot.connection_id`
rows for the same item, not only `SourceItem.connection_id`.

Binding a source to a project can also backfill historical extracted evidence.
`POST /api/v1/projects/{projectId}/sources/bindings` accepts
`backfill_history=true`, and
`POST /api/v1/projects/{projectId}/sources/bindings/{bindingId}/backfill` reruns the
same idempotent materialization later. Backfill does not duplicate source items,
evidence, or corpus entries; it inserts/reactivates missing active project item
links, creates missing project `context_candidate` evidence links, and refreshes
the Project corpus read model for existing `ExtractedEvidence` rows whose parent
item or same-item source snapshot belongs to the bound source.

Remote history import is distinct from this local rematerialization. The
Project binding `propose-backfill` route creates a `ProjectOperation`, a
Sources-owned history-import plan, and its start proposal in one transaction.
Project-scoped idempotency keys are locked before operation creation; safe
retries reuse the original operation/plan/proposal, while cross-Project or
different-parameter reuse fails closed.
After approval, quota-controlled segments reuse ordinary `extraction_jobs` and
the existing routing hook, so no Project-specific ingestion path or duplicate
raw source item is introduced.

After a scan materializes new items, the scan paths emit a best-effort
`source_post_processing_event` job (`postProcessing/eventEmitter.ts`). Sources
owns that job, the rule cursor, and the run audit rows:

- `source_post_processing_rules` bind one source connection to one reusable
  agent and define trigger, input window, and actions.
- `source_post_processing_runs` record each rule/manual execution, input item
  and evidence ids, associated agent run, output artifacts/proposals/jobs,
  cursor before/after, status, and errors.
  These rows are operational/audit state and are not shown as a normal Sources
  page run-history feed.
- When a run finishes with `status='succeeded'`, Sources upserts one Activity
  Inbox pointer row for the run's source connection and rule-local date:
  `activity_records.aggregate_key =
  source:briefing:<source_connection_id>:<local_date>`. The Activity row
  stores counts, run ids, artifact ids, and a short preview only; the full
  digest and per-item content remain in the Library read model. The
  `source_connections.config_json.daily_inbox_briefing` boolean disables or
  explicitly enables emission, otherwise it defaults on when the connection has
  an active post-processing rule. This is the sanctioned cross-domain
  notification write under BOUNDARIES B24A.
- Supported triggers are `items_materialized`, `schedule`, and `manual`.
- Supported actions are `batch_digest`, `per_item_summary`, `extract_evidence`,
  `create_proposals`, and `mark_items`; the default is artifact-only
  `batch_digest`. `mark_items` means the run must produce item relevance
  decisions; it does not mutate shared source items.
- `input_config_json.retrieval_context` can opt a rule into retrieval-backed
  relevance context across Project, Knowledge, Memory, and Sources domains.
  Project context and Knowledge base comparison are separate user-facing choices:
  project context is the targeted judging reference when a `project_id` is set,
  while Knowledge is an optional comparison source and is not enabled by default.
  With a `project_id`, the project public summary is pinned before search
  results. Backend validation rejects project-context search on rules that do
  not have a `project_id`.
- Before sending source item titles, excerpts, evidence, or extracted text to
  an agent run, source post-processing revalidates the selected agent/provider
  destination against the source connection's consent and egress policy. A
  denied source egress, including the space external-egress switch for external
  providers, fails the post-processing run before source content leaves Sources.
- Post-processing agent output is consumed as structured
  `source_post_processing.result.v1`; invalid structure fails the run and does
  not advance the rule cursor. `item_decisions_json` records
  `relevant`/`maybe`/`not_relevant` decisions. Relevance lives in
  `source_post_processing_item_decisions`; item reading state lives per user in
  `source_item_user_states`.
- `input_config_json.relevance_profile` lets a rule define what "relevant"
  means independent of which actions are enabled: an `objective`,
  `include_criteria`/`exclude_criteria`/`must_have`/`nice_to_have` lists, and
  an optional `decision_policy` (default wording is used when absent). The
  profile is rule-level, so multiple sources can reuse the same agent with
  different screening criteria.
  `isRelevanceScreeningEnabled(actions, inputConfig)` (`postProcessing/repository.ts`)
  is the single predicate — screening is active when `mark_items` is on
  **or** `relevance_profile.enabled` is true — and both the prompt
  (`postProcessing/instruction.ts`) and the structured-output validator
  (`postProcessing/resultParser.ts`) use it. When screening is active,
  `item_decisions` must cover every input item even if `mark_items` itself is
  off, so screening runs stay auditable. `matched_context_refs` are validated
  against the retrieval refs supplied to that run; hallucinated context refs
  fail the run instead of being persisted. Applying select/triage/ignore from
  a digest writes only the current user's `source_item_user_states` row.
- When `relevance_profile.enabled`, its `objective` and `include_criteria`
  are folded into the retrieval query ahead of the summary goal/connection
  name fallback, biasing whichever explicitly selected project, knowledge,
  memory, or source context gets pulled in before the agent judges the batch.
- Candidate prefiltering ranks only the current input batch before prompt
  assembly. Items filtered before the LLM are persisted as low-confidence
  `maybe` decisions with `stage="candidate_prefilter"` refs, so `mark_items`
  sends them to triage rather than silently ignoring them.
- Optional deep-analysis follow-up uses array-valued
  `source_post_processing_followups` in extraction job metadata. Multiple
  rules can wait on the same pending extraction job without overwriting each
  other, and generated deep-analysis jobs are appended back to the source
  screening run's `output_job_ids_json` for traceability.
- Preset creation flows may stamp `input_config_json.content_profile`,
  `summary_goal`, `output_instructions`, and `relevance_profile` so the
  reusable post-processing agent receives source-specific content guidance
  without cloning agents. Those preset-specific defaults live with the
  preset implementation, not in the generic source post-processing
  UI/service orchestration. The arXiv preset ships a frontend-only
  `screen_relevant_papers` option
  (`apps/web/src/modules/sources/sourcePostProcessingPresets.ts`,
  `apps/web/src/modules/sources/sourcePresets/academic/arxivPostProcessing.ts`)
  that enables `mark_items`, candidate prefiltering, and an enabled
  `relevance_profile` seeded from an optional screening objective. It does not
  enable Knowledge context by default; context domains are explicit rule options,
  not a separate backend preset enum. Public external source connectors such as
  arXiv, RSS, Atom, and watched public web pages default to allowing external
  model processing unless credentials or advanced source governance override
  that policy.

Post-processing may reuse the same `agent_id` across many sources. It is not an
Automations `event` trigger and does not use Automations cursors. `DailyCaptureReport`
remains separate: it summarizes a user's daily captured activity, not one
source connection's post-source processing.

### Retrieval projection

Sources is a retrieval domain through `source_item` and `extracted_evidence`
object types. The adapter indexes active candidate material only:

- `source_item`: `new`, `triaged`, and `selected` items; `ignored`,
  `archived`, and deleted items remove their projection.
- `extracted_evidence`: `candidate` and `active` evidence linked to a valid,
  readable parent source item.
- Edges are projected both ways as `has_evidence` and `evidence_for`.

The indexed text is intentionally bounded: item title, author/source URI/domain,
excerpt, and selected preset metadata; evidence title/type/excerpt plus source
title/author/URI. Full raw snapshots and extracted reader documents are not
indexed by default. Materialization, manual URL create/update, extraction,
custom/recipe materialization, and post-processing evidence writes best-effort
refresh the corresponding retrieval projection and enqueue embedding backfill.

Sources retrieval is opt-in in user-facing context surfaces: Ask Space defaults
to Knowledge only, managed agent tools expose `source.retrieval.search` and
`source.retrieval.brief` only when a run/profile enables the Sources domain, and
owner/admin maintenance uses the Sources-owned
`POST /api/v1/sources/retrieval/search|brief|reindex` endpoints.

## Custom Source Boundary

Custom Source extends `SourceConnection` with generated, source-specific
handler versions. A handler run is a controlled way to produce candidate Sources
output, not a way to mutate core product state.

Generated/template handler expansion (`typescript_node`) is frozen as the
Level 3 advanced fallback — no new handler languages or arbitrary code
execution features; bug/safety fixes only. See
[Sources Custom Source Handlers](../architecture/SOURCE_CUSTOM_SOURCE_HANDLERS.md#level-3-freeze-2026-07-01)
for the Level 1/2/3 split.

Handler code may only read `input.json`, write `output.json`, write files under
sandbox `files/`, and emit captured logs. It must not write
database rows, Memory, Knowledge, Wiki, Tasks, Project state, policy,
credentials, source repository files, or files outside `output.json` and
sandbox `files/`.

The server validates handler output and materializes only accepted data into
Sources-owned tables and artifacts.

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

`GET/PUT /api/v1/sources/custom-source-settings/space` reads and updates only
the Space product policy, including `download_bytes_max`.
`GET/PUT /api/v1/sources/custom-source-settings/instance`
requires instance-admin authority; it stores the runner availability toggle in
Instance Settings with default `runner_enabled=true`, while hard sandbox limits
remain instance-level server safety config.

Policy envelope behavior:

- Inside approved envelope: activation can be automatic when Space policy allows.
- Policy delta: activation creates a `custom_source_*` proposal, marks the
  tested handler version `pending_approval`, and binds the version to the
  proposal. Accepting the proposal activates the version through the Sources
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

- Raw external source material enters through Sources before becoming durable
  Knowledge or Memory.
- Sources `SourceConnection` is not Knowledge `Source`.
- Sources `ProjectSourceBinding` is project-scoped: `project_id` is required,
  creation requires project writer authority, and project collection visibility
  is controlled by `delivery_scope` (`project_members` or
  `source_subscribers`).
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

- `server/src/modules/sources/`
- `server/src/modules/jobs/`
- `server/src/modules/scheduler/`
- `server/src/modules/policy/`
- `server/src/modules/proposals/`
- `server/src/modules/artifacts/`
- `apps/web/src/modules/sources/`
- `apps/web/src/modules/projects/ProjectDetailPage.tsx`
- `packages/protocol/src/`
- `server/migrations/`

## Related Architecture

- [Sources And Evidence Foundation](../architecture/SOURCE_EVIDENCE_FOUNDATION.md)
- [Source Connector Consent](../architecture/SOURCE_CONNECTOR_CONSENT.md)
- [Source Provenance Matrix](../architecture/SOURCE_PROVENANCE_MATRIX.md)
- [Sources Custom Source Handlers](../architecture/SOURCE_CUSTOM_SOURCE_HANDLERS.md)
