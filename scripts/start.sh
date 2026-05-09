#!/usr/bin/env bash
# Start agent-space locally — backend + frontend
#
# Usage:
#   ./scripts/start.sh           — Docker Compose (default)
#   ./scripts/start.sh --local   — bare processes, no Docker (dev mode)
#   ./scripts/start.sh --build   — Docker Compose with image rebuild

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$REPO_ROOT/deployments/local/docker-compose.yml"
SANDBOX_IMAGE="agent-space-sandbox"

mode="docker"
build_flag=""

for arg in "$@"; do
  case $arg in
    --local) mode="local" ;;
    --build) build_flag="--build" ;;
    *) echo "Unknown argument: $arg" && exit 1 ;;
  esac
done

# ── Resolve ASPACE_HOME ───────────────────────────────────────────────────────
# Exported so docker-compose can use ${ASPACE_HOME} in env_file and volume paths.
ASPACE_HOME="${AGENT_SPACE_HOME:-$HOME/aspace}"
ASPACE_HOME="${ASPACE_HOME/#\~/$HOME}"   # expand leading ~
export ASPACE_HOME

ENV_FILE="$ASPACE_HOME/config/.env"

# ── Initialize ASPACE_HOME directories (idempotent) ──────────────────────────
init_aspace_dirs() {
  echo "  → data root: $ASPACE_HOME"
  install -d -m 700 "$ASPACE_HOME"
  install -d -m 700 "$ASPACE_HOME/config"
  install -d -m 700 "$ASPACE_HOME/secrets"
  install -d -m 700 "$ASPACE_HOME/db"
  install -d -m 700 "$ASPACE_HOME/runtime"
  install -d -m 750 "$ASPACE_HOME/storage"
  install -d -m 750 "$ASPACE_HOME/logs"
  install -d -m 750 "$ASPACE_HOME/cache"
  install -d -m 750 "$ASPACE_HOME/workspaces"
  install -d -m 750 "$ASPACE_HOME/sandboxes"
  install -d -m 750 "$ASPACE_HOME/artifacts"
}

# ── Ensure .env exists in ASPACE_HOME/config/ ────────────────────────────────
ensure_env() {
  if [[ ! -f "$ENV_FILE" ]]; then
    echo "No .env found — copying .env.example to $ENV_FILE"
    cp "$REPO_ROOT/deployments/local/.env.example" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
  fi
}

# ── Docker mode ───────────────────────────────────────────────────────────────
if [[ "$mode" == "docker" ]]; then
  export DOCKER_GID
  DOCKER_GID=$(stat -c '%g' /var/run/docker.sock 2>/dev/null || echo 989)

  if ! docker image inspect "$SANDBOX_IMAGE" &>/dev/null; then
    echo "Building sandbox image ($SANDBOX_IMAGE)..."
    docker build --network=host -t "$SANDBOX_IMAGE" "$REPO_ROOT/deployments/sandbox/"
  fi

  init_aspace_dirs
  ensure_env

  echo "Starting agent-space (Docker Compose)..."
  docker compose -f "$COMPOSE_FILE" up $build_flag
  exit 0
fi

# ── Local mode (no Docker) ────────────────────────────────────────────────────
echo "Starting agent-space (local processes)..."

init_aspace_dirs
ensure_env
set -a && source "$ENV_FILE" && set +a

# Backend
echo "  → backend on :8000"
cd "$REPO_ROOT/core/backend"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi
.venv/bin/uvicorn app.main:app --reload --port 8000 &
BACKEND_PID=$!

# Frontend
echo "  → frontend on :5173"
cd "$REPO_ROOT/frontend"
if [[ ! -d node_modules ]]; then
  npm ci --silent
fi
npm run dev &
FRONTEND_PID=$!

echo ""
echo "  Web UI:           http://localhost:5173"
echo "  API:              http://localhost:8000"
echo "  Interactive docs: http://localhost:8000/docs"
echo ""
echo "  Press Ctrl+C to stop both."

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0" INT TERM
wait
