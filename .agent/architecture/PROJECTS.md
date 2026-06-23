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

### project_id on durable objects

The following tables carry nullable `project_id` columns with database foreign keys to
`projects.id`. Existing rows with `project_id = NULL` are unaffected.

| Table | Column added |
|---|---|
| `runs` | `project_id` |
| `activity_records` | `project_id` |
| `artifacts` | `project_id` |
| `proposals` | `project_id` |
| `memory_entries` | `project_id` |

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
