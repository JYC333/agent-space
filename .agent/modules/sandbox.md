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
| `ephemeral`       | run          | server throwaway dir (no git)         | ✓ system scratch    | ✗                 | No             |
| `worktree`        | repo         | server process             | ✓ git worktree      | ✗                 | **No**         |
| `one_shot_docker` | worktree/plain dir | Docker sandbox executor       | ✓                  | ✓                | Yes            |

**File-access adapter rule (`claude_code` / `codex_cli`):** the working-directory
scope is resolved from workspace binding + risk (working-dir scope ladder, slice-1):

- **No workspace bound + low/medium risk → `ephemeral`** (run-scope): a
  system-provisioned throwaway working dir (no git, no persistent workspace),
  for chat / one-shot / non-coding CLI tasks. Provisioned and torn down by the
  server directly under `$SANDBOX_ROOT/ephemeral/`. **VERIFIED**
  by a real `claude_code` run 2026-06-14.
- **Workspace bound → `worktree`** (repo-scope): requires `risk_level=high`;
  the coding/mutating path with diff → `code_patch` proposal.
- **`high`/`critical` are never downgraded (B13):** high→worktree (needs a
  workspace), critical→one_shot_docker. If Docker is unavailable, the run
  fails closed; it never falls back to a server subprocess.

A file-access adapter that resolves to a non-isolating level (`none`/`dry_run`)
fails before the `adapter_started` RunStep with
`error_code=file_access_adapter_requires_worktree_policy`. Resolution lives in
`server/src/modules/runs/orchestrationService.ts` and runtime policy helpers (`resolve_sandbox_level` /
`file_access_sandbox_error`), shared by execution and preflight.

**`worktree` (high risk):**
The CLI runs as a subprocess of the server process with
`cwd=sandboxes/{run_id}/`.
No new container is spawned. Docker images are no longer the runtime tool
source; vendor CLIs are installed as instance runtime tools under
`$AGENT_SPACE_HOME/runtime-tools` and resolved by `RuntimeToolRegistry`.
Provides workspace isolation only — the process has the same access as the
server container.
Appropriate for trusted personal/family use where you control the deployment.

**`one_shot_docker` (critical):**
The server prepares the same run-scoped worktree/plain directory used for the
run, then `DockerCliCommandExecutor` mounts it at `/workspace`. The executor
mounts the instance runtime-tools tree read-only and at most one credential
profile read-only. It uses `--network none`, a read-only root, dropped
capabilities, `no-new-privileges`, PID/CPU/memory limits, and bounded tmpfs.
Provider-proxy and network-profile execution is rejected until an explicit
egress-enabled Docker policy is reviewed.

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
server CLI executor: subprocess(["/aspace/runtime-tools/claude_code/active/.../claude", "--print", ...], cwd=sandboxes/{run_id})
    ↓  CLI runs as subprocess inside the backend process (no new container)
diff / artifacts created in sandboxes/{run_id}/
    ↓  SandboxContext.cleanup() → git worktree remove --force
```

The workspace root must be a git repository; validation fails before sandbox creation if it is not.

## Docker Sandbox Flow

```
sandboxes/{run_id}/          ← writable sandbox dir
    ↓  ContextCompiler writes CLAUDE.md / AGENTS.md here
DockerExecutor: docker run --rm
    -v {host_sandbox_dir}:/workspace      (rw)
    -v {host_runtime_tools}:/runtime-tools (ro)
    -v {host_credential_profile}:/home/sandbox/.runtime-profile (ro, optional)
    --memory=1g --cpus=1 --pids-limit=256
    --read-only --cap-drop=ALL --security-opt=no-new-privileges
    --network=none --tmpfs=/tmp:rw,noexec,nosuid,size=128m
    agent-space-sandbox  claude --print "..."
    ↓  CLI runs inside a new container, isolated from the backend
diff / artifacts in /workspace → visible on host via volume mount
```

## Sandbox Image

Planned one-shot Docker runs use a separately built image:
```bash
docker build --network=host -t agent-space-sandbox sandbox/
```

The sandbox image does not bake in vendor CLIs. Docker execution mounts and
resolves the same instance runtime-tool installation explicitly. The image
reference is configurable through `SERVER_CLI_SANDBOX_IMAGE` and is never
pulled at run time (`--pull=never`).

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

- Docker container: removed immediately after run (`--rm --init`)
- Sandbox dir: `SandboxContext.cleanup()` → `git worktree remove --force` or `shutil.rmtree`
- Collect artifacts before cleanup

## Invariants
- `claude_code` and `codex_cli` always run sandboxed (B13); they never run at `none`/`dry_run`. A no-workspace CLI run resolves to `ephemeral`; a workspace-bound CLI run requires `risk_level=high` → `worktree`
- `ephemeral` (run-scope) is a system-provisioned throwaway working dir (no git, no persistent workspace), provisioned + torn down by the server under `$SANDBOX_ROOT/ephemeral/<space>/<run>`. No real workspace is touched
- `worktree` (repo-scope): `risk_level=high` → the agent receives a detached git worktree, never the real workspace directory
- Workspace roots outside `settings.workspace_root` require `Workspace.allow_external_root=True`; validation fails before sandbox creation otherwise
- High risk remains a server subprocess inside a worktree; critical local-CLI
  runs always use the Docker executor and are fail-closed if it cannot start
- CLAUDE.md / AGENTS.md are written to the sandbox dir (worktree or ephemeral), never to the real workspace
- File changes from a `worktree` run become a `code_patch` proposal; real workspace mutation happens only after the proposal is accepted. (Ephemeral runs have no workspace to diff; their output is materialized to artifacts.)

## Related Files
- `server/src/modules/runs/ephemeralSandbox.ts` — run-scope ephemeral sandbox
- `server/src/modules/workspaces/` — worktree and workspace path preparation
- `server/src/modules/workspaces/pathPolicy.ts` — path and root validation
- `server/src/modules/runs/orchestrationService.ts` — runtime policy enforcement before execution
- `server/src/modules/runtimeTools/` — controlled CLI tool install, active version, executable resolution
- `server/src/modules/runs/vendorCliAdapter.ts` — server generic local CLI runtime path
- `sandbox/Dockerfile` — base sandbox image for critical-risk one_shot_docker runs
- `server/src/modules/runs/localCliExecution.ts` — local and Docker CLI executors
- `server/src/modules/providers/cli/hostPath.ts` — host path translation for daemon mounts

## Related Decisions
- [0005-desktop-runtime.md](../decisions/0005-desktop-runtime.md)
