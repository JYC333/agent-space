# Projects

## What is a Project?

A **Project** is a goal-oriented knowledge and activity container.
It organises activities, artifacts, proposals, agent runs, and linked workspaces around a long-lived objective.
It is the stable ownership and context boundary for durable objects — not a task manager or execution environment.

## What is a Workspace?

A **Workspace** is a file, code, and execution boundary.
It is where agents inspect files, create sandboxes, run commands, collect diffs, and validate changes.
Capability code belongs to a Workspace.

## Project vs Workspace

| Concern | Project | Workspace |
|---|---|---|
| Purpose | Goal / knowledge / context | File / execution / sandbox |
| Holds | Activities, artifacts, proposals, runs, memory | Files, repos, capability code |
| Created by | User — named objective | User or system — maps to filesystem path |
| Cardinality | One project → many workspaces | One workspace → many projects |
| Capability outputs | Digests, artifacts, proposals, project memory | Capability code itself |

A Project can link to multiple Workspaces.  
A Workspace can serve multiple Projects.  
Capability code lives in a Workspace; its outputs (digests, artifacts, proposals, memory) belong to a Project.

## Information flow

External information should enter the system through the canonical provenance chain:

```
Activity -> Artifact -> Proposal -> Knowledge / Memory / Card
```

Do not write external information directly into active memory.
Each step adds trust validation and human review opportunity.

## Data model

### Project

| Field | Type | Notes |
|---|---|---|
| `id` | UUID string | Immutable primary key |
| `space_id` | FK → spaces | Hard access boundary; always included in queries |
| `owner_user_id` | FK → users (nullable) | Who controls the project for ACL |
| `name` | string | Unique among active projects within the space (service-layer check) |
| `description` | text (nullable) | Optional long-form description |
| `status` | string | `active` \| `archived` \| `deleted` |
| `current_focus` | text (nullable) | Short statement of current goal |
| `settings_json` | JSON (nullable) | Flexible per-project configuration |
| `created_at` / `updated_at` | datetime | Standard timestamps |
| `archived_at` | datetime (nullable) | Set when archived |
| `deleted_at` | datetime (nullable) | Soft-delete marker |

### ProjectWorkspace (association)

| Field | Type | Notes |
|---|---|---|
| `id` | UUID string | Primary key |
| `project_id` | FK → projects | |
| `workspace_id` | FK → workspaces | Must be in same space as project (service check) |
| `role` | string | `primary_codebase` \| `capability_library` \| `docs` \| `data` \| `deployment` \| `reference` |
| `created_at` / `updated_at` | datetime | |

Uniqueness constraint: `(project_id, workspace_id, role)` — a workspace can fill multiple distinct roles for the same project.

### ProjectMember (project memory ACL)

| Field | Type | Notes |
|---|---|---|
| `id` | UUID string | Primary key |
| `space_id` | FK -> spaces | Same hard boundary as Project |
| `project_id` | FK -> projects | Project whose concrete memory can be read |
| `user_id` | FK -> users | Space member receiving project-level access |
| `role` | string | `owner` \| `member` \| `viewer` |
| `status` | string | `active` \| `revoked` |
| `created_at` / `updated_at` | datetime | |

`project_members` is the ACL used by memory read/retrieval surfaces for
project-scoped memory. It does not make project memory public. In shared spaces,
concrete project memory is readable only by the project owner or an active
project member; `viewer` can read gated memory but cannot mutate project
metadata or public summaries.

### ProjectPublicSummary

| Field | Type | Notes |
|---|---|---|
| `id` | UUID string | Primary key |
| `space_id` | FK -> spaces | Space-public discovery boundary |
| `project_id` | FK -> projects | Unique current summary per project |
| `summary_text` | text | Redacted, high-level project brief only |
| `topics_json` | JSON array | Public aliases/topics for retrieval |
| `highlights_json` | JSON array | Public high-level highlights |
| `source_refs_json` | JSON array | Pointer metadata only; no raw memo/doc content |
| `redaction_version` | string | Sanitization contract version |
| `review_status` | string | `draft` \| `approved` \| `archived` |
| `updated_by_user_id` | FK -> users (nullable) | Last human updater |
| `generated_by_run_id` | FK -> runs (nullable) | Optional generating run, same project/space |
| `created_at` / `updated_at` | datetime | |

