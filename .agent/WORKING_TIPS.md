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

**Workspace path resolution (workspace_console api):**
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
`_FORBIDDEN_WRITE_SUFFIXES` in `backend/app/workspace/path_policy.py`.

---

## Workspace Console — Runtime Execution

**Console sessions use local CLI runtimes only (async background tasks).**

| Runtime       | Path       | How it works |
|---------------|------------|--------------|
| `claude_code` | Async (BG) | Saves status="running", dispatches `BackgroundTask`, returns immediately |
| `codex_cli`   | Async (BG) | Same as claude_code |

Policy: Console sessions are local CLI runtimes (claude_code, codex_cli). Per ADR 0010 the
invariant is **credential channel isolation** — an Anthropic API key must never enter a Claude
Code CLI subprocess env (enforced by `local_executor.build_subprocess_env`'s allowlist). The
in-process encrypted API channel (the reflector, `/providers/chat`) passes the key as a litellm
parameter, never via env, and may serve any provider including Anthropic. The generic
vendor-neutral API *runtime* adapter (`model_api`) uses that same in-process channel.

Frontend polls `GET /workspace-console/sessions/{id}` every 2 s while
`session.status === "running"`, then replays events with animation once done.

**RuntimeAdapterSpec owns local CLI command semantics.**

Model flags, permission bypass flags, invocation templates, and output parser
selection are declared in `backend/app/runtimes/specs.py`. CLI binary install
and status use the TS-controlled `/api/v1/runtime-tools` API; the retired
`/api/v1/runtime-adapters` instance API must not be used.

**Console sessions run in the workspace directory — no sandbox.**

Local CLI runtimes are called with `sandbox_dir=None` and `workspace_path=<ws.path>`.
This means they execute directly in the workspace (no git worktree, no Docker).
For production use with untrusted prompts, wire through the sandbox
infrastructure instead.

---

## Modules

**Module route prefix comes from the `router = APIRouter(prefix=...)` in `api.py`.**

The `modules/registry.py` loader mounts each router at `/api/v1` and lets the
`prefix` on the router define the rest of the path. Keep prefixes unique.

**Frontend module components must be lazy-imported in `registry.ts`.**

Use `lazy(() => import('./module_id/PageName'))`. Non-lazy imports break the
bundle split and slow initial load.
