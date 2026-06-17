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
  return 0
}

local_compose_ensure_control_plane_ts_authority_env() {
  [[ -f "$ENV_FILE" ]] || return 0

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

  # Public sessions are TS-owned. The role gains the session read model plus
  # session create + message append:
  # SELECT/INSERT/UPDATE on sessions (UPDATE touches updated_at),
  # SELECT/INSERT on messages, and SELECT on session_summaries for the
  # context-safe latest-summary read. Sessions are never DELETEd (no archive
  # semantics yet), messages are append-only, and summary condense writes are
  # not TS-owned yet, so those privileges stay denied.
  local sessions_grant_sql sessions_required_rows sessions_denied_rows
  sessions_grant_sql="-- TS-owned public sessions: read + create/append + summary read.
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

  # Context assembly is fixed TS-owned. context_snapshots support run-create and
  # finalization infrastructure; context_snapshot_items are appended by chat/full
  # context assembly. Full-run context additionally reads policies, digests,
  # memory relations, selected evidence, and personal-memory grant metadata/events.
  local context_grant_sql context_required_rows context_denied_rows context_column_checks
  context_grant_sql="-- Fixed TS-owned context assembly: snapshot items, source reads, digests, graph, evidence refs, and personal grant metadata.
GRANT SELECT, INSERT, UPDATE ON TABLE public.context_snapshot_items TO \"$role\";
GRANT SELECT, INSERT, UPDATE ON TABLE public.knowledge_items TO \"$role\";
GRANT SELECT, INSERT, UPDATE ON TABLE public.sources TO \"$role\";
GRANT SELECT, INSERT, UPDATE ON TABLE public.activity_records TO \"$role\";
GRANT SELECT ON TABLE public.policies TO \"$role\";
GRANT SELECT ON TABLE public.context_digests TO \"$role\";
GRANT SELECT ON TABLE public.memory_relations TO \"$role\";
GRANT SELECT, INSERT, UPDATE ON TABLE public.extracted_evidence TO \"$role\";
GRANT SELECT ON TABLE public.evidence_links TO \"$role\";
GRANT INSERT (id, space_id, evidence_id, target_type, target_id, link_type, status, created_by_run_id, created_at, updated_at) ON TABLE public.evidence_links TO \"$role\";
GRANT SELECT ON TABLE public.personal_memory_grants TO \"$role\";
GRANT UPDATE (status, consume_started_at, used_at, failed_at, failure_stage, updated_at) ON TABLE public.personal_memory_grants TO \"$role\";
GRANT INSERT ON TABLE public.personal_memory_grant_events TO \"$role\";"
  context_required_rows="('context_snapshot_items', 'SELECT'),
    ('context_snapshot_items', 'INSERT'),
    ('context_snapshot_items', 'UPDATE'),
    ('knowledge_items', 'SELECT'),
    ('knowledge_items', 'INSERT'),
    ('knowledge_items', 'UPDATE'),
    ('sources', 'SELECT'),
    ('sources', 'INSERT'),
    ('sources', 'UPDATE'),
    ('activity_records', 'SELECT'),
    ('activity_records', 'INSERT'),
    ('activity_records', 'UPDATE'),
    ('policies', 'SELECT'),
    ('context_digests', 'SELECT'),
    ('memory_relations', 'SELECT'),
    ('extracted_evidence', 'SELECT'),
    ('extracted_evidence', 'INSERT'),
    ('extracted_evidence', 'UPDATE'),
    ('evidence_links', 'SELECT'),
    ('personal_memory_grants', 'SELECT'),
    ('personal_memory_grant_events', 'INSERT'),"
  context_denied_rows="('context_snapshot_items', 'DELETE'),
    ('context_digests', 'INSERT'),
    ('context_digests', 'UPDATE'),
    ('context_digests', 'DELETE'),
    ('activity_records', 'DELETE'),
    ('knowledge_items', 'DELETE'),
    ('sources', 'DELETE'),
    ('extracted_evidence', 'DELETE'),
    ('evidence_links', 'INSERT'),
    ('evidence_links', 'UPDATE'),
    ('evidence_links', 'DELETE'),
    ('personal_memory_grants', 'UPDATE'),
    ('personal_memory_grants', 'INSERT'),
    ('personal_memory_grants', 'DELETE'),
    ('personal_memory_grant_events', 'UPDATE'),
    ('personal_memory_grant_events', 'DELETE'),"
  context_column_checks="  IF NOT has_column_privilege(role_name, 'public.evidence_links', 'id', 'INSERT') THEN
    RAISE EXCEPTION 'control-plane role % lacks evidence_links.id INSERT', role_name;
  END IF;
  IF NOT has_column_privilege(role_name, 'public.evidence_links', 'link_type', 'INSERT') THEN
    RAISE EXCEPTION 'control-plane role % lacks evidence_links.link_type INSERT', role_name;
  END IF;
  IF NOT has_column_privilege(role_name, 'public.evidence_links', 'created_by_run_id', 'INSERT') THEN
    RAISE EXCEPTION 'control-plane role % lacks evidence_links.created_by_run_id INSERT', role_name;
  END IF;
  IF has_column_privilege(role_name, 'public.evidence_links', 'confidence', 'INSERT') THEN
    RAISE EXCEPTION 'control-plane role % unexpectedly can INSERT evidence_links.confidence', role_name;
  END IF;
  IF has_column_privilege(role_name, 'public.evidence_links', 'reason', 'INSERT') THEN
    RAISE EXCEPTION 'control-plane role % unexpectedly can INSERT evidence_links.reason', role_name;
  END IF;
  IF NOT has_column_privilege(role_name, 'public.personal_memory_grants', 'status', 'UPDATE') THEN
    RAISE EXCEPTION 'control-plane role % lacks personal_memory_grants.status UPDATE', role_name;
  END IF;
  IF NOT has_column_privilege(role_name, 'public.personal_memory_grants', 'updated_at', 'UPDATE') THEN
    RAISE EXCEPTION 'control-plane role % lacks personal_memory_grants.updated_at UPDATE', role_name;
  END IF;
  IF NOT has_column_privilege(role_name, 'public.personal_memory_grants', 'failure_stage', 'UPDATE') THEN
    RAISE EXCEPTION 'control-plane role % lacks personal_memory_grants.failure_stage UPDATE', role_name;
  END IF;
  IF has_column_privilege(role_name, 'public.personal_memory_grants', 'memory_filter_json', 'UPDATE') THEN
    RAISE EXCEPTION 'control-plane role % unexpectedly can UPDATE personal_memory_grants.memory_filter_json', role_name;
  END IF;
  IF has_column_privilege(role_name, 'public.personal_memory_grants', 'target_run_id', 'UPDATE') THEN
    RAISE EXCEPTION 'control-plane role % unexpectedly can UPDATE personal_memory_grants.target_run_id', role_name;
  END IF;"

  # Memory read/proposal-create, read-access logging, and supported active-memory
  # proposal apply are fixed TS-owned. DELETE on memory_entries is never granted
  # (memory is soft-deleted via status). Spaces read access belongs to native
  # identity and is granted separately.
  local memory_grant_sql memory_required_rows memory_denied_rows memory_column_checks
  memory_grant_sql="-- Fixed TS-owned memory read/proposal-create + read-logging + active-memory apply.
GRANT SELECT, INSERT, UPDATE ON TABLE public.memory_entries TO \"$role\";
GRANT SELECT ON TABLE public.projects TO \"$role\";
GRANT INSERT ON TABLE public.proposals TO \"$role\";
GRANT INSERT ON TABLE public.memory_access_logs TO \"$role\";
GRANT SELECT, INSERT ON TABLE public.provenance_links TO \"$role\";
GRANT INSERT ON TABLE public.memory_relations TO \"$role\";"
  memory_required_rows="('memory_entries', 'SELECT'),
      ('memory_entries', 'INSERT'),
      ('memory_entries', 'UPDATE'),
      ('projects', 'SELECT'),
      ('proposals', 'INSERT'),
      ('memory_access_logs', 'INSERT'),
      ('provenance_links', 'SELECT'),
      ('provenance_links', 'INSERT'),
      ('memory_relations', 'INSERT'),"
  memory_denied_rows="('memory_entries', 'DELETE'),
      ('provenance_links', 'UPDATE'),
      ('provenance_links', 'DELETE'),"
  memory_column_checks=""

  # Leaf domains: activity capture, intake, knowledge notes/sources, tasks/boards,
  # and summary artifact creation. Shared context tables above already carry the
  # read/write grants those routes need.
  local leaf_domain_grant_sql leaf_domain_required_rows leaf_domain_denied_rows
  leaf_domain_grant_sql="-- TS-owned activity/intake/knowledge/tasks leaf domains.
GRANT SELECT ON TABLE public.source_connectors TO \"$role\";
GRANT SELECT, INSERT, UPDATE ON TABLE public.source_connections TO \"$role\";
GRANT SELECT, INSERT, UPDATE ON TABLE public.intake_items TO \"$role\";
GRANT SELECT, INSERT, UPDATE ON TABLE public.extraction_jobs TO \"$role\";
GRANT SELECT, INSERT, UPDATE ON TABLE public.workspace_intake_profiles TO \"$role\";
GRANT SELECT, INSERT ON TABLE public.workspace_source_bindings TO \"$role\";
GRANT SELECT, INSERT, UPDATE ON TABLE public.boards TO \"$role\";
GRANT SELECT, INSERT ON TABLE public.board_columns TO \"$role\";
GRANT SELECT, INSERT, UPDATE ON TABLE public.tasks TO \"$role\";
GRANT SELECT, INSERT ON TABLE public.task_runs TO \"$role\";
GRANT SELECT, INSERT ON TABLE public.task_evaluations TO \"$role\";
GRANT SELECT ON TABLE public.task_artifacts TO \"$role\";
GRANT SELECT, INSERT ON TABLE public.task_proposals TO \"$role\";
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.knowledge_item_sources TO \"$role\";
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.notes TO \"$role\";
GRANT SELECT, INSERT, DELETE ON TABLE public.entity_links TO \"$role\";
GRANT SELECT, INSERT, DELETE ON TABLE public.note_collection_items TO \"$role\";
GRANT SELECT, INSERT, UPDATE ON TABLE public.knowledge_item_relations TO \"$role\";"
  leaf_domain_required_rows="('source_connectors', 'SELECT'),
    ('source_connections', 'SELECT'),
    ('source_connections', 'INSERT'),
    ('source_connections', 'UPDATE'),
    ('intake_items', 'SELECT'),
    ('intake_items', 'INSERT'),
    ('intake_items', 'UPDATE'),
    ('extraction_jobs', 'SELECT'),
    ('extraction_jobs', 'INSERT'),
    ('extraction_jobs', 'UPDATE'),
    ('workspace_intake_profiles', 'SELECT'),
    ('workspace_intake_profiles', 'INSERT'),
    ('workspace_intake_profiles', 'UPDATE'),
    ('workspace_source_bindings', 'SELECT'),
    ('workspace_source_bindings', 'INSERT'),
    ('boards', 'SELECT'),
    ('boards', 'INSERT'),
    ('boards', 'UPDATE'),
    ('board_columns', 'SELECT'),
    ('board_columns', 'INSERT'),
    ('tasks', 'SELECT'),
    ('tasks', 'INSERT'),
    ('tasks', 'UPDATE'),
    ('task_runs', 'SELECT'),
    ('task_runs', 'INSERT'),
    ('task_evaluations', 'SELECT'),
    ('task_evaluations', 'INSERT'),
    ('task_artifacts', 'SELECT'),
    ('task_proposals', 'SELECT'),
    ('task_proposals', 'INSERT'),
    ('knowledge_item_sources', 'SELECT'),
    ('knowledge_item_sources', 'INSERT'),
    ('knowledge_item_sources', 'UPDATE'),
    ('knowledge_item_sources', 'DELETE'),
    ('notes', 'SELECT'),
    ('notes', 'INSERT'),
    ('notes', 'UPDATE'),
    ('notes', 'DELETE'),
    ('entity_links', 'SELECT'),
    ('entity_links', 'INSERT'),
    ('entity_links', 'DELETE'),
    ('note_collection_items', 'SELECT'),
    ('note_collection_items', 'INSERT'),
    ('note_collection_items', 'DELETE'),
    ('knowledge_item_relations', 'SELECT'),
    ('knowledge_item_relations', 'INSERT'),
    ('knowledge_item_relations', 'UPDATE'),"
  local scheduler_grant_sql scheduler_required_rows scheduler_denied_rows scheduler_column_checks
  scheduler_grant_sql="-- TS-owned automations, daily reports, and retention pruning.
GRANT SELECT, INSERT, UPDATE ON TABLE public.automations TO \"$role\";
GRANT SELECT, INSERT ON TABLE public.automation_runs TO \"$role\";
GRANT SELECT, INSERT, UPDATE ON TABLE public.automation_credential_grants TO \"$role\";
GRANT SELECT, INSERT, UPDATE ON TABLE public.daily_capture_report_settings TO \"$role\";
GRANT INSERT (id, space_id, owner_user_id, name, description, role_instruction, status, agent_kind, visibility, created_at, updated_at) ON TABLE public.agents TO \"$role\";
GRANT UPDATE (name, description, role_instruction, status, visibility, current_version_id, updated_at) ON TABLE public.agents TO \"$role\";
GRANT INSERT (id, agent_id, space_id, version_label, model_provider_id, model_name, system_prompt, model_config_json, runtime_config_json, context_policy_json, memory_policy_json, capabilities_json, tool_permissions_json, runtime_policy_json, tool_policy_json, output_policy_json, schedule_config_json, output_schema_json, created_at) ON TABLE public.agent_versions TO \"$role\";
GRANT SELECT, INSERT, UPDATE ON TABLE public.space_assistant_settings TO \"$role\";
GRANT SELECT (accessed_at) ON TABLE public.memory_access_logs TO \"$role\";
GRANT DELETE ON TABLE public.memory_access_logs TO \"$role\";"
  scheduler_required_rows="('jobs', 'INSERT'),
    ('automations', 'SELECT'),
    ('automations', 'INSERT'),
    ('automations', 'UPDATE'),
    ('automation_runs', 'SELECT'),
    ('automation_runs', 'INSERT'),
    ('automation_credential_grants', 'SELECT'),
    ('automation_credential_grants', 'INSERT'),
    ('automation_credential_grants', 'UPDATE'),
    ('daily_capture_report_settings', 'SELECT'),
    ('daily_capture_report_settings', 'INSERT'),
    ('daily_capture_report_settings', 'UPDATE'),
    ('space_assistant_settings', 'SELECT'),
    ('space_assistant_settings', 'INSERT'),
    ('space_assistant_settings', 'UPDATE'),
    ('memory_access_logs', 'DELETE'),"
  scheduler_denied_rows="('automations', 'DELETE'),
    ('automation_runs', 'UPDATE'),
    ('automation_runs', 'DELETE'),
    ('automation_credential_grants', 'DELETE'),
    ('daily_capture_report_settings', 'DELETE'),
    ('space_assistant_settings', 'DELETE'),"
  scheduler_column_checks="  IF NOT has_column_privilege(role_name, 'public.agents', 'id', 'INSERT') THEN
    RAISE EXCEPTION 'control-plane role % lacks agents.id INSERT', role_name;
  END IF;
  IF NOT has_column_privilege(role_name, 'public.agents', 'owner_user_id', 'INSERT') THEN
    RAISE EXCEPTION 'control-plane role % lacks agents.owner_user_id INSERT', role_name;
  END IF;
  IF NOT has_column_privilege(role_name, 'public.agents', 'name', 'UPDATE') THEN
    RAISE EXCEPTION 'control-plane role % lacks agents.name UPDATE', role_name;
  END IF;
  IF NOT has_column_privilege(role_name, 'public.agents', 'current_version_id', 'UPDATE') THEN
    RAISE EXCEPTION 'control-plane role % lacks agents.current_version_id UPDATE', role_name;
  END IF;
  IF NOT has_column_privilege(role_name, 'public.agent_versions', 'model_provider_id', 'INSERT') THEN
    RAISE EXCEPTION 'control-plane role % lacks agent_versions.model_provider_id INSERT', role_name;
  END IF;
  IF NOT has_column_privilege(role_name, 'public.agent_versions', 'runtime_config_json', 'INSERT') THEN
    RAISE EXCEPTION 'control-plane role % lacks agent_versions.runtime_config_json INSERT', role_name;
  END IF;
  IF NOT has_column_privilege(role_name, 'public.agent_versions', 'tool_policy_json', 'INSERT') THEN
    RAISE EXCEPTION 'control-plane role % lacks agent_versions.tool_policy_json INSERT', role_name;
  END IF;
  IF NOT has_table_privilege(role_name, 'public.space_assistant_settings', 'INSERT') THEN
    RAISE EXCEPTION 'control-plane role % lacks space_assistant_settings INSERT', role_name;
  END IF;
  IF NOT has_column_privilege(role_name, 'public.memory_access_logs', 'accessed_at', 'SELECT') THEN
    RAISE EXCEPTION 'control-plane role % lacks memory_access_logs.accessed_at SELECT', role_name;
  END IF;"
  leaf_domain_denied_rows="('source_connections', 'DELETE'),
    ('intake_items', 'DELETE'),
    ('extraction_jobs', 'DELETE'),
    ('workspace_intake_profiles', 'DELETE'),
    ('workspace_source_bindings', 'UPDATE'),
    ('workspace_source_bindings', 'DELETE'),
    ('boards', 'DELETE'),
    ('board_columns', 'UPDATE'),
    ('board_columns', 'DELETE'),
    ('tasks', 'DELETE'),
    ('task_runs', 'UPDATE'),
    ('task_runs', 'DELETE'),
    ('task_evaluations', 'UPDATE'),
    ('task_evaluations', 'DELETE'),
    ('task_artifacts', 'INSERT'),
    ('task_artifacts', 'UPDATE'),
    ('task_artifacts', 'DELETE'),
    ('task_proposals', 'UPDATE'),
    ('task_proposals', 'DELETE'),
    ('knowledge_item_relations', 'DELETE'),"

  local_compose_ensure_postgres_ready "$purpose" "$pguser" "$pgdb"

  echo "Configuring PostgreSQL control-plane role '$role' for mode '$MODE'..."
  echo "  - applying least-privilege identity, provider, run, job, runtime metadata, policy audit, proposal review/apply, sessions, context, memory, artifact, leaf-domain, and scheduler/automation grants"
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
-- Column-level grants are stored separately from table ACLs; clear the identity
-- and memory column grants explicitly before rebuilding the grant tiers.
REVOKE SELECT (id, email, display_name, avatar_url, created_at, last_login_at) ON TABLE public.users FROM "$role";
REVOKE INSERT (id, email, display_name, avatar_url, status, last_login_at, created_at, updated_at) ON TABLE public.users FROM "$role";
REVOKE UPDATE (email, display_name, avatar_url, last_login_at, updated_at) ON TABLE public.users FROM "$role";
REVOKE SELECT (user_id, provider, provider_user_id) ON TABLE public.auth_accounts FROM "$role";
REVOKE INSERT (id, user_id, provider, provider_user_id, email, created_at) ON TABLE public.auth_accounts FROM "$role";
REVOKE SELECT (id, user_id, token_hash, expires_at) ON TABLE public.user_sessions FROM "$role";
REVOKE INSERT (id, user_id, token_hash, created_at, expires_at, last_seen_at) ON TABLE public.user_sessions FROM "$role";
REVOKE UPDATE (last_seen_at) ON TABLE public.user_sessions FROM "$role";
REVOKE SELECT (id, space_id, user_id, role, status, created_at) ON TABLE public.space_memberships FROM "$role";
REVOKE INSERT (id, space_id, user_id, role, status, created_at, updated_at) ON TABLE public.space_memberships FROM "$role";
REVOKE SELECT (id, name, type, created_by_user_id, created_at, updated_at) ON TABLE public.spaces FROM "$role";
REVOKE INSERT (id, name, type, created_by_user_id, created_at, updated_at) ON TABLE public.spaces FROM "$role";
REVOKE SELECT (id, space_id, invited_email, role, token_hash, status, expires_at, accepted_at) ON TABLE public.space_invitations FROM "$role";
REVOKE INSERT (id, space_id, invited_email, role, token_hash, status, invited_by_user_id, created_at, expires_at) ON TABLE public.space_invitations FROM "$role";
REVOKE UPDATE (status, accepted_at) ON TABLE public.space_invitations FROM "$role";
REVOKE INSERT (id, space_id, name, type, provider, execution_location, runtime_origin, trust_level, observability_level, data_exposure_level, credential_mode, config_json, enabled, created_at, updated_at) ON TABLE public.execution_planes FROM "$role";
REVOKE SELECT (space_id, namespace, scope_type, deleted_at) ON TABLE public.memory_entries FROM "$role";
REVOKE INSERT (id, space_id, scope_type, scope_id, memory_type, content, status, created_at, updated_at, subject_user_id, owner_user_id, sensitivity_level, namespace, title, visibility, confidence, importance, created_by, version, access_count) ON TABLE public.memory_entries FROM "$role";
REVOKE UPDATE (access_count, last_accessed_at, last_retrieved_at) ON TABLE public.memory_entries FROM "$role";
REVOKE INSERT (id, space_id, evidence_id, target_type, target_id, link_type, status, created_by_run_id, created_at, updated_at) ON TABLE public.evidence_links FROM "$role";
REVOKE UPDATE (status, consume_started_at, used_at, failed_at, failure_stage, updated_at) ON TABLE public.personal_memory_grants FROM "$role";
REVOKE SELECT (id, space_id, system_role) ON TABLE public.note_collections FROM "$role";
REVOKE INSERT (id, space_id, parent_id, name, system_role, sort_order, is_system, is_hidden, created_at, updated_at) ON TABLE public.note_collections FROM "$role";

-- Native TS auth/spaces. Column-scoped grants cover session-cookie auth,
-- Google OAuth user/session creation, membership/default-space selection,
-- /me, /me/spaces, space create/read/member/invitation routes, and deterministic
-- space-created seeds. Table-wide writes remain denied except logout DELETE.
GRANT SELECT (id, email, display_name, avatar_url, created_at, last_login_at) ON TABLE public.users TO "$role";
GRANT INSERT (id, email, display_name, avatar_url, status, last_login_at, created_at, updated_at) ON TABLE public.users TO "$role";
GRANT UPDATE (email, display_name, avatar_url, last_login_at, updated_at) ON TABLE public.users TO "$role";
GRANT SELECT (user_id, provider, provider_user_id) ON TABLE public.auth_accounts TO "$role";
GRANT INSERT (id, user_id, provider, provider_user_id, email, created_at) ON TABLE public.auth_accounts TO "$role";
GRANT SELECT (id, user_id, token_hash, expires_at) ON TABLE public.user_sessions TO "$role";
GRANT INSERT (id, user_id, token_hash, created_at, expires_at, last_seen_at) ON TABLE public.user_sessions TO "$role";
GRANT UPDATE (last_seen_at) ON TABLE public.user_sessions TO "$role";
GRANT DELETE ON TABLE public.user_sessions TO "$role";
GRANT SELECT (id, space_id, user_id, role, status, created_at) ON TABLE public.space_memberships TO "$role";
GRANT INSERT (id, space_id, user_id, role, status, created_at, updated_at) ON TABLE public.space_memberships TO "$role";
GRANT SELECT (id, name, type, created_by_user_id, created_at, updated_at) ON TABLE public.spaces TO "$role";
GRANT INSERT (id, name, type, created_by_user_id, created_at, updated_at) ON TABLE public.spaces TO "$role";
GRANT SELECT (id, space_id, invited_email, role, token_hash, status, expires_at, accepted_at) ON TABLE public.space_invitations TO "$role";
GRANT INSERT (id, space_id, invited_email, role, token_hash, status, invited_by_user_id, created_at, expires_at) ON TABLE public.space_invitations TO "$role";
GRANT UPDATE (status, accepted_at) ON TABLE public.space_invitations TO "$role";
GRANT INSERT (id, space_id, name, type, provider, execution_location, runtime_origin, trust_level, observability_level, data_exposure_level, credential_mode, config_json, enabled, created_at, updated_at) ON TABLE public.execution_planes TO "$role";
GRANT SELECT (space_id, namespace, scope_type, deleted_at) ON TABLE public.memory_entries TO "$role";
GRANT INSERT (id, space_id, scope_type, scope_id, memory_type, content, status, created_at, updated_at, subject_user_id, owner_user_id, sensitivity_level, namespace, title, visibility, confidence, importance, created_by, version, access_count) ON TABLE public.memory_entries TO "$role";
GRANT SELECT (id, space_id, system_role) ON TABLE public.note_collections TO "$role";
GRANT INSERT (id, space_id, parent_id, name, system_role, sort_order, is_system, is_hidden, created_at, updated_at) ON TABLE public.note_collections TO "$role";

-- Providers/credentials TS authority.
GRANT SELECT, INSERT, UPDATE ON TABLE public.model_providers TO "$role";
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.credentials TO "$role";
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.model_provider_credentials TO "$role";
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.provider_task_policies TO "$role";
GRANT SELECT, INSERT ON TABLE public.cli_credential_events TO "$role";

-- Stage 4 TS-owned run orchestration/read/finalization. Keep grants scoped to
-- run execution evidence, minimal run-create validation, and trace summaries.
GRANT SELECT, INSERT, UPDATE ON TABLE public.runs TO "$role";
GRANT SELECT, INSERT, UPDATE ON TABLE public.run_steps TO "$role";
GRANT SELECT, INSERT ON TABLE public.run_events TO "$role";
GRANT SELECT, INSERT ON TABLE public.run_evaluations TO "$role";
GRANT SELECT, INSERT ON TABLE public.run_finalizations TO "$role";
GRANT SELECT, INSERT, UPDATE ON TABLE public.context_snapshots TO "$role";
-- run_steps.actor_id / run_events.actor_id are non-null Actor FKs; TS resolves
-- (and creates when absent) the same user/job/system actors Python uses.
GRANT SELECT, INSERT ON TABLE public.actors TO "$role";
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.run_execution_locks TO "$role";
GRANT SELECT, INSERT, UPDATE ON TABLE public.jobs TO "$role";
GRANT SELECT, INSERT ON TABLE public.job_events TO "$role";

-- Trace-safe execution summaries needed for adapter/runtime resolution.
GRANT SELECT ON TABLE public.execution_planes TO "$role";
GRANT SELECT ON TABLE public.agents TO "$role";
GRANT SELECT ON TABLE public.agent_versions TO "$role";
GRANT SELECT, INSERT, UPDATE ON TABLE public.workspaces TO "$role";
GRANT SELECT ON TABLE public.projects TO "$role";
GRANT SELECT, INSERT ON TABLE public.artifacts TO "$role";

-- TS-owned policy enforcement audit. TS may append/read durable policy
-- decisions, but must not update/delete audit rows or read unrelated contexts.
GRANT SELECT, INSERT ON TABLE public.policy_decision_records TO "$role";

-- TS-owned proposal review/apply surface.
GRANT SELECT, UPDATE ON TABLE public.proposals TO "$role";
GRANT SELECT, INSERT, UPDATE ON TABLE public.proposal_approvals TO "$role";
GRANT SELECT ON TABLE public.personal_memory_grants TO "$role";
GRANT SELECT ON TABLE public.personal_memory_grant_events TO "$role";

$sessions_grant_sql

$context_grant_sql

$memory_grant_sql

$leaf_domain_grant_sql

$scheduler_grant_sql

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
      $leaf_domain_required_rows
      $scheduler_required_rows
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
      ('run_evaluations', 'SELECT'),
      ('run_evaluations', 'INSERT'),
      ('run_finalizations', 'SELECT'),
      ('run_finalizations', 'INSERT'),
      ('context_snapshots', 'SELECT'),
      ('context_snapshots', 'INSERT'),
      ('context_snapshots', 'UPDATE'),
      ('run_execution_locks', 'SELECT'),
      ('run_execution_locks', 'INSERT'),
      ('run_execution_locks', 'UPDATE'),
      ('run_execution_locks', 'DELETE'),
      ('jobs', 'SELECT'),
      ('jobs', 'INSERT'),
      ('jobs', 'UPDATE'),
      ('job_events', 'SELECT'),
      ('job_events', 'INSERT'),
      ('execution_planes', 'SELECT'),
      ('agents', 'SELECT'),
      ('agent_versions', 'SELECT'),
      ('workspaces', 'SELECT'),
      ('workspaces', 'INSERT'),
      ('workspaces', 'UPDATE'),
      ('artifacts', 'SELECT'),
      ('artifacts', 'INSERT'),
      ('policy_decision_records', 'SELECT'),
      ('policy_decision_records', 'INSERT'),
      ('proposals', 'SELECT'),
      ('proposals', 'UPDATE'),
      ('proposal_approvals', 'SELECT'),
      ('proposal_approvals', 'INSERT'),
      ('proposal_approvals', 'UPDATE'),
      ('personal_memory_grants', 'SELECT'),
      ('personal_memory_grant_events', 'SELECT'),
      ('user_sessions', 'DELETE')
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
      $leaf_domain_denied_rows
      $scheduler_denied_rows
      ('sessions', 'DELETE'),
      ('messages', 'UPDATE'),
      ('messages', 'DELETE'),
      ('session_summaries', 'INSERT'),
      ('session_summaries', 'UPDATE'),
      ('session_summaries', 'DELETE'),
      ('run_events', 'UPDATE'),
      ('run_events', 'DELETE'),
      ('workspaces', 'DELETE'),
      ('jobs', 'DELETE'),
      ('policy_decision_records', 'UPDATE'),
      ('policy_decision_records', 'DELETE'),
      ('proposals', 'DELETE'),
      ('proposal_approvals', 'DELETE'),
      ('memory_access_logs', 'SELECT'),
      ('artifacts', 'UPDATE'),
      ('artifacts', 'DELETE'),
      ('users', 'UPDATE'),
      ('users', 'DELETE'),
      ('user_sessions', 'INSERT'),
      ('space_memberships', 'INSERT'),
      ('space_memberships', 'UPDATE'),
      ('space_memberships', 'DELETE')
    ) AS denied(table_name, privilege)
  LOOP
    IF has_table_privilege(role_name, format('public.%I', item.table_name), item.privilege) THEN
      RAISE EXCEPTION 'control-plane role % unexpectedly has %.% privilege',
        role_name, item.table_name, item.privilege;
    END IF;
  END LOOP;

  -- Memory read-access logging needs a column-scoped counter bump on
  -- memory_entries, never table-wide write. Assert the exact column grants.
  IF NOT has_column_privilege(role_name, 'public.users', 'id', 'SELECT') THEN
    RAISE EXCEPTION 'control-plane role % lacks users.id SELECT', role_name;
  END IF;
  IF NOT has_column_privilege(role_name, 'public.user_sessions', 'token_hash', 'SELECT') THEN
    RAISE EXCEPTION 'control-plane role % lacks user_sessions.token_hash SELECT', role_name;
  END IF;
  IF NOT has_column_privilege(role_name, 'public.user_sessions', 'last_seen_at', 'UPDATE') THEN
    RAISE EXCEPTION 'control-plane role % lacks user_sessions.last_seen_at UPDATE', role_name;
  END IF;
  IF NOT has_column_privilege(role_name, 'public.space_memberships', 'space_id', 'SELECT') THEN
    RAISE EXCEPTION 'control-plane role % lacks space_memberships.space_id SELECT', role_name;
  END IF;
  IF NOT has_column_privilege(role_name, 'public.spaces', 'name', 'SELECT') THEN
    RAISE EXCEPTION 'control-plane role % lacks spaces.name SELECT', role_name;
  END IF;
  IF NOT has_column_privilege(role_name, 'public.users', 'display_name', 'UPDATE') THEN
    RAISE EXCEPTION 'control-plane role % lacks users.display_name UPDATE', role_name;
  END IF;
  IF has_column_privilege(role_name, 'public.users', 'status', 'UPDATE') THEN
    RAISE EXCEPTION 'control-plane role % unexpectedly can UPDATE users.status', role_name;
  END IF;
  IF NOT has_column_privilege(role_name, 'public.users', 'email', 'INSERT') THEN
    RAISE EXCEPTION 'control-plane role % lacks users.email INSERT', role_name;
  END IF;
  IF NOT has_column_privilege(role_name, 'public.auth_accounts', 'provider_user_id', 'SELECT') THEN
    RAISE EXCEPTION 'control-plane role % lacks auth_accounts.provider_user_id SELECT', role_name;
  END IF;
  IF NOT has_column_privilege(role_name, 'public.auth_accounts', 'provider_user_id', 'INSERT') THEN
    RAISE EXCEPTION 'control-plane role % lacks auth_accounts.provider_user_id INSERT', role_name;
  END IF;
  IF NOT has_column_privilege(role_name, 'public.user_sessions', 'token_hash', 'INSERT') THEN
    RAISE EXCEPTION 'control-plane role % lacks user_sessions.token_hash INSERT', role_name;
  END IF;
  IF NOT has_column_privilege(role_name, 'public.space_memberships', 'role', 'INSERT') THEN
    RAISE EXCEPTION 'control-plane role % lacks space_memberships.role INSERT', role_name;
  END IF;
  IF NOT has_column_privilege(role_name, 'public.spaces', 'name', 'INSERT') THEN
    RAISE EXCEPTION 'control-plane role % lacks spaces.name INSERT', role_name;
  END IF;
  IF NOT has_column_privilege(role_name, 'public.space_invitations', 'token_hash', 'SELECT') THEN
    RAISE EXCEPTION 'control-plane role % lacks space_invitations.token_hash SELECT', role_name;
  END IF;
  IF NOT has_column_privilege(role_name, 'public.space_invitations', 'token_hash', 'INSERT') THEN
    RAISE EXCEPTION 'control-plane role % lacks space_invitations.token_hash INSERT', role_name;
  END IF;
  IF NOT has_column_privilege(role_name, 'public.space_invitations', 'status', 'UPDATE') THEN
    RAISE EXCEPTION 'control-plane role % lacks space_invitations.status UPDATE', role_name;
  END IF;
  IF NOT has_column_privilege(role_name, 'public.execution_planes', 'name', 'INSERT') THEN
    RAISE EXCEPTION 'control-plane role % lacks execution_planes.name INSERT', role_name;
  END IF;
  IF NOT has_column_privilege(role_name, 'public.memory_entries', 'namespace', 'SELECT') THEN
    RAISE EXCEPTION 'control-plane role % lacks memory_entries.namespace SELECT', role_name;
  END IF;
  IF NOT has_column_privilege(role_name, 'public.memory_entries', 'namespace', 'INSERT') THEN
    RAISE EXCEPTION 'control-plane role % lacks memory_entries.namespace INSERT', role_name;
  END IF;
  IF NOT has_column_privilege(role_name, 'public.note_collections', 'system_role', 'SELECT') THEN
    RAISE EXCEPTION 'control-plane role % lacks note_collections.system_role SELECT', role_name;
  END IF;
  IF NOT has_column_privilege(role_name, 'public.note_collections', 'system_role', 'INSERT') THEN
    RAISE EXCEPTION 'control-plane role % lacks note_collections.system_role INSERT', role_name;
  END IF;
$context_column_checks
$memory_column_checks
$scheduler_column_checks
END
\$\$;
SQL
  echo "  - verified required grants and denied unrelated table access"
  echo "Control-plane DB role '$role' is ready."
}