Project public summaries are intentionally separate from project memory. They
are designed for cross-project discovery and inspiration: approved summaries are
space-public and indexed as retrieval object type `project_public_summary`.
They must be sanitized before write; source refs may identify public pointers
but must not embed raw private memory, memo excerpts, document bodies, or other
concrete project content.

### Project Presets

Project presets are code-owned workflow packs selected when a Project is
created. They are project shape presets, not post-create feature toggles. A
Project's selected preset key is stored in `projects.settings_json.preset` and
the frontend uses it to choose the Project-specific shell, visual treatment, and
primary operations. Changing a Project's preset after creation is not a normal
user workflow.

The current built-in preset is `academic_research`. It reuses normal Project
Sources plus the `arxiv` source preset, `academic_paper_v1` extraction profile
key, and `academic_citation_v1` graph lens id. Its advertised sections are
`source_monitoring`, `corpus`, and `project_graph`; paper/citation objects are
represented through the core relation/object model and surfaced through the
project corpus and graph lens, not through a second project hierarchy. Academic
projects render an Academic Research workbench with direct literature
monitoring, paper screening/corpus, arXiv source setup, and citation graph
actions.

A project source binding whose `extraction_policy_json.profile_key` is
`academic_paper_v1` materializes matching arXiv-scanned source items into a
paper object (`space_objects` + `sources` + `academic_papers`, deduped per
space by `arxiv_id`/`doi`) before the normal Project Corpus sync runs — see
`materializeAcademicPaperFromSourceItem`
(`server/src/modules/academic/paperMaterializer.ts`). Once
`source_items.source_object_id` is set, the object is picked up by the
existing corpus/graph sync with no preset-specific wiring.

The `project_research` module (`/api/v1/projects/{id}/research/*`, see below)
adds a project-owned research workflow foundation on top of Project Corpus:
a research profile requiring human approval before a workflow can start,
workflow/stage/checkpoint state, Artifact-per-stage links, project screening
criteria, and a literature-matrix read model. Editing an approved research
profile returns it to `draft` and clears approval metadata so downstream
workflows require a fresh human confirmation. The module dispatches through
existing Runs/Artifacts rather than a parallel execution system. Its integrity
gate writes an `integrity_report` Artifact and a pending checkpoint after
checking workflow-scoped claim links for missing citations, missing evidence
or explicit gaps, evidence outside the project corpus, and missing experiment
provenance.

### project_id on durable objects

The following tables carry `project_id` columns with database foreign keys to
`projects.id`. Unless noted otherwise, the column is nullable and existing rows
with `project_id = NULL` are unaffected.

| Table | Column added |
|---|---|
| `runs` | `project_id` |
| `activity_records` | `project_id` |
| `artifacts` | `project_id` |
| `proposals` | `project_id` |
| `memory_entries` | `project_id` |
| `automations` | `project_id` (composite FK `(space_id, project_id)`; optional, `agent_run` target only, requires project writer authority to bind — see [modules/automations.md](../modules/automations.md)) |
| `project_source_bindings` | `project_id` (required; composite FK `(space_id, project_id)`; source consumption requires project writer authority) |
| `project_source_item_links` | `project_id` (required; materialized Source item collection rows for project source bindings) |
| `project_corpus_items` | `project_id` (required; project-owned corpus/read model over object, source item, and evidence links) |

`project_source_bindings` and `project_source_item_links` are Project-owned
consumption configuration/read-model records, authored in
`server/src/db/schema/projectSources.ts` and served by the Projects module.
`source_connections` stay space-scoped under Sources. The binding is the
project boundary: the same source connection can be bound to multiple projects
because the uniqueness constraint includes `(space_id, project_id,
source_connection_id, binding_key)`.

