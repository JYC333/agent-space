# Artifacts

Date: 2026-06-16

Artifacts are durable managed content records. Most are durable outputs produced
by runs; Intake also writes artifacts for captured source material and reader
documents. Artifacts let users inspect generated or captured content after
sandbox/source processing and can be linked to proposals, activities, source
snapshots, or other domain records.

An `Artifact` records its production context with `artifacts.run_id` when it was
produced by a run. Task attachment is a separate product relationship:
`task_artifacts` links a task to selected artifacts as output, evidence, or other
task-level material. `task_artifacts.run_id` is the task attachment's run context
when the attachment is tied to a task run; `artifacts.run_id` remains the
artifact's producing run. They usually match for run-produced task output, but
manual or reused attachments can keep the task attachment run null while the
artifact's production context remains unchanged.

## Product API

- The server owns the client-facing artifact read/export
  routes:
  - `GET /api/v1/artifacts`
  - `GET /api/v1/artifacts/{artifact_id}`
  - `GET /api/v1/artifacts/{artifact_id}/export`
- Artifact reads are scoped by space identity and artifact visibility.
- `workspace_shared` artifacts require `artifacts.workspace_id`. Non-owner
  list/read/export access must provide matching workspace context and pass the
  Project-inherited workspace ACL: personal-space workspaces are readable inside
  the personal space; shared-space workspaces are readable through linked
  Projects where the user is the project owner or an active project member.
  Workspaces with no readable linked Project fail closed for non-owner reads.
- Export returns inline artifact content when present, or a file download from
  managed artifact storage when `storage_path` is present.

## Sources

- Content-backed artifacts come from `output_json.artifacts`.
- File-backed artifacts come from `produced_artifact_paths`.
- Intake raw snapshots and reader documents are server-produced artifacts.
  `intake_reader_document` artifacts use
  `canonical_format="reader_document_json"` and store structured Reader JSON
  with remote image references, not downloaded image binaries.

## Storage Rules

- File artifacts are copied or registered into managed artifact storage.
- The database stores a durable relative storage reference, not a sandbox absolute path.
- Sandbox paths are temporary execution details.
- Artifact records must remain scoped to the owning run and space.
- The server resolves file-backed exports under
  `ARTIFACT_STORAGE_ROOT` (default:
  `$AGENT_SPACE_HOME/storage/artifacts`).

## Path Safety

- Unsafe paths are rejected.
- Rejected artifact paths are recorded as `materialization_errors`.
- Path traversal, absolute path input, missing files, and paths outside the allowed runtime output root must not create artifact records.
- Export rejects absolute paths, NUL bytes, path traversal out of managed
  artifact storage, sandbox-root reads, missing paths, and non-regular files.
