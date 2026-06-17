# Self-Evolution Deployment

## Overview

agent-space supports a protected self-evolution deployment structure where system code changes are managed through a controlled workflow: sandbox worktrees, diff collection, testing, proposal approval, and git merge.

## Directory Structure

```
~/.aspace/                    # ASPACE_ROOT: host-side parent (default ~/.aspace), holds mode roots
├── dev/                     # one mode root; bind-mounted as AGENT_SPACE_HOME=/aspace in containers
│   ├── .env
│   ├── config/              # app config (.env, cli-credentials.yaml)
│   ├── db/postgres/         # PostgreSQL data directory (bind-mounted into postgres container)
│   ├── db/dumps/            # pg_dump backup files
│   ├── storage/             # file uploads, exports
│   ├── logs/                # app + agent run logs
│   ├── cache/               # quota cache, runtime-homes
│   ├── runtime/             # transient runtime state
│   ├── workspaces/          # managed workspace repos (<workspace_id>/repo)
│   ├── sandboxes/           # per-run agent sandboxes
│   │   └── system-evolution/
│   │       └── <run_id>/    # git worktree created by deployer
│   ├── artifacts/           # run artifacts, diffs, patches, reports
│   ├── secrets/             # encrypted API keys, credentials
│   └── run/                 # Unix socket for deployer
│
├── test/                    # test mode root (same layout)
└── prod/                    # prod mode root (same layout)
```

## Instances

| Instance | Purpose | Ports | Compose Project |
|----------|---------|-------|-----------------|
| dev | Local dev with hot reload | 3000/8000 | agent-space-dev |
| test | Self-evolution validation | 3100/8100 | agent-space-test |
| prod | Production deployment | 3000/8000 | agent-space-prod |

## Repository Rules

- The repo must NOT contain real instance data.
- Keep only code, docs, migrations, compose templates, scripts, and example env templates.
- Do NOT store real `.env`, db files, uploaded files, memory data, logs, or secrets in git.

## Container Responsibilities

### Server Container

Owns:
- Agent runtime adapters
- Context builder
- Memory / activity / proposal system
- Policy checks
- UI / API
- File editing inside approved sandbox worktrees only

Server mounts:
- `${ASPACE_ROOT}/<env>:/aspace` (mode root for that environment)
- `${ASPACE_ROOT}/<env>/sandboxes:/aspace/sandboxes`
- `${ASPACE_ROOT}/<env>/run/deployer.sock:/aspace/run/deployer.sock`

Server must NOT mount:
- `/var/run/docker.sock`
- Writable `<AGENT_SPACE_HOME>/workspaces` (except via worktree sandbox)
- Other mode roots (`dev` from `test`, etc.)
- Host arbitrary paths

### Deployer Container

Owns:
- system_core git worktree creation
- Git status / diff collection
- Approved merge into canonical repo
- Test docker compose deployment
- Prod docker compose deployment
- Health checks
- Cleanup of system-evolution worktrees

Deployer mounts:
- `${REPO_ROOT}:/repo:ro` (the agent-space source repo)
- `${ASPACE_ROOT}/<env>/sandboxes:/aspace/sandboxes`
- `${ASPACE_ROOT}/<env>:/aspace` (mode root)
- `${ASPACE_ROOT}/<env>/run:/aspace/run`
- `/var/run/docker.sock:/var/run/docker.sock`

Deployer must NOT:
- Run Agent logic
- Call LLMs
- Write memory
- Create proposals
- Accept arbitrary shell commands
- Expose a public HTTP port

## Deployer Jobs

Communicate through Unix socket only. Accepts structured allowlisted jobs only.

| Job Type | Description |
|----------|-------------|
| `create_system_worktree` | Create a git worktree for a system evolution run |
| `collect_system_diff` | Collect git status/diff from a worktree |
| `run_system_tests` | Run allowlisted test profiles (backend, frontend, typecheck, lint, build) |
| `run_test_deploy` | Deploy test compose from a worktree |
| `merge_approved_system_patch` | Merge approved patch into canonical repo |
| `run_prod_deploy` | Deploy prod compose from canonical repo |
| `init_agent_space_worktree` | Clone canonical repo into worktree dir |
| `cleanup_system_worktree` | Remove a system evolution worktree |

## Self-Evolution Flow

1. **Server creates a system evolution run**
2. **Server asks deployer to create a worktree**
   ```
   deployer: create_system_worktree(RUN_ID=<run_id>)
   ```
3. **Server agent edits only** the worktree at `~/.aspace/dev/sandboxes/system-evolution/<run_id>`
4. **Server asks deployer to collect diff**
   ```
   deployer: collect_system_diff(WORKTREE_DIR=<path>)
   ```
5. **Server asks deployer to run tests**
   ```
   deployer: run_system_tests(WORKTREE_DIR=<path>, TEST_PROFILE=<profile>)
   ```
6. **Server creates a `code_patch` proposal** containing: changed files, diff, test logs, build logs, risk level, migration warning, test deployment status
7. **Optional test deploy**
   ```
   deployer: run_test_deploy(WORKTREE_DIR=<path>)
   ```
8. **After explicit approval**, server asks deployer to merge
   ```
   deployer: merge_approved_system_patch(WORKTREE_DIR=<path>, PROPOSAL_ID=<id>, BRANCH_NAME=<branch>)
   ```
9. **Production deploy**
   ```
   deployer: run_prod_deploy()
   ```

## Environment Variables

### Common
- `AGENT_SPACE_ENV=dev|test|prod`
- `INSTANCE_ROOT=/instance`
- `STORAGE_ROOT=/instance/storage`
- `LOG_ROOT=/instance/logs`
- `DATABASE_URL=...`
- `FRONTEND_URL=...`
- `BACKEND_URL=...`

### Self-Evolution
- `ENABLE_SYSTEM_EVOLUTION=true`
- `SYSTEM_CORE_REPO_PATH=/path/to/agent-space-repo` (must be an existing git repo)
- `SYSTEM_CORE_BASE_BRANCH=master`
- `SYSTEM_CORE_OWNER_EMAIL=<developer email>`
- `SYSTEM_EVOLUTION_SANDBOX_ROOT=~/.aspace/dev/sandboxes/system-evolution`

## System-Core Workspace Policy

- Registered from env/config only — not creatable through normal Add Workspace UI
- Registered into the developer's personal space with:
  - `workspace_type = system_core`
  - `protected = true`
  - `system_managed = true`
  - `registered_from = env`
- Even inside personal space, system_core uses system_core policy
- Personal space ownership does NOT bypass system_core policy

## Path Rules

- Backend Agent can write only the current run worktree
- Backend cannot write canonical repo
- Backend cannot access docker.sock
- Deployer can access canonical repo and docker.sock
- Worktrees must live outside the repo
- Never create sandboxes inside the repo

## High-Risk Changes

Mark proposal as high risk if it touches:
- auth
- policy
- permissions
- secrets
- sandbox manager
- deployer socket / API
- `docker-compose.prod.yml`
- migrations
- production deploy scripts

High-risk proposals:
- May generate diff and test deploy
- Should NOT auto-promote to production in MVP
- Require manual review

## Starting the System

```bash
./ops/scripts/start.sh --dev    # dev environment (hot reload)
./ops/scripts/start.sh --test   # test environment (isolated)
./ops/scripts/start.sh --prod   # prod environment
```

Or with Docker Compose directly:

```bash
docker compose -p agent-space-dev -f ops/compose/docker-compose.dev.yml --env-file ~/.aspace/dev/.env up
```
