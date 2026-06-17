# Module: Sandbox

## Purpose
Provide risk-proportionate isolation for agent runs. Two distinct concerns:

- **Workspace isolation** — the agent works in its own copy of files, cannot directly touch the real workspace
- **Process isolation** — the CLI process itself is contained (filesystem, network, resources)

## Sandbox Levels

| Sandbox Level     | Scope        | CLI runs in                       | Workspace isolation | Process isolation | New container? |
|-------------------|--------------|-----------------------------------|---------------------|-------------------|----------------|
| `none`            | —            | nowhere (no adapter exec)         | —                   | —                 | No             |
| `dry_run`         | —            | nowhere (no adapter exec)         | —                   | —                 | No             |
| `ephemeral`       | run          | TS throwaway dir (no git)         | ✓ system scratch    | ✗                 | No             |
| `worktree`        | repo         | backend process                   | ✓ git worktree      | ✗                 | **No**         |
| `one_shot_docker` | —            | not currently available           | planned             | planned           | Planned        |

**File-access adapter rule (`claude_code` / `codex_cli`):** the working-directory
scope is resolved from workspace binding + risk (working-dir scope ladder, slice-1):

- **No workspace bound + low/medium risk → `ephemeral`** (run-scope): a
  system-provisioned throwaway working dir (no git, no persistent workspace),
  for chat / one-shot / non-coding CLI tasks. Provisioned and torn down by the
  control-plane (TS) directly under `$SANDBOX_ROOT/ephemeral/`. **VERIFIED**
  by a real `claude_code` run 2026-06-14.
- **Workspace bound → `worktree`** (repo-scope): requires `risk_level=high`;
  the coding/mutating path with diff → `code_patch` proposal.
- **`high`/`critical` are never downgraded (B13):** high→worktree (needs a
  workspace), critical→one_shot_docker (fail-closed, unimplemented).

A file-access adapter that resolves to a non-isolating level (`none`/`dry_run`)
fails before the `adapter_started` RunStep with
`error_code=file_access_adapter_requires_worktree_policy`. Resolution lives in
`backend/app/runs/runtime_policy.py` (`resolve_sandbox_level` /
`file_access_sandbox_error`), shared by execution and preflight.

**`worktree` (high risk):**
The CLI runs as a subprocess of the control-plane process with
`cwd=sandboxes/{run_id}/`.
No new container is spawned. Docker images are no longer the runtime tool
source; vendor CLIs are installed as instance runtime tools under
`$AGENT_SPACE_HOME/runtime-tools` and resolved by `RuntimeToolRegistry`.
Provides workspace isolation only — the process has the same access as the
control-plane container.
Appropriate for trusted personal/family use where you control the deployment.

**`one_shot_docker` (critical/future):**
One-shot Docker is the intended hard-isolation path, but it is not currently active in
the backend product path. Critical/high paths that require Docker process isolation
must fail closed rather than silently downgrading to worktree execution.

## Owns
- `SandboxManager` — creates sandbox environments per run
- `SandboxContext` — per-run state (level, path, is_git_worktree, execution_mode)
- `DockerExecutor` — runs commands inside one-shot Docker containers
- Host path translation (`_resolve_host_path()` via /proc/self/mountinfo)
- Docker concurrency limiter (`get_docker_semaphore()`)
- `PathPolicy` — validates workspace file access paths

## Worktree Flow (high risk)

```
real workspace (git repo)
    ↓  git worktree add --detach sandboxes/{run_id}
sandboxes/{run_id}/          ← agent's CWD, has full git history
    ↓  ContextCompiler writes CLAUDE.md / AGENTS.md here
TS CLI executor: subprocess(["/aspace/runtime-tools/claude_code/active/.../claude", "--print", ...], cwd=sandboxes/{run_id})
    ↓  CLI runs as subprocess inside the backend process (no new container)
diff / artifacts created in sandboxes/{run_id}/
    ↓  SandboxContext.cleanup() → git worktree remove --force
```

The workspace root must be a git repository; validation fails before sandbox creation if it is not.

## Docker Sandbox Flow (planned)

```
sandboxes/{run_id}/          ← writable sandbox dir
    ↓  ContextCompiler writes CLAUDE.md / AGENTS.md here
DockerExecutor: docker run --rm
    -v {host_sandbox_dir}:/workspace      (rw)
    -v {host_workspace}:/workspace/repo   (ro, optional)
    --memory=1g --cpus=1
    --network=bridge
    agent-space-sandbox  claude --print "..."
    ↓  CLI runs inside a new container, isolated from the backend
diff / artifacts in /workspace → visible on host via volume mount
```

