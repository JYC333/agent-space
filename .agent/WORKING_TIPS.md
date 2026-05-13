# Working Tips

Practical gotchas and non-obvious behaviours discovered during development.
These are facts the codebase doesn't make obvious at a glance.

---

## Workspaces

**Creating a workspace auto-creates a folder on disk — but only if the Docker volume is writable.**

`POST /api/v1/workspaces` now calls `Path.mkdir()` on `workspace_root/<id>/`
when no explicit `path` is supplied. This only works if the container can write
to the workspaces mount. In `deployments/local/docker-compose.yml` the mount
was originally `:ro` (read-only), which silently blocked mkdir; the `:ro` flag
has been removed. PathPolicy still enforces read-only access at the API layer
for the file browser — the `:ro` Docker flag was redundant.

If an explicit `path` is passed, the directory is assumed to already exist
on the host. Stale paths silently return 404 from the file tree API.

**Workspace path resolution (workspace_console api):**
```
ws.path is absolute → use as-is
ws.path is relative → workspace_root / ws.path
ws.path is None     → workspace_root / ws.id   (pre-normalized rows only)
```

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
`_FORBIDDEN_WRITE_SUFFIXES` in `core/backend/app/workspace/path_policy.py`.

---

## Workspace Console — Runtime Execution

**There are two execution paths: synchronous and async.**

| Runtime         | Path        | How it works |
|-----------------|-------------|--------------|
| `mock`          | Sync        | Returns hardcoded demo events immediately |
| `anthropic_api` | Sync        | Blocks on `AnthropicAPIAdapter.run()`, returns completed session |
| `claude_code`   | Async (BG)  | Saves status="running", dispatches `BackgroundTask`, returns immediately |
| `codex`         | Async (BG)  | Same as claude_code |

Frontend polls `GET /workspace-console/sessions/{id}` every 2 s while
`session.status === "running"`, then replays events with animation once done.

**`ClaudeCLIAdapter` now accepts a `model` kwarg.**

Pass `ClaudeCLIAdapter(model="claude-opus-4-7")` and it adds `--model` to the
CLI command. Without a model, the CLI uses its configured default.

**Background tasks use `_open_session()` — patch it in tests.**

`_execute_session_background` opens its own DB session via `wc_api._open_session()`
(not the request's `get_db()` session which is already closed). In tests, monkeypatch
`app.workspace_console.api._open_session` to return a session bound to the test engine.

**Runtime availability is checked live on every `GET /runtimes` call.**

Each adapter's `is_available()` is called at request time. For `claude_code` this
checks `shutil.which("claude")`. For `anthropic_api` it checks that the `anthropic`
package is importable and `ANTHROPIC_API_KEY` is set.

**Console sessions run in the workspace directory — no sandbox.**

CLI adapters are called with `sandbox_dir=None` and `workspace_path=<ws.path>`.
This means they execute directly in the workspace (no git worktree, no Docker).
For production use with untrusted prompts, wire through `runner.py`'s sandbox
infrastructure instead.

---

## Modules

**Module route prefix comes from the `router = APIRouter(prefix=...)` in `api.py`.**

The `modules/registry.py` loader mounts each router at `/api/v1` and lets the
`prefix` on the router define the rest of the path. Keep prefixes unique.

**Frontend module components must be lazy-imported in `registry.ts`.**

Use `lazy(() => import('./module_id/PageName'))`. Non-lazy imports break the
bundle split and slow initial load.
