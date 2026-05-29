# Module: Sandbox

## Purpose
Provide risk-proportionate isolation for agent runs. Two distinct concerns:

- **Workspace isolation** — the agent works in its own copy of files, cannot directly touch the real workspace
- **Process isolation** — the CLI process itself is contained (filesystem, network, resources)

## Sandbox Levels

| Risk Level | Sandbox Level     | CLI runs in               | Workspace isolation | Process isolation | New container? |
|------------|-------------------|---------------------------|---------------------|-------------------|----------------|
| low        | `none`            | nowhere (no adapter exec) | —                   | —                 | No             |
| medium     | `dry_run`         | nowhere (no adapter exec) | —                   | —                 | No             |
| high       | `worktree`        | backend process           | ✓ git worktree      | ✗                 | **No**         |
| critical   | `one_shot_docker` | not currently available   | planned             | planned           | Planned        |

**File-access adapter requirement:** `claude_code` and `codex_cli` require `risk_level=high`.
The execution service validates this before starting the adapter and fails the run with
`error_code=file_access_adapter_requires_worktree_policy` if the policy is unsafe.
This check fires before the `adapter_started` RunStep so the misconfiguration is surfaced
as a configuration error, not a mid-execution failure.

**`worktree` (high risk):**
The CLI runs as a subprocess of the backend process with `cwd=sandboxes/{run_id}/`.
No new container is spawned. The backend image (Dockerfile) installs `claude` and `codex`
so this works identically on bare-metal and in Docker Compose.
Provides workspace isolation only — the process has the same access as the backend.
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
LocalExecutor: subprocess(["claude", "--print", ...], cwd=sandboxes/{run_id})
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
docker build --network=host -t agent-space-sandbox deployments/sandbox/
```

The backend Dockerfile also installs `claude` and `codex` for high-risk worktree runs.
Both images install the same CLI tools; they serve different isolation purposes.

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
- None → context JSON embedded in the prompt string (echo/test paths only).

## Cleanup

- Future Docker container: removed immediately after run (`remove=True` in DockerExecutor)
- Sandbox dir: `SandboxContext.cleanup()` → `git worktree remove --force` or `shutil.rmtree`
- Collect artifacts before cleanup

## Invariants
- `claude_code` and `codex_cli` require `risk_level=high`; the execution service rejects any run where these adapters are paired with a lower risk level before the adapter starts
- `risk_level=high` → `required_sandbox_level=worktree`; the agent always receives a detached git worktree, never the real workspace directory
- Workspace roots outside `settings.workspace_root` require `Workspace.allow_external_root=True`; validation fails before sandbox creation otherwise
- High risk never spawns a new container — CLI runs as a backend subprocess inside the worktree
- Critical one-shot Docker is fail-closed until the product path is implemented and tested
- CLAUDE.md / AGENTS.md are written to the sandbox dir, never to the real workspace
- File changes from the worktree become a `code_patch` proposal; real workspace mutation happens only after the proposal is accepted

## Related Files
- `core/backend/app/runs/sandbox_manager.py` — execution_workspace context manager
- `core/backend/app/runs/workspace_worktree.py` — workspace_git_worktree (detached git worktree creation)
- `core/backend/app/runs/worktree_manager.py` — isolated_run_workdir (plain temp dir fallback)
- `core/backend/app/workspace/root_validation.py` — validate_workspace_root_for_execution
- `core/backend/app/runs/runtime_policy.py` — validate_file_access_adapter_policy, risk→sandbox mapping
- `core/backend/app/runtimes/local_executor.py` — local subprocess execution
- `core/backend/app/runtimes/adapters/cli_runtime.py` — generic local CLI runtime path
- `core/backend/Dockerfile` — installs claude + codex for high-risk worktree runs
- `deployments/sandbox/Dockerfile` — sandbox image for critical-risk one_shot_docker runs
- `deployments/local/docker-compose.yml` — mounts Docker socket for critical-risk container spawning

## Related Decisions
- [0005-desktop-runtime.md](../decisions/0005-desktop-runtime.md)