## Sandbox Image

Planned one-shot Docker runs use a separately built image:
```bash
docker build --network=host -t agent-space-sandbox sandbox/
```

The sandbox image does not bake in vendor CLIs. Future Docker execution must
mount/resolve the same instance runtime tool installation explicitly.

## Concurrency Control

`threading.BoundedSemaphore(MAX_CONCURRENT_DOCKER_RUNS)` — intended to limit
simultaneous one-shot Docker containers when that path is enabled. Worktree runs are
not counted; they run as backend subprocesses.
Default: 3. Configurable via `MAX_CONCURRENT_DOCKER_RUNS` env var.

## Docker-in-Docker Path Translation

When spawning future one-shot Docker containers, volume paths must be HOST paths (Docker daemon interprets
them relative to the host). `_resolve_host_path()` reads `/proc/self/mountinfo` to translate.

## Context File Injection

Adapters check `self.sandbox_dir is not None`:
- Set → `ContextCompiler.compile()` writes CLAUDE.md / AGENTS.md into sandbox dir; prompt is task goal only.
- None → context JSON is handled in-process by native/API runtimes that do not need a vendor context file.

## Cleanup

- Future Docker container: removed immediately after run (`remove=True` in DockerExecutor)
- Sandbox dir: `SandboxContext.cleanup()` → `git worktree remove --force` or `shutil.rmtree`
- Collect artifacts before cleanup

## Invariants
- `claude_code` and `codex_cli` always run sandboxed (B13); they never run at `none`/`dry_run`. A no-workspace CLI run resolves to `ephemeral`; a workspace-bound CLI run requires `risk_level=high` → `worktree`
- `ephemeral` (run-scope) is a system-provisioned throwaway working dir (no git, no persistent workspace), provisioned + torn down by the control-plane (TS) under `$SANDBOX_ROOT/ephemeral/<space>/<run>`. No real workspace is touched
- `worktree` (repo-scope): `risk_level=high` → the agent receives a detached git worktree, never the real workspace directory
- Workspace roots outside `settings.workspace_root` require `Workspace.allow_external_root=True`; validation fails before sandbox creation otherwise
- High risk never spawns a new container — CLI runs as a backend subprocess inside the sandbox dir
- Critical one-shot Docker is fail-closed until the product path is implemented and tested
- CLAUDE.md / AGENTS.md are written to the sandbox dir (worktree or ephemeral), never to the real workspace
- File changes from a `worktree` run become a `code_patch` proposal; real workspace mutation happens only after the proposal is accepted. (Ephemeral runs have no workspace to diff; their output is materialized to artifacts.)

## Related Files
- `backend/app/runs/sandbox_manager.py` — execution_workspace context manager
- `backend/app/runs/workspace_worktree.py` — workspace_git_worktree (detached git worktree creation)
- `backend/app/runs/worktree_manager.py` — isolated_run_workdir (plain temp dir fallback)
- `backend/app/workspace/root_validation.py` — validate_workspace_root_for_execution
- `backend/app/runs/runtime_policy.py` — `resolve_sandbox_level` / `file_access_sandbox_error` (workspace+risk→sandbox scope), shared by execution and preflight
- `control-plane/src/modules/runs/ephemeralSandbox.ts` — TS-owned ephemeral (run-scope) working dir: scope mapping + prepare/remove under `$SANDBOX_ROOT/ephemeral`
- `control-plane/src/modules/runtimeTools/` — controlled CLI tool install, active version, executable resolution
- `control-plane/src/modules/runs/vendorCliAdapter.ts` — TS generic local CLI runtime path
- `backend/app/runtimes/local_executor.py` — legacy Python local subprocess execution for unowned paths
- `backend/app/runtimes/adapters/cli_runtime.py` — legacy Python generic local CLI runtime path
- `sandbox/Dockerfile` — base sandbox image for future critical-risk one_shot_docker runs
- `ops/compose/docker-compose.<mode>.yml` — mounts Docker socket for critical-risk container spawning

## Related Decisions
- [0005-desktop-runtime.md](../decisions/0005-desktop-runtime.md)