`project_corpus_items` is Project-owned. It reconciles Sources output into the
project's working corpus:

- `status` is link lifecycle (`active` / `archived`);
- `triage_status` is the project-level judgement (`new`, `relevant`, `maybe`,
  `excluded`, `included`);
- `triage_confirmed_by_user` is set whenever a human explicitly sets
  `triage_status` through the Corpus API. Automated screening-decision sync
  (`syncProjectCorpusSourceDecisions`) must not overwrite `triage_status` or
  `last_reviewed_at` once this is true — AI screening only suggests, the user
  confirms;
- `read_status` is project-level reading progress (`unread`, `skimmed`,
  `read`, `discussed`).

When the corpus item's object is a materialized academic paper (see above),
the corpus DTO's `object.academic` field carries joined `academic_papers` +
`sources` metadata (`arxiv_id`, `doi`, `publication_date`, `venue`,
`paper_type`, citation counts, `authors`, `categories`, `source_uri`); it is
`null` for non-paper objects.

`source_post_processing_item_decisions` remains the source-item-level
post-processing decision/audit record. Project corpus rows may point at the
latest relevant decision through `source_decision_id`, but project triage/read
state is not stored on source items and does not mutate Library state.

## API routes

All routes are under `/api/v1/projects` and require authentication.
Space scoping is enforced via the `space_id` query parameter resolved by `get_identity`.

| Method | Path | Description |
|---|---|---|
| GET | `/projects` | List projects in the authenticated space |
| POST | `/projects` | Create a project |
| GET | `/projects/{id}` | Get a project |
| PATCH | `/projects/{id}` | Update name / description / focus / settings |
| POST | `/projects/{id}/archive` | Archive a project |
| GET | `/projects/{id}/summary` | Counts: activities, artifacts, pending proposals, workspaces, active runs, memory entries |
| GET | `/projects/{id}/corpus` | List the project corpus over collected source items, evidence, and graph objects |
| POST | `/projects/{id}/corpus` | Upsert a project corpus entry for an object, source item, or evidence target; requires project writer |
| PATCH | `/projects/{id}/corpus/{corpus_item_id}` | Update project-level corpus lifecycle, triage, read status, role, relevance, confidence, reason, or metadata; requires project writer |
| POST | `/projects/{id}/corpus/backfill-source-items` | Recompute project corpus rows from current project source item links, evidence links, source-object pointers, and source post-processing decisions; requires project writer |
| GET / POST | `/projects/{id}/sources/bindings` | List or create Project-owned source bindings |
| POST | `/projects/{id}/sources/propose-bind` | Agent-only proposal path for `project_source_bind`; Project writers use direct binding creation |
| PATCH / DELETE | `/projects/{id}/sources/bindings/{bindingId}` | Update or disconnect a Project binding; removal is internally archived for audit and omitted from normal binding reads |
| POST | `/projects/{id}/sources/bindings/{bindingId}/backfill` | Idempotently rematerialize already-collected source items into the Project |
| POST | `/projects/{id}/sources/bindings/{bindingId}/propose-backfill` | Create an operation, history-import plan, and start proposal |
| POST | `/projects/{id}/sources/propose-setup` | Idempotently create one Project operation, paused Source draft, activation proposal, and dependent binding proposal |
| GET | `/projects/{id}/sources/health` | Read binding-level collection health |
| GET / POST | `/projects/{id}/operations` | List or create product-level Project operations |
| GET | `/projects/{id}/operations/{operationId}` | Read operation steps, links, and projected progress |
| POST | `/projects/{id}/operations/{operationId}/cancel` | Cancel a non-terminal grouping record |
| GET | `/projects/public-summaries` | List approved high-level project summaries in the current space |
| POST | `/projects/public-summaries/search` | Search only `project_public_summary` retrieval objects |
| GET | `/projects/{id}/public-summary` | Read the approved high-level public summary for a project |
| PUT | `/projects/{id}/public-summary` | Create/update the sanitized public summary. A bare write stages `review_status = draft` (project writer authority). Publishing (`approved`) or unpublishing (`archived`) requires project-owner-level authority |
| POST | `/projects/{id}/public-summary/draft` | Generate and store a sanitized **draft** public summary via the `project_public_summary` provider task; records a best-effort `policy_decision_records` audit of the model call |
| GET | `/projects/{id}/members` | List project-level memory ACL members |
| POST | `/projects/{id}/members` | Add/update a project memory ACL member |
| DELETE | `/projects/{id}/members/{user_id}` | Remove a project memory ACL member |
| GET | `/projects/{id}/workspaces` | List linked workspaces |
| POST | `/projects/{id}/workspaces` | Link a workspace (with role) |
| DELETE | `/projects/{id}/workspaces/{workspace_id}` | Unlink a workspace |
| GET | `/project-presets` | List built-in Project preset descriptors |
| GET | `/projects/{id}/preset` | Read the Project's selected preset key |
| GET / PUT | `/projects/{id}/research/profile` | Read / upsert the project's research profile (draft until approved) |
| POST | `/projects/{id}/research/profile/approve` | Approve the research profile; required before a workflow can start |
| GET | `/projects/{id}/research/workflow` | List research workflows for the project |
| POST | `/projects/{id}/research/workflow/start` | Start a research workflow (requires an approved profile) |
| POST | `/projects/{id}/research/workflow/{workflowId}/stages/{stageKey}/run` | Record a workflow stage transition, optionally linking a `run_id` |
| GET | `/projects/{id}/research/workflow/{workflowId}/checkpoints` | List checkpoints for a workflow |
| POST | `/projects/{id}/research/workflow/{workflowId}/checkpoints/{checkpointId}/decide` | Record a human decision (`approved` / `rejected` / `waived`) on a checkpoint |
| GET / POST | `/projects/{id}/research/artifacts` | List / link Artifacts to a workflow stage (`artifact_type` is a fixed vocabulary, e.g. `rq_brief`, `literature_matrix`, `synthesis_report`) |
| GET / PUT | `/projects/{id}/research/screening-criteria` | Read / upsert project screening criteria (keywords, methods, date range, venues, required evidence fields) |
| GET | `/projects/{id}/research/literature-matrix` | Literature matrix read model over included/maybe corpus papers, with academic metadata and evidence/annotation counts |
| POST | `/projects/{id}/research/literature-matrix/rebuild` | Backfill the project corpus from sources, then return the refreshed matrix |
| GET | `/projects/{id}/research/synthesis` | List `synthesis_report`-typed artifact links |
| POST | `/projects/{id}/research/integrity/run` | Run V1 integrity checks, write an `integrity_report` artifact, and record a pending `integrity_gate` checkpoint |

