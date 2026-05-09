# Module: Sandbox

## Purpose
Provide risk-proportionate isolation for agent runs. Two distinct concerns:

- **Workspace isolation** — the agent works in its own copy of files, cannot directly touch the real workspace
- **Process isolation** — the CLI process itself is contained (filesystem, network, resources)

## Sandbox Levels

| Risk Level | Sandbox Level     | CLI runs in               | Workspace isolation | Process isolation | New container? |
|------------|-------------------|---------------------------|---------------------|-------------------|----------------|
| low        | `dry_run`         | nowhere                   | —                   | —                 | No             |
| medium     | `worktree`        | backend process           | ✓ git worktree      | ✗                 | **No**         |
| high       | `one_shot_docker` | sandbox container         | ✓ volume mount      | ✓                 | Yes            |
| critical   | `one_shot_docker` | sandbox container         | ✓ volume mount      | ✓                 | Yes            |

**`worktree` (medium — default):**
The CLI runs as a subprocess of the backend process with `cwd=sandboxes/{run_id}/`.
No new container is spawned. The backend image (Dockerfile) installs `claude` and `codex`
so this works identically on bare-metal and in Docker Compose.
Provides workspace isolation only — the process has the same access as the backend.
Appropriate for trusted personal/family use where you control the deployment.

**`one_shot_docker` (high/critical):**
A new `agent-space-sandbox` container is spawned per run. Only the sandbox directory and
(optionally) the workspace repo are visible. Full process containment.
Required when you need hard resource limits or stricter filesystem boundaries.

## Owns
- `SandboxManager` — creates sandbox environments per run
- `SandboxContext` — per-run state (level, path, is_git_worktree, executor_type)
- `DockerExecutor` — runs commands inside one-shot Docker containers
- Host path translation (`_resolve_host_path()` via /proc/self/mountinfo)
- Docker concurrency limiter (`get_docker_semaphore()`)
- `PathPolicy` — validates workspace file access paths

## Worktree Flow (medium risk)

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

Falls back to plain `mkdir` when the workspace is not a git repo.

## Docker Sandbox Flow (high/critical risk)

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

Built separately (needed for high/critical risk only):
```bash
docker build --network=host -t agent-space-sandbox deployments/sandbox/
```

The backend Dockerfile also installs `claude` and `codex` for medium-risk worktree runs.
Both images install the same CLI tools; they serve different isolation purposes.

## Concurrency Control

`threading.BoundedSemaphore(MAX_CONCURRENT_DOCKER_RUNS)` — limits simultaneous Docker containers.
Worktree runs are not counted; they run as backend subprocesses.
Default: 3. Configurable via `MAX_CONCURRENT_DOCKER_RUNS` env var.

## Docker-in-Docker Path Translation

When spawning high-risk containers, volume paths must be HOST paths (Docker daemon interprets
them relative to the host). `_resolve_host_path()` reads `/proc/self/mountinfo` to translate.

## Context File Injection

Adapters check `self.sandbox_dir is not None`:
- Set → `ContextCompiler.compile()` writes CLAUDE.md / AGENTS.md into sandbox dir; prompt is task goal only.
- None → context JSON embedded in the prompt string (echo/test paths only).

## Cleanup

- Docker container: removed immediately after run (`remove=True` in DockerExecutor)
- Sandbox dir: `SandboxContext.cleanup()` → `git worktree remove --force` or `shutil.rmtree`
- Collect artifacts before cleanup

## Invariants
- `claude_cli` and `codex_cli` are always sandboxed — `_SANDBOXED_ADAPTERS` in runner.py
- An agent can escalate `risk_level` but cannot remove itself from `_SANDBOXED_ADAPTERS`
- Medium risk never spawns a new container — CLI runs as a backend subprocess in the worktree
- CLAUDE.md / AGENTS.md are written to the sandbox dir, never to the real workspace

## Related Files
- `core/backend/app/workspace/sandbox_manager.py` — SandboxManager, SandboxContext, SandboxLevel
- `core/backend/app/agents/cli_adapter.py` — DockerExecutor, LocalExecutor
- `core/backend/app/agents/runner.py` — _resolve_adapter, _SANDBOXED_ADAPTERS
- `core/backend/Dockerfile` — installs claude + codex for worktree (medium-risk) runs
- `deployments/sandbox/Dockerfile` — sandbox image for high/critical-risk runs
- `deployments/local/docker-compose.yml` — mounts Docker socket for high-risk container spawning

## Related Decisions
- [0005-desktop-runtime.md](../decisions/0005-desktop-runtime.md)
