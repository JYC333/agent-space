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
Activity → Artifact → Proposal → Wiki / Memory / Card
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

### project_id on durable objects

The following tables carry a nullable soft-reference `project_id` column.
Existing rows with `project_id = NULL` are unaffected; no existing behaviour changes.

| Table | Column added |
|---|---|
| `runs` | `project_id` (no FK, consistent with `task_id` pattern) |
| `activity_records` | `project_id` (soft reference) |
| `artifacts` | `project_id` (soft reference) |
| `proposals` | `project_id` (soft reference) |
| `memory_entries` | `project_id` (soft reference) |

> **Why no FK on existing tables?**  
> SQLite cannot add FK constraints to existing tables via `ALTER TABLE ADD COLUMN` without a full table rebuild.  
> Integrity is enforced at the service layer.

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

**Isolation guarantee:** Before filtering, each endpoint calls `assert_project_in_space(db, project_id, space_id)` which raises `ValueError` (→ HTTP 422) if the project does not exist in the requesting space. This prevents cross-space enumeration via a guessed project ID.

**Output schemas:** Each corresponding output schema (`ActivityOut`, `ArtifactOut`, `ProposalOut`, `RunOutV2`, `MemoryOut`, `ActivityRecordOut`) now includes `project_id: Optional[str] = None`. Rows without a project are not affected.

**Frontend:** All five `*Api.list()` functions in `api/client.ts` accept `project_id`. `ProjectDetailPage` uses these to render per-section scoped previews (up to 5 items each) with "View all →" links to the global list.

## Access control

- Project access is scoped by `space_id`. A user can only access projects within their active space.
- Cross-space workspace linking is rejected: linking a workspace from a different space returns 404.
- No complex RBAC beyond the existing space-membership check.

## Non-goals

- Project is not a task manager. Use the Task Board for work items.
- Project does not auto-promote artifacts into memory or wiki.
- Project does not implement RBAC beyond current space-scoped access.
- Research, paper, author, citation, or literature tables are not part of Project.
