#!/usr/bin/env bash
# run_test_deploy — deploy test compose from worktree
# Args: WORKSPACE_DIR=<path>
set -euo pipefail

WORKSPACE_DIR="${WORKSPACE_DIR:-}"
INSTANCE_ROOT="${INSTANCE_ROOT:-/aspace}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.test.yml}"
API_SERVICE="${API_SERVICE:-server}"

if [[ -z "$WORKSPACE_DIR" ]]; then
    echo "ERROR: WORKSPACE_DIR is required" >&2
    exit 1
fi

if [[ ! -d "$WORKSPACE_DIR" ]]; then
    echo "ERROR: worktree directory does not exist: $WORKSPACE_DIR" >&2
    exit 1
fi

COMPOSE_PATH="$WORKSPACE_DIR/ops/compose/$COMPOSE_FILE"

if [[ ! -f "$COMPOSE_PATH" ]]; then
    echo "ERROR: compose file not found: $COMPOSE_PATH" >&2
    exit 1
fi

cd "$WORKSPACE_DIR"

echo "[run_test_deploy] deploying from $COMPOSE_PATH"
echo "[run_test_deploy] project=agent-space-test"

AGENT_SPACE_MODE_ROOT="$INSTANCE_ROOT" docker compose \
    -p agent-space-test \
    -f "$COMPOSE_PATH" \
    --env-file "$INSTANCE_ROOT/.env" \
    up -d --build 2>&1

echo "[run_test_deploy] waiting for $API_SERVICE health..."
for i in $(seq 1 60); do
    if AGENT_SPACE_MODE_ROOT="$INSTANCE_ROOT" docker compose \
        -p agent-space-test \
        -f "$COMPOSE_PATH" \
        --env-file "$INSTANCE_ROOT/.env" \
        exec -T "$API_SERVICE" \
        node -e "fetch('http://localhost:8010/health').then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))" \
        > /dev/null 2>&1; then
        echo "[run_test_deploy] $API_SERVICE healthy after ${i}s"
        exit 0
    fi
    sleep 1
done
echo "[run_test_deploy] WARNING: $API_SERVICE did not become healthy within 60s" >&2
exit 1
