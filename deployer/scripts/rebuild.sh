#!/usr/bin/env bash
# Rebuild and restart backend + frontend
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

echo "[rebuild] repo=$REPO_ROOT"
echo "[rebuild] building backend and frontend images..."
AGENT_SPACE_MODE_ROOT="$INSTANCE_ROOT" "${COMPOSE[@]}" build backend frontend

echo "[rebuild] restarting backend and frontend..."
AGENT_SPACE_MODE_ROOT="$INSTANCE_ROOT" "${COMPOSE[@]}" up -d --no-deps backend frontend

echo "[rebuild] waiting for backend health..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        echo "[rebuild] backend healthy after ${i}s"
        exit 0
    fi
    sleep 1
done
echo "[rebuild] WARNING: backend did not become healthy within 30s" >&2
exit 1
