# agent-space Deployer

Host-level deployment supervisor. Runs **outside** the main app container and handles
rebuild/restart requests from the backend via a Unix domain socket.

## Why

The backend cannot restart itself from inside a Docker container. The deployer runs on the
host (or in a separate sidecar container with Docker access) and acts on approved deployment
jobs submitted by the backend.

## Start (as part of Docker Compose — recommended)

```bash
# First time: create the shared socket directory on the host
sudo mkdir -p /var/run/agent-space

# Then bring up the full stack (deployer starts automatically)
cd deployments/local
docker compose up -d
```

The deployer container has Docker socket access and shares `/var/run/agent-space` with the
backend container. The backend submits jobs to the socket; the deployer runs the scripts.

## Allowed Job Types

| Job Type              | Script                         | Effect                              |
|-----------------------|--------------------------------|-------------------------------------|
| `rebuild_agent_space` | `scripts/rebuild.sh`           | docker compose build + up -d        |
| `restart_agent_space` | `scripts/restart.sh`           | docker compose restart              |
| `health_check`        | `scripts/health_check.sh`      | curl /health                        |

## Wire Protocol

Newline-delimited JSON over Unix socket. One request → one response.

**Request:**
```json
{"job_id": "01J...", "proposal_id": "...", "space_id": "personal",
 "requested_by_user_id": "default_user", "job_type": "rebuild_agent_space", "target": "local"}
```

**Response:**
```json
{"job_id": "01J...", "status": "succeeded", "exit_code": 0,
 "stdout": "...", "stderr": "", "started_at": "...", "completed_at": "..."}
```

## Alternative: run directly on host (without Compose)

Useful for development or environments where Docker Compose is not running the deployer.

```bash
# Install Python deps (none beyond stdlib)
# Create socket directory
sudo mkdir -p /var/run/agent-space

# Run with defaults
REPO_ROOT=/path/to/agent-space python deployer/deployer.py

# Or with a custom socket path
DEPLOYER_SOCKET=/tmp/deployer.sock \
REPO_ROOT=/path/to/agent-space \
    python deployer/deployer.py
```

The process must have Docker CLI access (`docker` on PATH, user in `docker` group or root).

## Security

- Socket is owner read/write, group read/write (`0660`). Restrict the group.
- Only allowlisted job types are executed — no arbitrary shell commands.
- Every job must come from an approved proposal (enforced by the backend before calling).
- The deployer never reads or writes the database directly.