## project_id query filter on durable object list APIs

All five durable object list endpoints accept an optional `project_id` query parameter to scope results to a project:

| Endpoint | Parameter added |
|---|---|
| `GET /activity` | `project_id` |
| `GET /artifacts` | `project_id` |
| `GET /proposals` | `project_id` |
| `GET /runs` | `project_id` |
| `GET /memory` | `project_id` |

**Isolation guarantee:** Before filtering, each endpoint validates the requested
project with `assertProjectInSpace(db, space_id, project_id)`, returning HTTP 422
if the project does not exist in the requesting space or has been deleted. This
prevents cross-space enumeration via a guessed project ID. Durable writes that
accept a `project_id` also validate the association: Activity create, Run create,
and runtime materialized proposals reject missing/deleted/cross-space projects
before persisting rows. Runtime proposal materialization also canonicalizes the
proposal payload `project_id` and the `proposals.project_id` column to the same
validated value. Proposal apply carries `proposals.project_id` into
`memory_entries.project_id` only after revalidating the project in the proposal
space.

**Output schemas:** Each corresponding output schema (`ActivityOut`, `ArtifactOut`, `ProposalOut`, `RunOut`, `MemoryOut`, `ActivityRecordOut`) now includes `project_id: Optional[str] = None`. Rows without a project are not affected.

