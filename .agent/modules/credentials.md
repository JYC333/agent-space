# Module: CLI Credentials

## Design Statement

CLI login state belongs to agent-space, not to individual sandboxes.

Sandboxes receive short-lived, minimal, audited access to one approved CLI credential profile.

## Problem

The backend runs inside Docker. CLI tools (Claude Code, Codex, OpenCode) need their login
state at runtime. Without credential management:
- The user must log in manually inside every sandbox → unacceptable.
- The full backend HOME is mounted into every sandbox → security risk.
- CLI login state is untracked and unaudited.

## Solution: CredentialBroker

The `CredentialBroker` (`server/src/modules/providers/cliCredentialBroker.ts`) manages:
- **Profile discovery** — reads `instance/config/cli-credentials.yaml` + auto-discovers `instance/secrets/cli-credentials/<runtime>/<name>/` directories.
- **Grants** — before each run, the broker issues a `CredentialGrant` scoped to one profile.
- **Cleanup** — removes per-run temp HOME dirs after the run completes.
- **Audit** — every grant, denied grant, or no-profile failure is recorded in `cli_credential_events`.

## Storage Layout

```
instance/
└── secrets/
    └── cli-credentials/
        ├── claude_code/
        │   └── default/      ← Claude Code login state (~/.claude contents)
        ├── codex_cli/
        │   └── default/      ← Codex login state (~/.codex contents)
        └── opencode/
            └── default/
```

This directory is private, not committed, and mounted via Docker Compose at `/app/instance`.

## Config File

`instance/config/cli-credentials.yaml` maps runtimes to profile directories:

```yaml
profiles:
  claude_code:
    default:
      source_path: "/app/instance/secrets/cli-credentials/claude_code/default"
      target_path: "/home/agent/.claude"
      readonly: false
```

If a profile directory exists but is not listed in the config, the broker auto-discovers it.
CLI runtimes do not fall back to the backend container's default HOME credentials.
Manual and automation runs both require an explicit resolved profile.

## Execution Modes

### Worktree Runtime

For high-risk file-access runs, the CLI runs as a subprocess inside a detached
git worktree. The broker:
1. Creates `instance/cache/runtime-homes/<run_id>/`
2. Symlinks the credential dir: `<run_id>/.claude → source_path`
3. Sets `HOME=<run_id>/` in the subprocess environment

The CLI finds its login state at the expected path without seeing the full container HOME.

```
/app/instance/cache/runtime-homes/<run_id>/
├── .claude  →  /app/instance/secrets/cli-credentials/claude_code/default/
└── (nothing else)
```

If no explicit profile is resolved, runtime execution fails before the runtime adapter is
invoked with `runtime_credential_profile_required`.

`one_shot_docker` is not implemented in this build. Critical-risk runs that
require that sandbox level fail closed before runtime invocation.

## Initializing a Profile

```bash
# Step 1: install the runtime tool through the server installer
curl -X POST localhost:3000/api/v1/runtime-tools/claude_code/install \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"version":"latest"}'

# Step 2: run the managed login stream from the frontend or API.
# The server launches the active runtime-tool binary and syncs the
# resulting login state into:
#   $AGENT_SPACE_HOME/secrets/cli-credentials/claude_code/default/

# Step 3: verify the broker sees it through the default server entrypoint
curl localhost:3000/api/v1/credentials/cli/profiles?runtime=claude_code
```

## Runtime Adapter Credential Spec

Each RuntimeAdapterSpec declares credential behavior in its `credentials`
section. Local CLI runtime adapters use explicit CLI credential profiles;
execution and preflight both require the selected profile source path to exist.

## Audit Events

Every credential usage writes a `CliCredentialEvent` record:

| Action | When |
|---|---|
| `credential.grant` | A profile was found and a grant was issued |
| `credential.grant_denied` | No profile was configured; runtime fails with `runtime_credential_profile_required` |
| `credential.grant_failed` | Grant failed after profile resolution, such as missing source path |

No-profile failures use `credential_source="none"` and
`fallback_reason="no_profile_configured"`. New successful
`container_default` fallback events must not be emitted.

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

- `server/src/modules/providers/` — credential broker/store and provider routes
- `server/src/modules/runtimeTools/` — controlled CLI tool installer and active binary registry
- `server/src/modules/runs/vendorCliAdapter.ts` — server CLI adapter profile grant behavior
- `server/src/modules/runtimeAdapters/` — CredentialSpec/runtime spec semantics
- `server/src/modules/runs/vendorCliAdapter.ts` — GenericCliRuntimeAdapter profile grant behavior
- `server/src/modules/runs/` — runtime execution integration and credential mount
- `server/migrations/` — CliCredentialEvent tables
- `instance/config/cli-credentials.yaml` — profile config (private)
- `instance/secrets/cli-credentials/` — credential directories (gitignored)
