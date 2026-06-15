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

local_compose_ensure_mode_env_file() {
  if [[ -f "$ENV_FILE" ]]; then
    return 0
  fi

  local template="$ENV_DIR/.env.$MODE.example"
  if [[ ! -f "$template" ]]; then
    echo "ERROR: missing env template: $template" >&2
    exit 1
  fi

  install -d -m 700 "$MODE_ROOT"
  echo "No .env found — copying $template to $ENV_FILE"
  cp "$template" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
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

local_compose_wait_service_healthy() {
  local service="$1"
  local purpose="${2:-service readiness}"
  local timeout_seconds="${3:-120}"
  local attempt container_id status

  for ((attempt = 1; attempt <= timeout_seconds; attempt++)); do
    container_id="$("${COMPOSE[@]}" ps -q "$service" 2>/dev/null || true)"
    if [[ -n "$container_id" ]]; then
      status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id" 2>/dev/null || true)"
      case "$status" in
        healthy)
          return 0
          ;;
        exited|dead)
          echo "ERROR: service '$service' exited while waiting for $purpose." >&2
          return 1
          ;;
      esac
    fi
    sleep 1
  done

  echo "ERROR: service '$service' was not healthy for $purpose after waiting." >&2
  return 1
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

local_compose_is_placeholder_value() {
  local value="${1:-}"
  local lower="${value,,}"

  [[ -z "$value" ]] && return 0
  [[ "$value" == \<*\> ]] && return 0
  case "$lower" in
    change_me|changeme|replace_me*|replace-with-*|*replace*me*|placeholder)
      return 0
      ;;
  esac
  return 1
}

local_compose_random_hex() {
  local bytes="${1:-24}"
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex "$bytes"
    return 0
  fi
  python3 -c "import secrets; print(secrets.token_hex($bytes))"
}

local_compose_set_env_value() {
  local key="$1"
  local value="$2"
  local file="${3:-$ENV_FILE}"
  local tmp

  install -d -m 700 "$(dirname "$file")"
  [[ -f "$file" ]] || : > "$file"
  tmp="$(mktemp "${file}.tmp.XXXXXX")"

  awk -v key="$key" -v value="$value" '
    BEGIN { done = 0 }
    $0 ~ "^[[:space:]]*#?[[:space:]]*" key "[[:space:]]*=" {
      print key "=" value
      done = 1
      next
    }
    { print }
    END {
      if (!done) {
        if (NR > 0) print ""
        print key "=" value
      }
    }
  ' "$file" > "$tmp"
  mv "$tmp" "$file"
  chmod 600 "$file"
}

local_compose_ensure_env_secret() {
  local key="$1"
  local bytes="${2:-24}"
  local current=""

  current="$(local_compose_setting "$key" || true)"
  if local_compose_is_placeholder_value "$current"; then
    local_compose_set_env_value "$key" "$(local_compose_random_hex "$bytes")"
  fi
}

local_compose_control_plane_ts_authority_enabled() {
  local credentials_authority runs_authority policy_authority proposals_authority sessions_authority chat_turn_authority context_authority memory_authority memory_apply_authority
  credentials_authority="$(local_compose_setting_or_default CONTROL_PLANE_PROVIDERS_CREDENTIALS_AUTHORITY python)"
  runs_authority="$(local_compose_setting_or_default CONTROL_PLANE_RUNS_AUTHORITY python)"
  policy_authority="$(local_compose_setting_or_default CONTROL_PLANE_POLICY_AUTHORITY python)"
  proposals_authority="$(local_compose_setting_or_default CONTROL_PLANE_PROPOSALS_AUTHORITY python)"
  sessions_authority="$(local_compose_setting_or_default CONTROL_PLANE_SESSIONS_AUTHORITY python)"
  chat_turn_authority="$(local_compose_setting_or_default CONTROL_PLANE_CHAT_TURN_AUTHORITY python)"
  context_authority="$(local_compose_setting_or_default CONTROL_PLANE_CONTEXT_AUTHORITY python)"
  memory_authority="$(local_compose_setting_or_default CONTROL_PLANE_MEMORY_AUTHORITY python)"
  memory_apply_authority="$(local_compose_setting_or_default CONTROL_PLANE_MEMORY_APPLY_AUTHORITY python)"
  [[ "${credentials_authority,,}" == "ts" || "${runs_authority,,}" == "ts" || "${policy_authority,,}" == "ts" || "${proposals_authority,,}" == "ts" || "${sessions_authority,,}" == "ts" || "${chat_turn_authority,,}" == "ts" || "${context_authority,,}" == "ts" || "${memory_authority,,}" == "ts" || "${memory_apply_authority,,}" == "ts" ]]
}

