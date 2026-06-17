# Working Tips

Practical gotchas and non-obvious behaviours discovered during development.
These are facts the codebase doesn't make obvious at a glance.

---

## Workspaces

**Creating a workspace auto-creates a folder on disk — but only if the Docker volume is writable.**

`POST /api/v1/workspaces` now calls `Path.mkdir()` on `workspace_root/<id>/`
when no explicit `path` is supplied. This only works if the container can write
to the workspaces mount. In the `ops/compose/docker-compose.<mode>.yml`
files the workspaces mount must not be `:ro` (read-only), which would silently
block mkdir. PathPolicy still enforces read-only access at the API layer
for the file browser — the `:ro` Docker flag was redundant.

If an explicit `path` is passed, the directory is assumed to already exist
on the host. Stale paths silently return 404 from the file tree API.

**Workspace path resolution (workspace-console routes under `workspaces`):**
```
ws.path is absolute → use as-is
ws.path is relative → workspace_root / ws.path
ws.path is None     → workspace_root / ws.id   (pre-normalized rows only)
```
For execution (worktree sandbox), `validate_workspace_root_for_execution()` additionally
enforces that the resolved root is under `settings.workspace_root` unless
`ws.allow_external_root=True`. Absolute paths outside the managed root fail unless
this flag is set.

---

## Frontend UI Components

**Always use `Select` from `components/ui/select.tsx` for dropdowns.**

Never use a bare `<select>` element — it won't pick up the design system
styling (border, bg-input, ring, dark mode). The custom `Select` takes
`options: { value, label }[]`, `value`, `onChange`, `size` (`sm` | `md`),
and an optional `dropUp` flag.

---

## PathPolicy

**PathPolicy rejects write access to `.py`, `.sh`, and similar source files.**

Agents may not write these directly; they must go through a `code_patch`
Proposal. Read access is allowed. The forbidden write suffixes are declared in
`FORBIDDEN_WRITE_SUFFIXES` in `server/src/modules/workspaces/pathPolicy.ts`.

---

## Workspace Console — Runtime Execution

**Console session execution is not active.**

Current workspace-console routes live inside the registered `workspaces` module.
Tree, file, git status, git diff, runtime status, and session list reads exist;
session create/detail/run/stop routes return the explicit feature-not-implemented
response. Do not describe workspace-console sessions as a current local CLI
execution path.

**RuntimeAdapterSpec owns local CLI command semantics.**

Model flags, permission bypass flags, invocation templates, and output parser
selection are declared in `server/src/modules/runtimeAdapters/specs.ts`. CLI binary install
and status use the server-controlled `/api/v1/runtime-tools` API; the retired
`/api/v1/runtime-adapters` instance API must not be used.

Managed CLI execution belongs to the server `runs` path, which prepares
ephemeral/worktree sandboxes and records evidence, artifacts, and proposals.

---

## Modules

**Module route ownership is explicit in `routeRegistry.ts`.**

Backend routes live in `server/src/modules/<module>/routes.ts`. A module
is active only when its `ServerModule` is listed in
`server/src/gateway/routeRegistry.ts`; unknown `/api/v1/*` routes return
the local server 404 catch-all.

**Frontend module components must be lazy-imported in `registry.ts`.**

Use `lazy(() => import('./module_id/PageName'))`. Non-lazy imports break the
bundle split and slow initial load.