**Frontend:** All five `*Api.list()` functions in `api/client.ts` accept `project_id`. `ProjectDetailPage` uses these to render per-section scoped previews (up to 5 items each) with "View all →" links to the global list.

## Access control

- Project access is scoped by `space_id`. A user can only access projects within their active space.
- Cross-space workspace linking is rejected: linking a workspace from a different space returns 404.
- Project memory ACL is separate from high-level project visibility:
  `project_members` gates concrete `memory_entries.project_id` reads, while
  `project_public_summaries` is an approved, sanitized, space-public discovery
  layer.
- Project metadata/public-summary/workspace-link mutations require project
  writer authority: the project `owner_user_id`, a space `owner`/`admin`, or an
  active `project_members.role` of `owner` or `member`. `viewer` is read-only for
  concrete project memory and cannot mutate project metadata or public summary.
- Project source binding creation requires project writer authority and binds a
  Source connection directly to a Project. Removing project-workspace links does
  not mutate project source bindings.
- Project Detail shows a compact Sources summary and links to the Project
  Sources surface. Project Sources supports binding sources, backfill, scan,
  pause/remove, health, and the materialized project item collection. Global
  Sources remains the source-level management surface.
- Project Chat at `/projects/{id}/chat` reuses the normal agent chat/session
  and managed Run pipeline. Sessions and Runs carry validated `project_id`;
  reusing a session under another Project is rejected. Managed Project Chat
  exposes proposal-only source actions and stores structured action previews
  on assistant-message metadata for inline cards and canonical Review links.
- Project creation lets the user choose a Project preset. Project Detail uses
  the chosen preset to render the corresponding project shell. Academic Research
  projects show a research workbench and direct literature/corpus/citation graph
  operations. The preset does not create a second Project hierarchy.
- Project Detail also shows recent Sources recommendations from project-linked
  source post-processing decisions. These are selected/maybe candidate items for
  review and follow-up; accepting durable Knowledge still goes through proposal
  review.
- **Publishing a public summary** (`review_status` other than `draft`) requires
  project-**owner**-level authority — the project `owner_user_id` or a space
  `owner`/`admin`. A project `member` (writer) can stage drafts but cannot
  self-approve. The draft generator only ever writes `draft`. This gives the
  project owner a review gate before content becomes space-public.
- `settings_json` is free-form per-project configuration and may carry private
  operational detail. `GET /projects` and `GET /projects/{id}` redact it to
  `null` for non-writers; only project writers see it. `name`, `description`,
  and `current_focus` remain space-visible descriptive metadata.
- Project public-summary search is restricted to retrieval object type
  `project_public_summary`. It does not expose project memory, artifacts, docs,
  memo bodies, or other concrete project content.
- Approved public summaries also feed the **system chat candidate collector**
  (source `project_public_summary`), so the shared assistant can surface
  cross-project inspiration. Only the sanitized summary is read; concrete
  project memory stays behind its own ACL.
- **Database-level space/project consistency:** `projects` carries a composite
  candidate key `UNIQUE (space_id, id)`, and `project_public_summaries` and
  `project_members` carry a composite FK `(space_id, project_id) → projects
  (space_id, id)`. A summary or ACL row therefore cannot reference a project in
  another space even via hand-written SQL.

## Non-goals

- Project is not a task manager. Use the Task Board for work items.
- Project does not auto-promote artifacts into memory or knowledge.
- Project is not a Knowledge type; KnowledgeItem rows may reference `project_id`
  as a contextual association only.
- Project public summaries are not a substitute for project memory ACL; they are
  a sanitized discovery layer.
- Research, paper, author, citation, or literature tables are not part of Project.
# Project operations

`project_operations` is a Projects-owned grouping/read model over canonical
Runs, Jobs, Proposals, Artifacts, source bindings, and history-import plans.
It never executes or blocks those objects. Ordered optional steps provide a
product progress view; status and `progress_json` are projected from validated,
same-space links when an operation is read. Public routes live under
`/api/v1/projects/{projectId}/operations`; cancellation changes only the
operation grouping record and never cancels linked execution objects.
