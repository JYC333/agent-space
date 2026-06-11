# Module: Deployment

## Purpose
Allow the web UI to trigger approved deployment actions (rebuild/restart) without giving
the main app container direct control over the host Docker daemon.

## Architecture

```
Browser UI
  → backend API  POST /api/v1/deployments/jobs
  → DeployerClient  (Unix socket client)
  → /var/run/agent-space/deployer.sock
  → host deployer process  (deployer/deployer.py)
  → whitelisted deploy script  (deployer/scripts/)
  → docker compose build/restart backend frontend
  → health check
  → result written back to DeploymentJob record
  → frontend displays status
```

The backend cannot restart itself from inside a Docker container.
The deployer runs **on the host** and is the only process that can trigger compose operations.

## Allowed Job Types

| Job Type              | Script                    | Effect                              |
|-----------------------|---------------------------|-------------------------------------|
| `rebuild_agent_space` | `deployer/scripts/rebuild.sh`      | docker compose build + up -d        |
| `restart_agent_space` | `deployer/scripts/restart.sh`      | docker compose restart              |
| `health_check`        | `deployer/scripts/health_check.sh` | curl /health                        |

No other commands are accepted. The deployer never executes arbitrary shell input.

## MVP Status

Current state:
- `DeploymentJob` model exists in the database ✓
- `DeployerClient` implemented ✓
- API routes: `POST/GET /api/v1/deployments/jobs` ✓
- Deployer process: `deployer/deployer.py` ✓
- Deploy scripts: `deployer/scripts/` ✓
- Socket path config: `config.deployer_socket_path` ✓

Deployment flow is **manual-start**: the user must start `deployer/deployer.py` on the
host before deployment jobs will succeed. If the socket is absent, the API returns a
clear error with instructions.

## Deployment Flow (Full)

1. Agent proposes code changes → code proposal created
2. User reviews diff and approves proposal
3. Backend applies patch to real repo
4. User triggers deployment via frontend → `POST /api/v1/deployments/jobs`
5. Backend creates `DeploymentJob` record (status=queued)
6. `DeployerClient` sends job to Unix socket
7. Deployer validates job_type, runs script
8. Script runs `docker compose build + up -d backend frontend`
9. Script polls `/health` until backend is up
10. Deployer returns result to backend
11. Backend updates `DeploymentJob` (status=succeeded/failed)
12. Frontend displays result

## What Is Still Manual

- Starting the deployer: `python deployer/deployer.py` (or systemd unit)
- Creating `/var/run/agent-space/` with correct permissions on the host

## Security

- Deployer socket is not exposed on any TCP port
- Only allowlisted job types are accepted
- Deployer never reads/writes the database or user memory
- Docker socket access lives in the deployer, not the main app (for deployment purposes)
- Agent-generated code cannot trigger deployment without a human-approved proposal

## Related Files
- `deployer/deployer.py` — host deployer process
- `deployer/protocol.py` — wire protocol constants
- `deployer/scripts/` — whitelisted deploy scripts
- `backend/app/deployment/client.py` — DeployerClient
- `backend/app/deployment/api.py` — HTTP routes
- `backend/app/models.py` — DeploymentJob model
- `backend/app/config.py` — `deployer_socket_path`
- `ops/compose/docker-compose.<mode>.yml` — mounts /var/run/agent-space into backend

## Related Boundaries
- B41, B42, B43 in BOUNDARIES.md
