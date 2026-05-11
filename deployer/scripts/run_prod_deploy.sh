#!/usr/bin/env bash
# run_prod_deploy — deploy prod compose from canonical repo after merge
# Args: INSTANCE_ROOT=<path>
set -euo pipefail

REPO_PATH="${REPO_PATH:-/repo}"
INSTANCE_ROOT="${INSTANCE_ROOT:-/aspace}"

cd "$REPO_PATH"

echo "[run_prod_deploy] deploying from canonical repo"
echo "[run_prod_deploy] project=agent-space-prod"

COMPOSE_FILE="$REPO_PATH/deployments/local/docker-compose.prod.yml"

if [[ ! -f "$COMPOSE_FILE" ]]; then
    echo "ERROR: prod compose file not found: $COMPOSE_FILE" >&2
    exit 1
fi

ASPACE_HOME="$INSTANCE_ROOT" docker compose \
    -p agent-space-prod \
    -f "$COMPOSE_FILE" \
    --env-file "$INSTANCE_ROOT/.env" \
    up -d --build 2>&1

echo "[run_prod_deploy] waiting for backend health..."
for i in $(seq 1 60); do
    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        echo "[run_prod_deploy] backend healthy after ${i}s"
        exit 0
    fi
    sleep 1
done
echo "[run_prod_deploy] WARNING: backend did not become healthy within 60s" >&2
exit 1