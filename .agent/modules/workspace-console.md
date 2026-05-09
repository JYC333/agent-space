# Module: Workspace Console

## Status
**PLANNED** — UI views not yet implemented. Backend WorkspaceManager partially implemented.

## Purpose
Browser-based interface for browsing workspace files, reviewing agent run outputs, inspecting diffs, and approving proposals. All file access goes through server-side managers — the frontend never accesses the host filesystem directly.

## Owns
- Workspace file browser UI
- Git status and diff viewer UI
- Agent run log viewer UI
- Artifact browser UI
- Proposal review and approval UI
- `WorkspaceManager` backend service (file access, git operations)

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

## Backend API (Planned)

```
GET  /api/v1/workspaces
GET  /api/v1/workspaces/{id}/files?path=...
GET  /api/v1/workspaces/{id}/git/status
GET  /api/v1/workspaces/{id}/git/diff
GET  /api/v1/workspaces/{id}/runs
GET  /api/v1/workspaces/{id}/artifacts
POST /api/v1/workspaces/{id}/proposals/{pid}/approve
POST /api/v1/workspaces/{id}/proposals/{pid}/reject
```

## Invariants
- Frontend must not access arbitrary server paths — all file access via WorkspaceManager API
- File browsing is always read-only for the UI; writes go through the agent + proposal flow
- WorkspaceManager must validate all paths via PathPolicy before reading or writing
- Git operations must be scoped to the workspace root; no `..` traversal allowed

## Related Files
- `core/backend/app/models.py` — Workspace, WorkspaceMembership
- `core/backend/app/schemas.py` — WorkspaceCreate, WorkspaceOut
- `core/backend/app/workspace/` — WorkspaceManager (TODO), PathPolicy, SandboxManager
- `core/backend/app/workspace/path_policy.py` — PathPolicy enforcement
- `frontend/src/pages/` — TODO: workspace console pages
- `frontend/src/api/` — TODO: workspace API client

## TODO
- WorkspaceManager file browsing API
- Git status/diff API
- Frontend workspace console pages
- Artifact download UI
