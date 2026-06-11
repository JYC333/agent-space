#!/usr/bin/env bash
# Restart backend + frontend containers without rebuilding
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
MODE="${AGENT_SPACE_ENV:-dev}"
INSTANCE_ROOT="${AGENT_SPACE_HOME:-/aspace}"
COMPOSE_FILE="$REPO_ROOT/ops/compose/docker-compose.$MODE.yml"
COMPOSE_PROJECT="agent-space-$MODE"

case "$MODE" in
    dev|test|prod) ;;
    *) echo "ERROR: AGENT_SPACE_ENV must be dev, test, or prod (got '$MODE')" >&2; exit 1 ;;
esac

if [[ ! -f "$COMPOSE_FILE" ]]; then
    echo "ERROR: compose file not found: $COMPOSE_FILE" >&2
    exit 1
fi

COMPOSE=(docker compose --env-file "$INSTANCE_ROOT/.env" -p "$COMPOSE_PROJECT" -f "$COMPOSE_FILE")

echo "[restart] restarting backend and frontend..."
AGENT_SPACE_MODE_ROOT="$INSTANCE_ROOT" "${COMPOSE[@]}" restart backend frontend

echo "[restart] waiting for backend health..."
for i in $(seq 1 20); do
    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        echo "[restart] backend healthy after ${i}s"
        exit 0
    fi
    sleep 1
done
echo "[restart] WARNING: backend did not become healthy within 20s" >&2
exit 1
