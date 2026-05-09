# Module: CLI Credentials

## Design Statement

CLI login state belongs to agent-space, not to individual sandboxes.

Sandboxes receive temporary, minimal, audited access to one approved CLI credential profile.

## Problem

The backend runs inside Docker. CLI tools (Claude Code, Codex, OpenCode) need their login
state at runtime. Without credential management:
- The user must log in manually inside every sandbox → unacceptable.
- The full backend HOME is mounted into every sandbox → security risk.
- CLI login state is untracked and unaudited.

## Solution: CredentialBroker

The `CredentialBroker` (`app/credentials/broker.py`) manages:
- **Profile discovery** — reads `instance/config/cli-credentials.yaml` + auto-discovers `instance/secrets/cli-credentials/<runtime>/<name>/` directories.
- **Grants** — before each run, the broker issues a `CredentialGrant` scoped to one profile.
- **Cleanup** — removes per-run temp HOME dirs after the run completes.
- **Audit** — every grant (or skip) is recorded in `cli_credential_events`.

## Storage Layout

```
instance/
└── secrets/
    └── cli-credentials/
        ├── claude-code/
        │   └── default/      ← Claude Code login state (~/.claude contents)
        ├── codex/
        │   └── default/      ← Codex login state (~/.codex or API key file)
        └── opencode/
            └── default/
```

This directory is private, not committed, and mounted via Docker Compose at `/app/instance`.

## Config File

`instance/config/cli-credentials.yaml` maps runtimes to profile directories:

```yaml
profiles:
  claude-code:
    default:
      source_path: "/app/instance/secrets/cli-credentials/claude-code/default"
      target_path: "/home/agent/.claude"
      readonly: false
```

If a profile directory exists but is not listed in the config, the broker auto-discovers it.

## Execution Modes

### Worktree (medium-risk)

The CLI runs as a subprocess inside the backend container. The broker:
1. Creates `instance/cache/runtime-homes/<run_id>/`
2. Symlinks the credential dir: `<run_id>/.claude → source_path`
3. Sets `HOME=<run_id>/` in the subprocess environment

The CLI finds its login state at the expected path without seeing the full container HOME.

```
/app/instance/cache/runtime-homes/<run_id>/
├── .claude  →  /app/instance/secrets/cli-credentials/claude-code/default/
└── (nothing else)
```

### Docker (high-risk)

A one-shot Docker container is spawned. The broker returns `host_source_path` + `target_path`
for a volume mount. The credential dir is mounted read-only by default:

```
docker run ...
  -v /host/instance/secrets/cli-credentials/claude-code/default:/home/agent/.claude:ro
  ...
```

If the CLI needs write access (token refresh), set `readonly: false` in the config.
The profile directory is then mounted writable into the container.

## Option A vs Option B

| | Option A (simplest MVP) | Option B (explicit profile) |
|---|---|---|
| Setup | Claude Code already logged in inside backend container | Credential dir copied to `instance/secrets/cli-credentials/claude-code/default/` |
| Broker behavior | Returns `None` grant → uses container's default `~/.claude` | Returns grant with temp HOME symlink |
| Security boundary | Backend container HOME is shared for all runs | Per-run temp HOME, only selected profile |
| When to use | Personal MVP, single-user | Multi-profile, production |

Both work. The broker is transparent about which path is taken (logged + audited).

## Initializing a Profile (Option B)

```bash
# Step 1: log in inside the backend container
docker exec -it agent-space-backend bash
claude login

# Step 2: copy the resulting ~/.claude into the managed profile dir
cp -r ~/.claude /app/instance/secrets/cli-credentials/claude-code/default/

# Step 3: verify the broker sees it
curl localhost:8000/api/v1/credentials/cli/profiles?runtime=claude-code
```

## Adapter Credential Spec

Each CLI adapter declares its requirements via `get_credential_spec()`:

```python
class ClaudeCLIAdapter(AgentAdapter):
    def get_credential_spec(self) -> CredentialSpec:
        return CredentialSpec(
            runtime="claude-code",
            required=False,             # False → falls back to container default (Option A)
            default_target_path="/home/agent/.claude",
            supports_read_only=False,   # Claude Code may refresh tokens
            env_auth_var=None,
        )
```

## Audit Events

Every credential usage writes a `CliCredentialEvent` record:

| Action | When |
|---|---|
| `credential.grant` | A profile was found and a grant was issued |
| `credential.skipped` | No profile configured; using container default (Option A) |
| `credential.denied` | Grant failed (profile dir missing, policy, etc.) |

## What Sandboxes Must NOT See

- `/app/instance/db` — database
- `/app/instance/secrets` (except the one granted profile dir)
- Other users' credential profiles
- The backend source root
- SSH keys, AWS credentials, Docker socket (unless explicitly granted)
- The full backend container HOME

## API

```
GET  /api/v1/credentials/cli/profiles                 — list profiles (reloads from disk)
GET  /api/v1/credentials/cli/profiles/{id}            — get one profile
POST /api/v1/credentials/cli/profiles/{id}/detect     — check if source_path exists
```

## Related Files

- `core/backend/app/credentials/broker.py` — CredentialBroker, CredentialProfile, CredentialGrant
- `core/backend/app/credentials/api.py` — FastAPI routes
- `core/backend/app/agents/base.py` — CredentialSpec dataclass
- `core/backend/app/agents/claude_adapter.py` — get_credential_spec(), credential_grant usage
- `core/backend/app/agents/runner.py` — broker integration, temp HOME cleanup
- `core/backend/app/agents/cli_adapter.py` — LocalExecutor (HOME env), DockerExecutor (credential_volumes)
- `core/backend/app/workspace/sandbox_manager.py` — get_docker_adapter() credential mount
- `core/backend/app/models.py` — CliCredentialEvent
- `instance/config/cli-credentials.yaml` — profile config (private)
- `instance/secrets/cli-credentials/` — credential directories (gitignored)
