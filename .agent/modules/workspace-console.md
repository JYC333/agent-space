# Module: Workspace Console

## Status
Backend workspace console read APIs are active. UI views are still partial/planned.

## Purpose
Browser-based interface for browsing workspace files, reviewing agent run outputs, inspecting diffs, and approving proposals. All file access goes through server-side managers — the frontend never accesses the host filesystem directly.

## Owns
- Workspace file browser UI
- Git status and diff viewer UI
- Agent run log viewer UI
- Artifact browser UI
- Proposal review and approval UI
- Workspace console backend read APIs (tree, file content, git status, git diff)

## Does Not Own
- Sandbox creation (sandbox module)
- Proposal storage (proposals module)
- Memory display (memory module)
- Agent run dispatch (agents module)

## UI Areas (Planned)

```
/workspaces
  /{workspace_id}/files      — file browser (read-only view)
  /{workspace_id}/git        — git status, log, diff
  /{workspace_id}/runs       — agent run list and detail
  /{workspace_id}/artifacts  — artifact browser
  /{workspace_id}/proposals  — pending proposals for approval
```

## Backend API

```
GET  /api/v1/workspace-console/workspaces
GET  /api/v1/workspace-console/workspaces/{id}/tree?path=...
GET  /api/v1/workspace-console/workspaces/{id}/file?path=...
GET  /api/v1/workspace-console/workspaces/{id}/git/status
GET  /api/v1/workspace-console/workspaces/{id}/git/diff?path=...
```

## Invariants
- Frontend must not access arbitrary server paths — all file access via WorkspaceManager API
- File browsing is always read-only for the UI; writes go through the agent + proposal flow
- Workspace console tree/file/status/diff reads enforce `workspace.read` before data is returned
- Workspace list remains membership-scoped and does not create one policy record per row
- PathPolicy validates all requested paths and blocks traversal plus secret-like paths such
  as `.env*` except committed env templates (`.env.*.example`, `.env.sample`, `.env.template`), private keys,
  `.ssh`, `.aws`, and secrets directories
- Git operations must be scoped to the workspace root; no `..` traversal allowed
- Full git diff output is bounded. Full diff, system-managed, external-root,
  protected/restricted, and secret-like read attempts force policy audit records.
- Secret-like diff values are redacted. Diffs touching secret-like paths are denied.
- `resource_space_id` for policy enforcement comes from the actual Workspace row,
  not caller-supplied input.

## Related Files
- `core/backend/app/models.py` — Workspace, WorkspaceMembership
- `core/backend/app/schemas.py` — WorkspaceCreate, WorkspaceOut
- `core/backend/app/workspace_console/api.py` — workspace console read API
- `core/backend/app/workspace/` — WorkspaceManager, PathPolicy, SandboxManager
- `core/backend/app/workspace/path_policy.py` — PathPolicy enforcement
- `frontend/src/pages/` — TODO: workspace console pages
- `frontend/src/api/` — TODO: workspace API client

## TODO
- Frontend workspace console pages
- Artifact download UI
