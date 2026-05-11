#!/usr/bin/env bash
# Start agent-space locally — backend + frontend
#
# Usage:
#   ./scripts/start.sh              — Docker Compose dev (default)
#   ./scripts/start.sh --dev         — dev environment (hot reload, port 3000/8000)
#   ./scripts/start.sh --test        — test environment (isolated, port 3100/8100)
#   ./scripts/start.sh --prod        — prod environment (port 3000/8000)
#   ./scripts/start.sh --local       — bare processes, no Docker (dev mode)
#   ./scripts/start.sh --build       — Docker Compose with image rebuild

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_DIR="$REPO_ROOT/deployments/local"
SANDBOX_IMAGE="agent-space-sandbox"

mode="dev"
build_flag=""

for arg in "$@"; do
  case $arg in
    --dev)    mode="dev" ;;
    --test)   mode="test" ;;
    --prod)   mode="prod" ;;
    --local)  mode="local" ;;
    --build)  build_flag="--build" ;;
    *) echo "Unknown argument: $arg" && exit 1 ;;
  esac
done

# ── Resolve ASPACE_HOME ───────────────────────────────────────────────────────
ASPACE_HOME="${AGENT_SPACE_HOME:-$HOME/aspace}"
ASPACE_HOME="${ASPACE_HOME/#\~/$HOME}"
export ASPACE_HOME

# ── Per-mode root (no instance/ layer) ────────────────────────────────────────
MODE_ROOT="$ASPACE_HOME/$mode"
export MODE_ROOT

ENV_FILE="$MODE_ROOT/.env"

# ── Initialize data root directories (idempotent) ──────────────────────────────
init_data_dirs() {
  echo "  → aspace home: $ASPACE_HOME"
  echo "  → mode root: $MODE_ROOT"

  # Top-level aspace home (minimal — just holds per-mode dirs)
  install -d -m 700 "$ASPACE_HOME"

  # Per-mode directories — 700 for container user access
  install -d -m 700 "$MODE_ROOT"
  install -d -m 700 "$MODE_ROOT/storage"
  install -d -m 700 "$MODE_ROOT/logs"
  install -d -m 700 "$MODE_ROOT/db"
  install -d -m 700 "$MODE_ROOT/secrets"
  install -d -m 700 "$MODE_ROOT/artifacts"
  install -d -m 700 "$MODE_ROOT/cache"
  install -d -m 700 "$MODE_ROOT/run"
  install -d -m 700 "$MODE_ROOT/sandboxes"
}

# ── Ensure .env exists in mode root ───────────────────────────────────────────
ensure_env() {
  if [[ ! -f "$ENV_FILE" ]]; then
    echo "No .env found — copying template to $ENV_FILE"
    if [[ -f "$COMPOSE_DIR/instance/$mode/.env" ]]; then
      cp "$COMPOSE_DIR/instance/$mode/.env" "$ENV_FILE"
    else
      cp "$COMPOSE_DIR/.env.example" "$ENV_FILE"
    fi
    chmod 600 "$ENV_FILE"
  fi
}

# ── Docker mode ────────────────────────────────────────────────────────────────
if [[ "$mode" != "local" ]]; then
  export DOCKER_GID
  DOCKER_GID=$(stat -c '%g' /var/run/docker.sock 2>/dev/null || echo 989)

  if ! docker image inspect "$SANDBOX_IMAGE" &>/dev/null; then
    echo "Building sandbox image ($SANDBOX_IMAGE)..."
    docker build --network=host -t "$SANDBOX_IMAGE" "$REPO_ROOT/deployments/sandbox/"
  fi

  init_data_dirs
  ensure_env

  case "$mode" in
    dev)
      COMPOSE_FILE="$COMPOSE_DIR/docker-compose.dev.yml"
      COMPOSE_PROJECT="agent-space-dev"
      ;;
    test)
      COMPOSE_FILE="$COMPOSE_DIR/docker-compose.test.yml"
      COMPOSE_PROJECT="agent-space-test"
      ;;
    prod)
      COMPOSE_FILE="$COMPOSE_DIR/docker-compose.prod.yml"
      COMPOSE_PROJECT="agent-space-prod"
      ;;
  esac

  echo "Starting agent-space ($mode) with Docker Compose..."
  echo "  compose file: $COMPOSE_FILE"
  echo "  project: $COMPOSE_PROJECT"
  echo "  mode root: $MODE_ROOT"

  # Pass ASPACE_HOME to docker compose so volume paths can use it
  ASPACE_HOME="$ASPACE_HOME" docker compose \
    -p "$COMPOSE_PROJECT" \
    -f "$COMPOSE_FILE" \
    --env-file "$ENV_FILE" \
    up $build_flag
  exit 0
fi

# ── Local mode (no Docker) ───────────────────────────────────────────────────
echo "Starting agent-space (local processes)..."

init_data_dirs
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