local_compose_ensure_control_plane_ts_authority_env() {
  [[ -f "$ENV_FILE" ]] || return 0

  local providers_authority
  local credentials_authority
  local runs_authority
  local policy_authority
  local proposals_authority
  local sessions_authority
  local chat_turn_authority
  local context_authority
  local memory_authority
  local memory_apply_authority
  providers_authority="$(local_compose_setting CONTROL_PLANE_PROVIDERS_AUTHORITY || true)"
  credentials_authority="$(local_compose_setting CONTROL_PLANE_PROVIDERS_CREDENTIALS_AUTHORITY || true)"
  runs_authority="$(local_compose_setting CONTROL_PLANE_RUNS_AUTHORITY || true)"
  policy_authority="$(local_compose_setting CONTROL_PLANE_POLICY_AUTHORITY || true)"
  proposals_authority="$(local_compose_setting CONTROL_PLANE_PROPOSALS_AUTHORITY || true)"
  sessions_authority="$(local_compose_setting CONTROL_PLANE_SESSIONS_AUTHORITY || true)"
  chat_turn_authority="$(local_compose_setting CONTROL_PLANE_CHAT_TURN_AUTHORITY || true)"
  context_authority="$(local_compose_setting CONTROL_PLANE_CONTEXT_AUTHORITY || true)"
  memory_authority="$(local_compose_setting CONTROL_PLANE_MEMORY_AUTHORITY || true)"
  memory_apply_authority="$(local_compose_setting CONTROL_PLANE_MEMORY_APPLY_AUTHORITY || true)"

  # New dev/test environments start directly on the TypeScript authority.
  # Existing explicit python settings are respected.
  if [[ "$MODE" != "prod" && -z "$providers_authority" && -z "$credentials_authority" && -z "$runs_authority" && -z "$policy_authority" && -z "$proposals_authority" && -z "$sessions_authority" && -z "$chat_turn_authority" && -z "$context_authority" && -z "$memory_authority" && -z "$memory_apply_authority" ]]; then
    local_compose_set_env_value CONTROL_PLANE_PROVIDERS_AUTHORITY ts
    local_compose_set_env_value CONTROL_PLANE_PROVIDERS_CREDENTIALS_AUTHORITY ts
    local_compose_set_env_value CONTROL_PLANE_RUNS_AUTHORITY ts
    local_compose_set_env_value CONTROL_PLANE_POLICY_AUTHORITY ts
    local_compose_set_env_value CONTROL_PLANE_PROPOSALS_AUTHORITY ts
    local_compose_set_env_value CONTROL_PLANE_SESSIONS_AUTHORITY ts
    local_compose_set_env_value CONTROL_PLANE_CHAT_TURN_AUTHORITY ts
    local_compose_set_env_value CONTROL_PLANE_CONTEXT_AUTHORITY ts
    local_compose_set_env_value CONTROL_PLANE_MEMORY_AUTHORITY ts
    local_compose_set_env_value CONTROL_PLANE_MEMORY_APPLY_AUTHORITY ts
    providers_authority="ts"
    credentials_authority="ts"
    runs_authority="ts"
    policy_authority="ts"
    proposals_authority="ts"
    sessions_authority="ts"
    chat_turn_authority="ts"
    context_authority="ts"
    memory_authority="ts"
    memory_apply_authority="ts"
  fi

  # Existing dev/test env files from earlier TS migrations may already have
  # TS providers/credentials authority but lack later authority switches.
  if [[ "$MODE" != "prod" && -z "$runs_authority" && "${credentials_authority,,}" == "ts" ]]; then
    local_compose_set_env_value CONTROL_PLANE_RUNS_AUTHORITY ts
    runs_authority="ts"
  fi
  if [[ "$MODE" != "prod" && -z "$policy_authority" && "${credentials_authority,,}" == "ts" ]]; then
    local_compose_set_env_value CONTROL_PLANE_POLICY_AUTHORITY ts
    policy_authority="ts"
  fi
  if [[ "$MODE" != "prod" && -z "$proposals_authority" && "${credentials_authority,,}" == "ts" ]]; then
    local_compose_set_env_value CONTROL_PLANE_PROPOSALS_AUTHORITY ts
    proposals_authority="ts"
  fi
  # Stage 6 sessions slice: backfill for existing dev/test envs created before
  # this switch existed. The public sessions read/write surface is TS-owned when
  # flipped; session reflect stays Python-owned.
  if [[ "$MODE" != "prod" && -z "$sessions_authority" && "${credentials_authority,,}" == "ts" ]]; then
    local_compose_set_env_value CONTROL_PLANE_SESSIONS_AUTHORITY ts
    sessions_authority="ts"
  fi
  # Stage 6 chat-turn slice: backfill for existing dev/test envs after
  # sessions/runs have moved. Python remains the context/run-preparation port.
  if [[ "$MODE" != "prod" && -z "$chat_turn_authority" && "${credentials_authority,,}" == "ts" ]]; then
    local_compose_set_env_value CONTROL_PLANE_CHAT_TURN_AUTHORITY ts
    chat_turn_authority="ts"
  fi
  # Stage 6 context-assembly slice (slice 4): backfill for existing dev/test envs
  # after the chat-turn slice moved. TS owns chat context build + snapshot
  # persistence; Python keeps the candidate-read and run-create ports.
  if [[ "$MODE" != "prod" && -z "$context_authority" && "${chat_turn_authority,,}" == "ts" ]]; then
    local_compose_set_env_value CONTROL_PLANE_CONTEXT_AUTHORITY ts
    context_authority="ts"
  fi
  # Stage 6 memory-read slice (slice 5): backfill for existing dev/test envs. The
  # TS memory read model is independent of the other switches; gate the backfill
  # on credentials=ts (the common "already on TS" marker).
  if [[ "$MODE" != "prod" && -z "$memory_authority" && "${credentials_authority,,}" == "ts" ]]; then
    local_compose_set_env_value CONTROL_PLANE_MEMORY_AUTHORITY ts
    memory_authority="ts"
  fi
  # Stage 6 memory-apply slice (7b): backfill for existing dev/test envs after
  # the memory read/proposal-create slice moved.
  if [[ "$MODE" != "prod" && -z "$memory_apply_authority" && "${memory_authority,,}" == "ts" ]]; then
    local_compose_set_env_value CONTROL_PLANE_MEMORY_APPLY_AUTHORITY ts
    memory_apply_authority="ts"
  fi

  if ! local_compose_control_plane_ts_authority_enabled; then
    return 0
  fi

  providers_authority="$(local_compose_setting_or_default CONTROL_PLANE_PROVIDERS_AUTHORITY python)"
  credentials_authority="$(local_compose_setting_or_default CONTROL_PLANE_PROVIDERS_CREDENTIALS_AUTHORITY python)"
  runs_authority="$(local_compose_setting_or_default CONTROL_PLANE_RUNS_AUTHORITY python)"
  policy_authority="$(local_compose_setting_or_default CONTROL_PLANE_POLICY_AUTHORITY python)"
  proposals_authority="$(local_compose_setting_or_default CONTROL_PLANE_PROPOSALS_AUTHORITY python)"
  sessions_authority="$(local_compose_setting_or_default CONTROL_PLANE_SESSIONS_AUTHORITY python)"
  chat_turn_authority="$(local_compose_setting_or_default CONTROL_PLANE_CHAT_TURN_AUTHORITY python)"
  context_authority="$(local_compose_setting_or_default CONTROL_PLANE_CONTEXT_AUTHORITY python)"
  memory_authority="$(local_compose_setting_or_default CONTROL_PLANE_MEMORY_AUTHORITY python)"
  memory_apply_authority="$(local_compose_setting_or_default CONTROL_PLANE_MEMORY_APPLY_AUTHORITY python)"
  # Context assembly depends on the chat-turn slice (which itself cascades to
  # sessions/runs/credentials below).
  if [[ "${context_authority,,}" == "ts" && "${chat_turn_authority,,}" != "ts" ]]; then
    local_compose_set_env_value CONTROL_PLANE_CHAT_TURN_AUTHORITY ts
    chat_turn_authority="ts"
  fi
  if [[ "${memory_apply_authority,,}" == "ts" && "${memory_authority,,}" != "ts" ]]; then
    local_compose_set_env_value CONTROL_PLANE_MEMORY_AUTHORITY ts
    memory_authority="ts"
  fi
  if [[ "${memory_authority,,}" == "ts" && "${policy_authority,,}" != "ts" ]]; then
    local_compose_set_env_value CONTROL_PLANE_POLICY_AUTHORITY ts
    policy_authority="ts"
  fi
  if [[ "${memory_authority,,}" == "ts" && "${proposals_authority,,}" != "ts" ]]; then
    local_compose_set_env_value CONTROL_PLANE_PROPOSALS_AUTHORITY ts
    proposals_authority="ts"
  fi
  if [[ "${runs_authority,,}" == "ts" && "${credentials_authority,,}" != "ts" ]]; then
    local_compose_set_env_value CONTROL_PLANE_PROVIDERS_CREDENTIALS_AUTHORITY ts
    credentials_authority="ts"
  fi
  if [[ "${policy_authority,,}" == "ts" && "${credentials_authority,,}" != "ts" ]]; then
    local_compose_set_env_value CONTROL_PLANE_PROVIDERS_CREDENTIALS_AUTHORITY ts
    credentials_authority="ts"
  fi
  if [[ "${proposals_authority,,}" == "ts" && "${credentials_authority,,}" != "ts" ]]; then
    local_compose_set_env_value CONTROL_PLANE_PROVIDERS_CREDENTIALS_AUTHORITY ts
    credentials_authority="ts"
  fi
  if [[ "${chat_turn_authority,,}" == "ts" && "${credentials_authority,,}" != "ts" ]]; then
    local_compose_set_env_value CONTROL_PLANE_PROVIDERS_CREDENTIALS_AUTHORITY ts
    credentials_authority="ts"
  fi
  if [[ "${chat_turn_authority,,}" == "ts" && "${sessions_authority,,}" != "ts" ]]; then
    local_compose_set_env_value CONTROL_PLANE_SESSIONS_AUTHORITY ts
    sessions_authority="ts"
  fi
  if [[ "${chat_turn_authority,,}" == "ts" && "${runs_authority,,}" != "ts" ]]; then
    local_compose_set_env_value CONTROL_PLANE_RUNS_AUTHORITY ts
    runs_authority="ts"
  fi
  if [[ "${providers_authority,,}" != "ts" ]]; then
    local_compose_set_env_value CONTROL_PLANE_PROVIDERS_AUTHORITY ts
  fi

  local role
  role="$(local_compose_setting_or_default CONTROL_PLANE_DB_RW_USER agent_space_cp)"
  local_compose_validate_pg_identifier "CONTROL_PLANE_DB_RW_USER" "$role"
  if ! local_compose_setting CONTROL_PLANE_DB_RW_USER >/dev/null 2>&1; then
    local_compose_set_env_value CONTROL_PLANE_DB_RW_USER "$role"
  fi

  local_compose_ensure_env_secret CONTROL_PLANE_DB_RW_PASSWORD 24
  local_compose_ensure_env_secret CONTROL_PLANE_INTERNAL_TOKEN 32

  local pgdb password current_url desired_url
  pgdb="$(local_compose_setting_or_default POSTGRES_DB agent_space)"
  local_compose_validate_pg_identifier "POSTGRES_DB" "$pgdb"
  password="$(local_compose_setting CONTROL_PLANE_DB_RW_PASSWORD)"
  desired_url="postgresql://${role}:${password}@postgres:5432/${pgdb}"
  current_url="$(local_compose_setting CONTROL_PLANE_DATABASE_URL || true)"
  if local_compose_is_placeholder_value "$current_url"; then
    local_compose_set_env_value CONTROL_PLANE_DATABASE_URL "$desired_url"
  fi
}

