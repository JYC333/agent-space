#!/usr/bin/env bash
# Start agent-space via Docker Compose (backend + frontend + deployer).
#
# Usage:
#   ./scripts/start.sh              — dev (default)
#   ./scripts/start.sh --dev        — dev environment (hot reload, port 3000/8000)
#   ./scripts/start.sh --test       — test environment (isolated, port 3100/8100)
#   ./scripts/start.sh --prod       — prod environment (port 80/8000)
#   ./scripts/start.sh --build      — same as above with image rebuild
#
# Data layout: $ASPACE_HOME/<mode>/ (e.g. ~/aspace/dev). Override the top-level
# parent directory with AGENT_SPACE_HOME when you need a non-default location.

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
    --build)  build_flag="--build" ;;
    *) echo "Unknown argument: $arg" && exit 1 ;;
  esac
done

# ── Path layout ────────────────────────────────────────────────────────────────
# ASPACE_HOME: top-level agent-space data root (holds dev/, test/, prod/).
# MODE_ROOT:    this environment's writable tree (mounted as /aspace in containers).
ASPACE_HOME="${AGENT_SPACE_HOME:-$HOME/aspace}"
ASPACE_HOME="${ASPACE_HOME/#\~/$HOME}"
export ASPACE_HOME

MODE_ROOT="$ASPACE_HOME/$mode"
export MODE_ROOT
# Compose volume host paths (defaults in yml match $HOME/aspace/<mode> if unset).
export AGENT_SPACE_MODE_ROOT="$MODE_ROOT"

ENV_FILE="$MODE_ROOT/.env"

# ── Initialize data root directories (idempotent) ──────────────────────────────
init_data_dirs() {
  echo "  → aspace home: $ASPACE_HOME"
  echo "  → mode root:   $MODE_ROOT"

  install -d -m 700 "$ASPACE_HOME"
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
echo "  project:      $COMPOSE_PROJECT"
echo "  mode root:    $MODE_ROOT"

docker compose \
  -p "$COMPOSE_PROJECT" \
  -f "$COMPOSE_FILE" \
  --env-file "$ENV_FILE" \
  up $build_flag
