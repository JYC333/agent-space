#!/usr/bin/env bash
# run_test_deploy — deploy test compose from worktree
# Args: WORKSPACE_DIR=<path>
set -euo pipefail

WORKSPACE_DIR="${WORKSPACE_DIR:-}"
INSTANCE_ROOT="${INSTANCE_ROOT:-/aspace}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.test.yml}"

if [[ -z "$WORKSPACE_DIR" ]]; then
    echo "ERROR: WORKSPACE_DIR is required" >&2
    exit 1
fi

if [[ ! -d "$WORKSPACE_DIR" ]]; then
    echo "ERROR: worktree directory does not exist: $WORKSPACE_DIR" >&2
    exit 1
fi

COMPOSE_PATH="$WORKSPACE_DIR/deployments/local/$COMPOSE_FILE"

if [[ ! -f "$COMPOSE_PATH" ]]; then
    echo "ERROR: compose file not found: $COMPOSE_PATH" >&2
    exit 1
fi

cd "$WORKSPACE_DIR"

echo "[run_test_deploy] deploying from $COMPOSE_PATH"
echo "[run_test_deploy] project=agent-space-test"

ASPACE_HOME="$INSTANCE_ROOT" docker compose \
    -p agent-space-test \
    -f "$COMPOSE_PATH" \
    --env-file "$INSTANCE_ROOT/.env" \
    up -d --build 2>&1

echo "[run_test_deploy] waiting for backend health..."
for i in $(seq 1 60); do
    if curl -sf http://localhost:8100/health > /dev/null 2>&1; then
        echo "[run_test_deploy] backend healthy after ${i}s"
        exit 0
    fi
    sleep 1
done
echo "[run_test_deploy] WARNING: backend did not become healthy within 60s" >&2
exit 1