#!/usr/bin/env bash
# Shared local Docker Compose/env resolution for host-side scripts.
#
# Source this file, parse script-specific arguments into MODE, then call:
#   local_compose_init "$MODE"

local_compose_trim() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

local_compose_validate_mode() {
  case "${1:-}" in
    dev|test|prod) ;;
    *) echo "ERROR: --mode must be dev, test, or prod (got '${1:-}')" >&2; exit 1 ;;
  esac
}

local_compose_init() {
  MODE="${1:-${AGENT_SPACE_MODE:-dev}}"
  local_compose_validate_mode "$MODE"

  REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
  COMPOSE_DIR="$REPO_ROOT/ops/compose"
  ENV_DIR="$REPO_ROOT/ops/env"

  # ASPACE_ROOT is the host-side parent of mode roots: dev/, test/, prod/.
  ASPACE_ROOT="${ASPACE_ROOT:-$HOME/.aspace}"
  ASPACE_ROOT="${ASPACE_ROOT/#\~/$HOME}"
  export ASPACE_ROOT

  MODE_ROOT="$ASPACE_ROOT/$MODE"
  ENV_FILE="$MODE_ROOT/.env"
  COMPOSE_PROJECT="agent-space-$MODE"
  COMPOSE_FILE="$COMPOSE_DIR/docker-compose.$MODE.yml"

  export REPO_ROOT
  export COMPOSE_DIR
  export ENV_DIR
  export MODE_ROOT
  export AGENT_SPACE_MODE_ROOT="$MODE_ROOT"

  COMPOSE=(docker compose --env-file "$ENV_FILE" -p "$COMPOSE_PROJECT" -f "$COMPOSE_FILE")
  COMPOSE_HINT="docker compose --env-file $ENV_FILE -p $COMPOSE_PROJECT -f $COMPOSE_FILE"
  LOCAL_COMPOSE_POSTGRES_STARTED=false
}

local_compose_service_running() {
  local service="$1"
  local running=""
  running="$("${COMPOSE[@]}" ps --services --filter status=running 2>/dev/null || true)"
  [[ $'\n'"$running"$'\n' == *$'\n'"$service"$'\n'* ]]
}

local_compose_ensure_postgres() {
  local purpose="${1:-operation}"

  if local_compose_service_running postgres; then
    return 0
  fi

  echo "Starting postgres service for $purpose (mode: $MODE)..."
  if ! "${COMPOSE[@]}" up -d postgres >/dev/null; then
    echo "ERROR: failed to start postgres service for mode '$MODE'." >&2
    return 1
  fi
  LOCAL_COMPOSE_POSTGRES_STARTED=true
}

local_compose_wait_postgres_ready() {
  local pguser="$1"
  local db="${2:-postgres}"
  local timeout_seconds="${3:-30}"
  local attempt

  for ((attempt = 1; attempt <= timeout_seconds; attempt++)); do
    if "${COMPOSE[@]}" exec -T postgres pg_isready -U "$pguser" -d "$db" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done

  echo "ERROR: postgres service is not ready for mode '$MODE' after waiting." >&2
  return 1
}

local_compose_ensure_postgres_ready() {
  local purpose="$1"
  local pguser="$2"
  local db="${3:-postgres}"
  local timeout_seconds="${4:-30}"

  if ! local_compose_ensure_postgres "$purpose"; then
    return 1
  fi
  local_compose_wait_postgres_ready "$pguser" "$db" "$timeout_seconds"
}

local_compose_stop_postgres_if_started() {
  local purpose="${1:-operation}"

  if [[ "${LOCAL_COMPOSE_POSTGRES_STARTED:-false}" == "true" ]]; then
    echo "[$purpose] stopping postgres service started for $purpose..."
    "${COMPOSE[@]}" stop postgres >/dev/null || true
    LOCAL_COMPOSE_POSTGRES_STARTED=false
  fi
  return 0
}

local_compose_env_value() {
  local key="$1"
  local file="${2:-$ENV_FILE}"
  local line parsed_key value

  [[ -f "$file" ]] || return 1

  while IFS= read -r line || [[ -n "$line" ]]; do
    line="$(local_compose_trim "$line")"
    [[ -z "$line" || "$line" == \#* ]] && continue

    if [[ "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*)[[:space:]]*=(.*)$ ]]; then
      parsed_key="${BASH_REMATCH[1]}"
      [[ "$parsed_key" == "$key" ]] || continue

      value="$(local_compose_trim "${BASH_REMATCH[2]}")"
      if [[ "$value" == \"* ]]; then
        value="${value#\"}"
        value="${value%%\"*}"
      elif [[ "$value" == \'* ]]; then
        value="${value#\'}"
        value="${value%%\'*}"
      else
        value="${value%%#*}"
        value="$(local_compose_trim "$value")"
      fi

      printf '%s\n' "$value"
      return 0
    fi
  done < "$file"

  return 1
}

local_compose_setting() {
  local key="$1"
  local value="${!key-}"
  if [[ -n "$value" ]]; then
    printf '%s\n' "$value"
    return 0
  fi
  local_compose_env_value "$key"
}

local_compose_setting_or_default() {
  local key="$1"
  local default="$2"
  local value

  if value="$(local_compose_setting "$key")" && [[ -n "$value" ]]; then
    printf '%s\n' "$value"
  else
    printf '%s\n' "$default"
  fi
}

local_compose_validate_pg_identifier() {
  local label="$1"
  local value="$2"
  if [[ ! "$value" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
    echo "ERROR: $label contains unsafe characters" >&2
    exit 1
  fi
}
