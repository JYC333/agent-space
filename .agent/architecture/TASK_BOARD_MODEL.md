# Task board model

This document describes the **agent-native task board** domain layer. It is backend-only; Kanban UI is deferred.

## Core separation

- **Board** — A space- or workspace-level work surface. Groups columns and tasks for planning and visibility.
- **Task** — The **product-level work item**. Humans and agents share this vocabulary. Tasks carry acceptance criteria, priority, assignment, and lifecycle status **independent of the job queue**.
- **Run** — One **execution attempt** for an agent (or system workflow). A task may have many runs over time (retries, validation passes, reviews).
- **Job** — An **infrastructure queue row** (`jobs` table). Used for workers, retries, and dispatch plumbing. **Jobs are not product tasks** and must not be used as the source of truth for user-visible task state.
- **Artifact** — Output attached to a run or task (files, reports, logs). Linked to tasks through `task_artifacts` when needed.
- **Proposal** — A requested system change (for example memory updates). Linked to tasks through `task_proposals`. **Task done does not imply a proposal was applied** — approval is a separate workflow.
- **Evaluation** — Future self/human/system review of a task or run. The `task_evaluations` table exists for later milestones; APIs are minimal today.

## Relationships

- A task may optionally sit on a **board** and **column** (`board_id`, `column_id`).
- A task links to many **runs** via `task_runs` (roles such as `primary`, `retry`, `review`).
- A task links to **artifacts** and **proposals** through junction tables with roles (for example `output`, `evidence`, `main_change`).
- Dependencies between tasks use `task_dependencies` (`blocks`, `requires`, `related`, etc.).

## Agent–human collaboration

Boards and tasks are scoped by **space** (and optionally **workspace**). Assignments may reference both users and agents. The API enforces space boundaries so cross-space references are rejected.

## Task ↔ Run linkage

- **Canonical:** `task_runs` (`TaskRun` ORM) — every product association between a `Task` and a `Run` that the task board should list or join on **must** go through this table. `GET /api/v1/tasks/{id}/runs` is implemented by querying `TaskRun`, then loading `Run` rows by id.
- **Shortcut:** `runs.task_id` (nullable string on `Run`, no FK in the canonical baseline) is an **optional denormalized hint** for a single “primary” task context (traceability, read-model helpers). It is **not** a second source of truth: do not filter “runs for this task” using only `Run.task_id`. Task context for listings should attach through `TaskService` / `TaskRun` (and related link tables), not by assuming `Run.task_id` is always populated for every role or link.

**Task is not Job.** `Run.task_id` holds a **Task.id** when set, not a `jobs.id`.

## Execution boundary

`POST /api/v1/tasks/{id}/runs` creates a **queued** `Run` through `RunService.create_run`, inserts a `task_runs` row (canonical), sets `Run.task_id` only as the **primary-task shortcut**, and may move the task to `in_progress`. It does **not** call runtime adapters or enqueue infrastructure jobs.

## Frontend

Task board **UI** (Kanban, drag-and-drop) is explicitly out of scope for the first surface slice and remains a future frontend effort.

## Obsolete patterns (do not reintroduce)

- `POST /api/v1/tasks/{id}/run` (singular **`/run`**) that returned a `Job` and enqueued worker execution.
- Storing product tasks as `Job` rows with `job_type="product_task"` (or any **Task = Job** mapping).
