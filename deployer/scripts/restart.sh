#!/usr/bin/env bash
# Restart backend + frontend containers without rebuilding
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
COMPOSE_FILE="$REPO_ROOT/deployments/local/docker-compose.yml"

echo "[restart] restarting backend and frontend..."
docker compose -f "$COMPOSE_FILE" restart backend frontend

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
