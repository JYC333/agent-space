#!/usr/bin/env bash
# Rebuild and restart backend + frontend
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
COMPOSE_FILE="$REPO_ROOT/deployments/local/docker-compose.yml"

echo "[rebuild] repo=$REPO_ROOT"
echo "[rebuild] building backend and frontend images..."
docker compose -f "$COMPOSE_FILE" build backend frontend

echo "[rebuild] restarting backend and frontend..."
docker compose -f "$COMPOSE_FILE" up -d --no-deps backend frontend

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
