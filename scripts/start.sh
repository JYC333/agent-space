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
# Data layout: $ASPACE_ROOT/<mode>/ (e.g. ~/.aspace/dev). Override the host-side
# parent directory with ASPACE_ROOT when you need a non-default location.
# AGENT_SPACE_HOME is NOT this parent: inside containers it is the mounted mode
# root (/aspace); for direct local backend runs it is a concrete mode root such
# as $HOME/.aspace/dev.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/local-compose.sh
source "$SCRIPT_DIR/lib/local-compose.sh"

SANDBOX_IMAGE="agent-space-sandbox"

MODE="${AGENT_SPACE_MODE:-dev}"
build_flag=""

for arg in "$@"; do
  case $arg in
    --dev)    MODE="dev" ;;
    --test)   MODE="test" ;;
    --prod)   MODE="prod" ;;
    --build)  build_flag="--build" ;;
    *) echo "Unknown argument: $arg" && exit 1 ;;
  esac
done

local_compose_init "$MODE"
ENV_TEMPLATE="$COMPOSE_DIR/.env.$MODE.example"

# ── Initialize data root directories (idempotent) ──────────────────────────────
init_data_dirs() {
  echo "  → aspace root: $ASPACE_ROOT"
  echo "  → mode root:   $MODE_ROOT"

  install -d -m 700 "$ASPACE_ROOT"
  install -d -m 700 "$MODE_ROOT"
  install -d -m 700 "$MODE_ROOT/storage"
  install -d -m 700 "$MODE_ROOT/logs"
  install -d -m 700 "$MODE_ROOT/db"
  install -d -m 700 "$MODE_ROOT/db/postgres"
  install -d -m 700 "$MODE_ROOT/db/dumps"
  install -d -m 700 "$MODE_ROOT/secrets"
  install -d -m 700 "$MODE_ROOT/artifacts"
  install -d -m 700 "$MODE_ROOT/cache"
  install -d -m 700 "$MODE_ROOT/run"
  install -d -m 700 "$MODE_ROOT/sandboxes"
}

# ── Ensure .env exists in mode root ───────────────────────────────────────────
ensure_env() {
  if [[ ! -f "$ENV_FILE" ]]; then
    if [[ ! -f "$ENV_TEMPLATE" ]]; then
      echo "Missing env template: $ENV_TEMPLATE" >&2
      exit 1
    fi
    echo "No .env found — copying $ENV_TEMPLATE to $ENV_FILE"
    cp "$ENV_TEMPLATE" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
  fi
}

validate_prod_env() {
  [[ "$MODE" == "prod" ]] || return 0

  local pw
  pw="$(local_compose_env_value POSTGRES_PASSWORD || true)"
  local lower="${pw,,}"

  if [[ -z "$pw" ]]; then
    echo "Refusing to start prod: POSTGRES_PASSWORD is empty in $ENV_FILE" >&2
    exit 1
  fi
  if [[ "$pw" == "agent_space_dev_password" ]]; then
    echo "Refusing to start prod: POSTGRES_PASSWORD uses the development password" >&2
    exit 1
  fi
  if [[ "$pw" == \<*\> || "$lower" == "change_me" || "$lower" == "changeme" || "$lower" == replace_me* || "$lower" == *replace*me* || "$lower" == "placeholder" ]]; then
    echo "Refusing to start prod: POSTGRES_PASSWORD is still a placeholder" >&2
    exit 1
  fi
}

init_data_dirs
ensure_env
validate_prod_env

export DOCKER_GID
DOCKER_GID=$(stat -c '%g' /var/run/docker.sock 2>/dev/null || echo 989)

if ! docker image inspect "$SANDBOX_IMAGE" &>/dev/null; then
  echo "Building sandbox image ($SANDBOX_IMAGE)..."
  docker build --network=host -t "$SANDBOX_IMAGE" "$REPO_ROOT/deployments/sandbox/"
fi

echo "Starting agent-space ($MODE) with Docker Compose..."
echo "  compose file: $COMPOSE_FILE"
echo "  project:      $COMPOSE_PROJECT"
echo "  mode root:    $MODE_ROOT"

up_args=(up)
if [[ -n "$build_flag" ]]; then
  up_args+=("$build_flag")
fi
"${COMPOSE[@]}" "${up_args[@]}"