local_compose_provision_control_plane_db_role() {
  local purpose="${1:-control-plane role provisioning}"

  if ! local_compose_control_plane_ts_authority_enabled; then
    return 0
  fi

  local role password pgdb pguser
  role="$(local_compose_setting_or_default CONTROL_PLANE_DB_RW_USER agent_space_cp)"
  password="$(local_compose_setting CONTROL_PLANE_DB_RW_PASSWORD || true)"
  pgdb="$(local_compose_setting_or_default POSTGRES_DB agent_space)"
  pguser="$(local_compose_setting_or_default POSTGRES_USER agent_space)"

  local_compose_validate_pg_identifier "CONTROL_PLANE_DB_RW_USER" "$role"
  local_compose_validate_pg_identifier "POSTGRES_DB" "$pgdb"
  local_compose_validate_pg_identifier "POSTGRES_USER" "$pguser"

  if local_compose_is_placeholder_value "$password"; then
    echo "ERROR: CONTROL_PLANE_DB_RW_PASSWORD is required for control-plane TS authority." >&2
    echo "       Run ops/scripts/start.sh or ops/scripts/db/migrate.sh so it can be generated." >&2
    exit 1
  fi

  local role_sql password_sql
  role_sql="${role//\'/\'\'}"
  password_sql="${password//\'/\'\'}"

  # Stage 6 sessions slice: grants are per-slice and dormant until the
  # CONTROL_PLANE_SESSIONS_AUTHORITY switch is flipped to `ts`. While `python`
  # (the preparation default) the cp role gets no session/message/summary access
  # at all, which the smoke test below asserts. When `ts`, the role gains the
  # session read model plus session create + message append:
  # SELECT/INSERT/UPDATE on sessions (UPDATE touches updated_at),
  # SELECT/INSERT on messages, and SELECT on session_summaries for the
  # context-safe latest-summary read. Sessions are never DELETEd (no archive
  # semantics yet), messages are append-only, and summary condense writes are
  # not TS-owned yet, so those privileges stay denied in both modes.
  local sessions_authority sessions_grant_sql sessions_required_rows sessions_denied_rows
  sessions_authority="$(local_compose_setting_or_default CONTROL_PLANE_SESSIONS_AUTHORITY python)"
  if [[ "${sessions_authority,,}" == "ts" ]]; then
    sessions_grant_sql="-- Stage 6 sessions slice (CONTROL_PLANE_SESSIONS_AUTHORITY=ts): read + create/append + summary read.
GRANT SELECT, INSERT, UPDATE ON TABLE public.sessions TO \"$role\";
GRANT SELECT, INSERT ON TABLE public.messages TO \"$role\";
GRANT SELECT ON TABLE public.session_summaries TO \"$role\";"
    sessions_required_rows="('sessions', 'SELECT'),
      ('sessions', 'INSERT'),
      ('sessions', 'UPDATE'),
      ('messages', 'SELECT'),
      ('messages', 'INSERT'),
      ('session_summaries', 'SELECT'),"
    sessions_denied_rows=""
  else
    sessions_grant_sql="-- Stage 6 sessions slice not flipped; cp role has no session access."
    sessions_required_rows=""
    sessions_denied_rows="('sessions', 'SELECT'),
      ('sessions', 'INSERT'),
      ('sessions', 'UPDATE'),
      ('messages', 'SELECT'),
      ('messages', 'INSERT'),
      ('session_summaries', 'SELECT'),"
  fi

  # Stage 6 context-assembly slice (slice 4): grants are per-slice and dormant
  # until CONTROL_PLANE_CONTEXT_AUTHORITY=ts. When flipped, the TS chat turn owns
  # the ChatContextBuilder selection loop and persists the audit snapshot, so it
  # gains SELECT/INSERT/UPDATE on context_snapshots (UPDATE the run's existing
  # row) and context_snapshot_items (append selected items; UPDATE kept for
  # idempotent re-persist). memory_access_logs is NOT granted — the chat path
  # does not write access logs (that stays with the runs path / memory slice).
  local context_authority context_grant_sql context_required_rows context_denied_rows
  context_authority="$(local_compose_setting_or_default CONTROL_PLANE_CONTEXT_AUTHORITY python)"
  if [[ "${context_authority,,}" == "ts" ]]; then
    context_grant_sql="-- Stage 6 context-assembly slice (CONTROL_PLANE_CONTEXT_AUTHORITY=ts): snapshot read/write + items read/write.
GRANT SELECT, INSERT, UPDATE ON TABLE public.context_snapshots TO \"$role\";
GRANT SELECT, INSERT, UPDATE ON TABLE public.context_snapshot_items TO \"$role\";"
    context_required_rows="('context_snapshots', 'SELECT'),
      ('context_snapshots', 'INSERT'),
      ('context_snapshots', 'UPDATE'),
      ('context_snapshot_items', 'SELECT'),
      ('context_snapshot_items', 'INSERT'),
      ('context_snapshot_items', 'UPDATE'),"
    context_denied_rows=""
  else
    context_grant_sql="-- Stage 6 context-assembly slice not flipped; cp role has no context-snapshot access."
    context_required_rows=""
    context_denied_rows="('context_snapshots', 'SELECT'),
      ('context_snapshots', 'INSERT'),
      ('context_snapshots', 'UPDATE'),
      ('context_snapshot_items', 'SELECT'),
      ('context_snapshot_items', 'INSERT'),
      ('context_snapshot_items', 'UPDATE'),"
  fi

  # Stage 6 memory slices (5-6 + 7a): grants are per-slice and dormant until
  # CONTROL_PLANE_MEMORY_AUTHORITY=ts. When flipped, TS owns /memory
  # list/get/search plus public memory proposal creation. It gets SELECT on
  # memory_entries/projects for read/target authorization and INSERT on
  # proposals for pending proposal rows only. Slice 7a additionally restores
  # read-access logging: INSERT on memory_access_logs and a COLUMN-SCOPED UPDATE
  # on memory_entries(access_count, last_accessed_at) so get/search can bump read
  # counters. Without the apply switch, the role does not get table-wide
  # memory_entries write and content/visibility columns remain unwritable.
  # Slice 7b (CONTROL_PLANE_MEMORY_APPLY_AUTHORITY=ts) additionally grants
  # table-wide memory_entries INSERT/UPDATE + provenance_links/memory_relations
  # INSERT so the TS accept path can apply accepted proposals. It also grants
  # column-scoped spaces(id, type) SELECT for the private-placement hard
  # invariant. DELETE on memory_entries is never granted (memory is soft-deleted
  # via status).
  local memory_authority memory_apply_authority memory_grant_sql memory_required_rows memory_denied_rows
  local memory_column_checks
  memory_authority="$(local_compose_setting_or_default CONTROL_PLANE_MEMORY_AUTHORITY python)"
  memory_apply_authority="$(local_compose_setting_or_default CONTROL_PLANE_MEMORY_APPLY_AUTHORITY python)"
  if [[ "${memory_authority,,}" == "ts" && "${memory_apply_authority,,}" == "ts" ]]; then
    memory_grant_sql="-- Stage 6 memory (CONTROL_PLANE_MEMORY_APPLY_AUTHORITY=ts): read + proposal-create + read-logging + active-memory apply.
GRANT SELECT, INSERT, UPDATE ON TABLE public.memory_entries TO \"$role\";
GRANT SELECT ON TABLE public.projects TO \"$role\";
GRANT INSERT ON TABLE public.proposals TO \"$role\";
GRANT INSERT ON TABLE public.memory_access_logs TO \"$role\";
GRANT INSERT ON TABLE public.provenance_links TO \"$role\";
GRANT INSERT ON TABLE public.memory_relations TO \"$role\";
GRANT SELECT (id, type) ON TABLE public.spaces TO \"$role\";"
    memory_required_rows="('memory_entries', 'SELECT'),
      ('memory_entries', 'INSERT'),
      ('memory_entries', 'UPDATE'),
      ('projects', 'SELECT'),
      ('proposals', 'INSERT'),
      ('memory_access_logs', 'INSERT'),
      ('provenance_links', 'INSERT'),
      ('memory_relations', 'INSERT'),"
    # Active-memory writes flow through the applier; hard DELETE never granted.
    memory_denied_rows="('memory_entries', 'DELETE'),
      ('spaces', 'SELECT'),"
    memory_column_checks="  IF NOT has_column_privilege(role_name, 'public.spaces', 'id', 'SELECT') THEN
    RAISE EXCEPTION 'control-plane role % lacks spaces.id SELECT', role_name;
  END IF;
  IF NOT has_column_privilege(role_name, 'public.spaces', 'type', 'SELECT') THEN
    RAISE EXCEPTION 'control-plane role % lacks spaces.type SELECT', role_name;
  END IF;
  IF has_column_privilege(role_name, 'public.spaces', 'name', 'SELECT') THEN
    RAISE EXCEPTION 'control-plane role % unexpectedly can SELECT spaces.name', role_name;
  END IF;"
  elif [[ "${memory_authority,,}" == "ts" ]]; then
    memory_grant_sql="-- Stage 6 memory slices (CONTROL_PLANE_MEMORY_AUTHORITY=ts): read model + pending proposal creation + read-access logging.
GRANT SELECT ON TABLE public.memory_entries TO \"$role\";
GRANT SELECT ON TABLE public.projects TO \"$role\";
GRANT INSERT ON TABLE public.proposals TO \"$role\";
GRANT INSERT ON TABLE public.memory_access_logs TO \"$role\";
GRANT UPDATE (access_count, last_accessed_at) ON TABLE public.memory_entries TO \"$role\";"
    memory_required_rows="('memory_entries', 'SELECT'),
      ('projects', 'SELECT'),
      ('proposals', 'INSERT'),
      ('memory_access_logs', 'INSERT'),"
    # memory_entries UPDATE is granted column-scoped only; the table-level check
    # below must still report it as denied (column grants do not satisfy
    # has_table_privilege), and INSERT/DELETE + apply tables stay fully denied.
    memory_denied_rows="('memory_entries', 'INSERT'),
      ('memory_entries', 'UPDATE'),
      ('memory_entries', 'DELETE'),
      ('provenance_links', 'INSERT'),
      ('memory_relations', 'INSERT'),
      ('spaces', 'SELECT'),"
    memory_column_checks="  IF NOT has_column_privilege(role_name, 'public.memory_entries', 'access_count', 'UPDATE') THEN
    RAISE EXCEPTION 'control-plane role % lacks memory_entries.access_count UPDATE', role_name;
  END IF;
  IF NOT has_column_privilege(role_name, 'public.memory_entries', 'last_accessed_at', 'UPDATE') THEN
    RAISE EXCEPTION 'control-plane role % lacks memory_entries.last_accessed_at UPDATE', role_name;
  END IF;
  IF has_column_privilege(role_name, 'public.memory_entries', 'content', 'UPDATE') THEN
    RAISE EXCEPTION 'control-plane role % unexpectedly can UPDATE memory_entries.content', role_name;
  END IF;
  IF has_column_privilege(role_name, 'public.memory_entries', 'visibility', 'UPDATE') THEN
    RAISE EXCEPTION 'control-plane role % unexpectedly can UPDATE memory_entries.visibility', role_name;
  END IF;
  IF has_column_privilege(role_name, 'public.spaces', 'id', 'SELECT') THEN
    RAISE EXCEPTION 'control-plane role % unexpectedly can SELECT spaces.id', role_name;
  END IF;
  IF has_column_privilege(role_name, 'public.spaces', 'type', 'SELECT') THEN
    RAISE EXCEPTION 'control-plane role % unexpectedly can SELECT spaces.type', role_name;
  END IF;"
  else
    memory_grant_sql="-- Stage 6 memory slices not flipped; cp role has no memory/project/proposal-create/log access."
    memory_required_rows=""
    memory_denied_rows="('memory_entries', 'SELECT'),
      ('projects', 'SELECT'),
      ('proposals', 'INSERT'),
      ('memory_access_logs', 'INSERT'),
      ('provenance_links', 'INSERT'),
      ('memory_relations', 'INSERT'),
      ('spaces', 'SELECT'),"
    memory_column_checks="  IF has_column_privilege(role_name, 'public.memory_entries', 'access_count', 'UPDATE') THEN
    RAISE EXCEPTION 'control-plane role % unexpectedly can UPDATE memory_entries.access_count', role_name;
  END IF;
  IF has_column_privilege(role_name, 'public.spaces', 'id', 'SELECT') THEN
    RAISE EXCEPTION 'control-plane role % unexpectedly can SELECT spaces.id', role_name;
  END IF;
  IF has_column_privilege(role_name, 'public.spaces', 'type', 'SELECT') THEN
    RAISE EXCEPTION 'control-plane role % unexpectedly can SELECT spaces.type', role_name;
  END IF;"
  fi

  local_compose_ensure_postgres_ready "$purpose" "$pguser" "$pgdb"

  echo "Configuring PostgreSQL control-plane role '$role' for mode '$MODE'..."
  echo "  - applying least-privilege provider, run, job, runtime metadata, policy audit, proposal review, and (when flipped) sessions, context-snapshot, and memory grants"
  "${COMPOSE[@]}" exec -T postgres psql -X -q -v ON_ERROR_STOP=1 -U "$pguser" "$pgdb" <<SQL
DO \$\$
DECLARE
  role_name text := '$role_sql';
  role_password text := '$password_sql';
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
    EXECUTE format('CREATE ROLE %I LOGIN PASSWORD %L', role_name, role_password);
  ELSE
    EXECUTE format('ALTER ROLE %I WITH LOGIN PASSWORD %L', role_name, role_password);
  END IF;
END
\$\$;

REVOKE ALL PRIVILEGES ON DATABASE "$pgdb" FROM "$role";
GRANT CONNECT ON DATABASE "$pgdb" TO "$role";
REVOKE TEMPORARY ON DATABASE "$pgdb" FROM "$role";
-- PostgreSQL grants TEMP (and CONNECT) on every database to PUBLIC by default,
-- and has_database_privilege() sees PUBLIC-inherited rights. Revoke TEMP from
-- PUBLIC so the least-privilege check below reflects reality; the main backend
-- role keeps TEMP implicitly as the database owner.
REVOKE TEMPORARY ON DATABASE "$pgdb" FROM PUBLIC;

REVOKE ALL PRIVILEGES ON SCHEMA public FROM "$role";
GRANT USAGE ON SCHEMA public TO "$role";

REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM "$role";
-- Column-level grants are stored separately from table ACLs; clear the slice
-- 7a counter bump and slice 7b placement-check grants explicitly before
-- rebuilding the memory grant tier.
REVOKE UPDATE (access_count, last_accessed_at) ON TABLE public.memory_entries FROM "$role";
REVOKE SELECT (id, type) ON TABLE public.spaces FROM "$role";

-- Providers/credentials TS authority.
GRANT SELECT, INSERT, UPDATE ON TABLE public.model_providers TO "$role";
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.credentials TO "$role";
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.model_provider_credentials TO "$role";
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.provider_task_policies TO "$role";
GRANT SELECT, INSERT ON TABLE public.cli_credential_events TO "$role";

-- Stage 4 TS-owned run orchestration. Keep grants table-scoped and avoid
-- unrelated context tables (memory/activity/policy/proposals/artifacts).
GRANT SELECT, INSERT, UPDATE ON TABLE public.runs TO "$role";
GRANT SELECT, INSERT, UPDATE ON TABLE public.run_steps TO "$role";
GRANT SELECT, INSERT ON TABLE public.run_events TO "$role";
-- run_steps.actor_id / run_events.actor_id are non-null Actor FKs; TS resolves
-- (and creates when absent) the same user/job/system actors Python uses.
GRANT SELECT, INSERT ON TABLE public.actors TO "$role";
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.run_execution_locks TO "$role";
GRANT SELECT, UPDATE ON TABLE public.jobs TO "$role";
GRANT SELECT, INSERT ON TABLE public.job_events TO "$role";

-- Trace-safe execution summaries needed for adapter/runtime resolution.
GRANT SELECT ON TABLE public.execution_planes TO "$role";
GRANT SELECT ON TABLE public.agents TO "$role";
GRANT SELECT ON TABLE public.agent_versions TO "$role";

-- TS-owned policy enforcement audit. TS may append/read durable policy
-- decisions, but must not update/delete audit rows or read unrelated contexts.
GRANT SELECT, INSERT ON TABLE public.policy_decision_records TO "$role";

-- TS-owned proposal review read surface. Apply/reject/egress writes
-- still dispatch through the internal Python proposal port, but the role keeps
-- explicit proposal-table permissions for the TS review lifecycle boundary.
GRANT SELECT, UPDATE ON TABLE public.proposals TO "$role";
GRANT SELECT, INSERT, UPDATE ON TABLE public.proposal_approvals TO "$role";

$sessions_grant_sql

$context_grant_sql

$memory_grant_sql

-- Least-privilege smoke test: required run/job privileges must exist; schema
-- mutation, run_event mutation, policy audit mutation, and unrelated
-- context-table reads must not.
DO \$\$
DECLARE
  role_name text := '$role_sql';
  item record;
BEGIN
  IF NOT has_database_privilege(role_name, current_database(), 'CONNECT') THEN
    RAISE EXCEPTION 'control-plane role % lacks CONNECT on database', role_name;
  END IF;
  IF has_database_privilege(role_name, current_database(), 'TEMP') THEN
    RAISE EXCEPTION 'control-plane role % unexpectedly has TEMP on database', role_name;
  END IF;
  IF NOT has_schema_privilege(role_name, 'public', 'USAGE') THEN
    RAISE EXCEPTION 'control-plane role % lacks USAGE on public schema', role_name;
  END IF;
  IF has_schema_privilege(role_name, 'public', 'CREATE') THEN
    RAISE EXCEPTION 'control-plane role % unexpectedly has CREATE on public schema', role_name;
  END IF;

  FOR item IN
    SELECT * FROM (VALUES
      $sessions_required_rows
      $context_required_rows
      $memory_required_rows
      ('model_providers', 'SELECT'),
      ('credentials', 'SELECT'),
      ('model_provider_credentials', 'SELECT'),
      ('provider_task_policies', 'SELECT'),
      ('cli_credential_events', 'INSERT'),
      ('runs', 'SELECT'),
      ('runs', 'INSERT'),
      ('runs', 'UPDATE'),
      ('run_steps', 'SELECT'),
      ('run_steps', 'INSERT'),
      ('run_steps', 'UPDATE'),
      ('run_events', 'SELECT'),
      ('run_events', 'INSERT'),
      ('run_execution_locks', 'SELECT'),
      ('run_execution_locks', 'INSERT'),
      ('run_execution_locks', 'UPDATE'),
      ('run_execution_locks', 'DELETE'),
      ('jobs', 'SELECT'),
      ('jobs', 'UPDATE'),
      ('job_events', 'SELECT'),
      ('job_events', 'INSERT'),
      ('execution_planes', 'SELECT'),
      ('agents', 'SELECT'),
      ('agent_versions', 'SELECT'),
      ('policy_decision_records', 'SELECT'),
      ('policy_decision_records', 'INSERT'),
      ('proposals', 'SELECT'),
      ('proposals', 'UPDATE'),
      ('proposal_approvals', 'SELECT'),
      ('proposal_approvals', 'INSERT'),
      ('proposal_approvals', 'UPDATE')
    ) AS required(table_name, privilege)
  LOOP
    IF NOT has_table_privilege(role_name, format('public.%I', item.table_name), item.privilege) THEN
      RAISE EXCEPTION 'control-plane role % lacks %.% privilege',
        role_name, item.table_name, item.privilege;
    END IF;
  END LOOP;

  FOR item IN
    SELECT * FROM (VALUES
      $sessions_denied_rows
      $context_denied_rows
      $memory_denied_rows
      ('sessions', 'DELETE'),
      ('messages', 'UPDATE'),
      ('messages', 'DELETE'),
      ('session_summaries', 'INSERT'),
      ('session_summaries', 'UPDATE'),
      ('session_summaries', 'DELETE'),
      ('run_events', 'UPDATE'),
      ('run_events', 'DELETE'),
      ('jobs', 'INSERT'),
      ('jobs', 'DELETE'),
      ('policy_decision_records', 'UPDATE'),
      ('policy_decision_records', 'DELETE'),
      ('proposals', 'DELETE'),
      ('proposal_approvals', 'DELETE'),
      ('memory_access_logs', 'SELECT'),
      ('activity_records', 'SELECT'),
      ('artifacts', 'SELECT')
    ) AS denied(table_name, privilege)
  LOOP
    IF has_table_privilege(role_name, format('public.%I', item.table_name), item.privilege) THEN
      RAISE EXCEPTION 'control-plane role % unexpectedly has %.% privilege',
        role_name, item.table_name, item.privilege;
    END IF;
  END LOOP;

  -- Stage 6 slice 7a: read-access logging needs a column-scoped counter bump on
  -- memory_entries, never table-wide write. Assert the exact column grants (or
  -- their absence when not flipped).
$memory_column_checks
END
\$\$;
SQL
  echo "  - verified required grants and denied unrelated context-table access"
  echo "Control-plane DB role '$role' is ready."
}
