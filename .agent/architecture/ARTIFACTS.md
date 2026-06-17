# Artifacts

Date: 2026-06-16

Artifacts are durable outputs produced by runs. They let users inspect generated content after sandbox cleanup and can be linked to proposals or activities.

## Product API

- The server owns the client-facing artifact read/export
  routes:
  - `GET /api/v1/artifacts`
  - `GET /api/v1/artifacts/{artifact_id}`
  - `GET /api/v1/artifacts/{artifact_id}/export`
- Artifact reads are scoped by space identity and artifact visibility.
- Export returns inline artifact content when present, or a file download from
  managed artifact storage when `storage_path` is present.

## Sources

- Content-backed artifacts come from `output_json.artifacts`.
- File-backed artifacts come from `produced_artifact_paths`.

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
