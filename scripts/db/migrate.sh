#!/usr/bin/env bash
# Run Alembic migrations (upgrade head) against the PostgreSQL database.
#
# Two execution modes:
#
#   docker (default) — run Alembic INSIDE the backend service via Docker Compose,
#     so it uses the in-network `postgres` host and the matching PostgreSQL client
#     and Python deps shipped in the backend image. This is the reliable path for
#     the default Docker Compose setup, where Postgres is NOT published to the host.
#
#   host (--host)    — run Alembic on the host against an explicitly configured,
#     reachable external PostgreSQL. Requires DATABASE_URL (or a complete set of
#     POSTGRES_* with POSTGRES_HOST). A connectivity preflight runs first so the
#     DB is never left half-migrated when the host cannot reach Postgres.
#
# Pre-migration backup safety:
#   For --mode prod a pre-migration pg_dump custom-format backup is REQUIRED and
#   is taken before Alembic runs, written to:
#       $ASPACE_ROOT/<mode>/db/dumps/pre-migrate-<timestamp>.dump
#   If that dump fails, migration aborts before Alembic touches the schema.
#   Non-prod modes skip it for convenience; opt in with PRE_MIGRATION_BACKUP=1
#   or the --pre-migration-backup flag to get the identical safety net.
#
# PostgreSQL is the server database; Alembic owns all schema creation and
# migration.
#
# Credentials are never printed — the target is shown with credentials redacted.
#
# Usage:
#   scripts/db/migrate.sh [--mode dev|test|prod]            # docker-native (default)
#   scripts/db/migrate.sh --host [--mode dev|test|prod]     # host mode, external Postgres
#   scripts/db/migrate.sh --mode dev --pre-migration-backup # opt into pre-migration dump
#   DATABASE_URL=postgresql+psycopg://... scripts/db/migrate.sh --host

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/local-compose.sh
source "$SCRIPT_DIR/../lib/local-compose.sh"

MODE="${AGENT_SPACE_MODE:-dev}"
RUN_MODE="docker"
PRE_MIGRATION_BACKUP="${PRE_MIGRATION_BACKUP:-0}"

# ── Argument parsing (before computing mode-dependent paths) ───────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) MODE="$2"; shift 2 ;;
    --host) RUN_MODE="host"; shift ;;
    --docker) RUN_MODE="docker"; shift ;;
    --pre-migration-backup) PRE_MIGRATION_BACKUP="1"; shift ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,2\}//'; exit 0 ;;
    *) echo "ERROR: unknown option: $1" >&2; exit 1 ;;
  esac
done

local_compose_init "$MODE"
BACKEND_DIR="$REPO_ROOT/core/backend"
trap 'local_compose_stop_postgres_if_started "migrate"' EXIT

redacted_target() {
  # Show only host:port/db — never user:pass.
  local safe="${1#*://}"   # drop scheme://
  safe="${safe##*@}"       # drop user:pass@, keep host:port/db
  echo "postgresql+psycopg://[credentials-redacted]@${safe}"
}

# Resolve a host-mode DATABASE_URL (env, mode .env, or POSTGRES_* parts). Sets the
# global DATABASE_URL or exits with a clear error. Never prints credentials.
resolve_host_database_url() {
  local database_url="${DATABASE_URL:-}"
  if [[ -z "$database_url" ]]; then
    database_url="$(local_compose_env_value DATABASE_URL || true)"
  fi
  if [[ -z "$database_url" ]]; then
    local pguser pgpass pgdb pghost pgport
    pguser="$(local_compose_setting POSTGRES_USER || true)"
    pgpass="$(local_compose_setting POSTGRES_PASSWORD || true)"
    pgdb="$(local_compose_setting POSTGRES_DB || true)"
    if [[ -n "$pguser" && -n "$pgpass" && -n "$pgdb" ]]; then
      pghost="$(local_compose_setting_or_default POSTGRES_HOST localhost)"
      pgport="$(local_compose_setting_or_default POSTGRES_PORT 5432)"
      database_url="postgresql+psycopg://${pguser}:${pgpass}@${pghost}:${pgport}/${pgdb}"
    fi
  fi
  if [[ -z "$database_url" ]]; then
    echo "ERROR: host mode requires a reachable external Postgres." >&2
    echo "       Set DATABASE_URL, or provide $ENV_FILE with POSTGRES_USER/PASSWORD/DB (+ POSTGRES_HOST)." >&2
    exit 1
  fi
  export DATABASE_URL="$database_url"
}

# ── Pre-migration backup (custom-format pg_dump) ──────────────────────────────
pre_migration_backup_docker() {
  local out="$1"
  local pgdb pguser
  pgdb="$(local_compose_setting_or_default POSTGRES_DB agent_space)"
  pguser="$(local_compose_setting_or_default POSTGRES_USER agent_space)"
  local_compose_validate_pg_identifier "POSTGRES_DB" "$pgdb"
  local_compose_validate_pg_identifier "POSTGRES_USER" "$pguser"

  # Ensure postgres is up so it can be dumped before any schema change.
  if ! local_compose_ensure_postgres_ready "migration" "$pguser"; then
    return 1
  fi
  "${COMPOSE[@]}" exec -T postgres \
    pg_dump -U "$pguser" -Fc --no-owner --no-acl "$pgdb" > "$out"
}

pre_migration_backup_host() {
  local out="$1"
  resolve_host_database_url
  # pg_dump speaks the standard libpq URI scheme, not the SQLAlchemy +psycopg one.
  local uri="${DATABASE_URL/postgresql+psycopg:/postgresql:}"
  pg_dump -Fc --no-owner --no-acl "$uri" > "$out"
}

ensure_pre_migration_backup() {
  local dumps_dir="$MODE_ROOT/db/dumps"
  install -d -m 700 "$dumps_dir"
  local ts dump_path
  ts="$(date -u +%Y%m%d-%H%M%S)"
  dump_path="$dumps_dir/pre-migrate-$ts.dump"

  echo "[migrate] taking required pre-migration backup before Alembic (mode: $MODE)..."
  if [[ "$RUN_MODE" == "host" ]]; then
    pre_migration_backup_host "$dump_path" || true
  else
    pre_migration_backup_docker "$dump_path" || true
  fi

  if [[ ! -s "$dump_path" ]]; then
    echo "ERROR: pre-migration backup failed or produced an empty dump." >&2
    echo "       Aborting BEFORE Alembic runs so the database is never migrated unprotected." >&2
    rm -f "$dump_path"
    exit 1
  fi
  chmod 600 "$dump_path"
  echo "[migrate] pre-migration backup written: $dump_path ($(du -sh "$dump_path" | cut -f1))"
}

# ── Docker-native path (default) ──────────────────────────────────────────────
run_docker() {
  echo "Running Alembic migrations in the backend container (mode: $MODE)..."
  echo "  target: in-network postgres service (DATABASE_URL from compose env)"

  local running=""
  running="$("${COMPOSE[@]}" ps --services --filter status=running 2>/dev/null || true)"

  if [[ $'\n'"$running"$'\n' == *$'\n'backend$'\n'* ]]; then
    # Backend already running — exec into it (cheapest, shares the live network).
    "${COMPOSE[@]}" exec -T backend python -m alembic upgrade head
  else
    local pguser
    pguser="$(local_compose_setting_or_default POSTGRES_USER agent_space)"
    local_compose_validate_pg_identifier "POSTGRES_USER" "$pguser"
    local_compose_ensure_postgres_ready "migration" "$pguser"
    # Backend not running — one-shot container. Compose starts the postgres
    # dependency (depends_on: service_healthy) before Alembic connects.
    "${COMPOSE[@]}" run --rm -T backend python -m alembic upgrade head
  fi
  echo "Migrations complete."
}

# ── Host path (explicit external Postgres only) ───────────────────────────────
run_host() {
  resolve_host_database_url

  echo "Running Alembic migrations on host (mode: $MODE)..."
  echo "  target: $(redacted_target "$DATABASE_URL")"

  # Connectivity preflight — fail fast (and clearly) before Alembic runs so a
  # caller like reset-postgres.sh never leaves a dropped/created DB unmigrated.
  if ! DATABASE_URL="$DATABASE_URL" python3 - <<'PY'
import os, sys
from sqlalchemy import create_engine, text
try:
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
except Exception as exc:  # never echo the exception (may contain credentials)
    sys.stderr.write(f"unreachable: {type(exc).__name__}\n")
    sys.exit(1)
PY
  then
    echo "ERROR: cannot reach the configured Postgres in host mode." >&2
    echo "       Verify the database is running and DATABASE_URL points to a reachable host:port." >&2
    echo "       For the default Docker Compose setup, drop --host to migrate inside the backend container." >&2
    exit 1
  fi

  cd "$BACKEND_DIR"
  DATABASE_URL="$DATABASE_URL" python3 -m alembic upgrade head
  echo "Migrations complete."
}

# ── Pre-migration backup gate ─────────────────────────────────────────────────
# prod always requires it; other modes only when explicitly opted in.
if [[ "$MODE" == "prod" || "$PRE_MIGRATION_BACKUP" == "1" ]]; then
  ensure_pre_migration_backup
else
  echo "[migrate] pre-migration backup skipped (mode: $MODE)."
  echo "          Opt in with PRE_MIGRATION_BACKUP=1 or --pre-migration-backup."
fi

if [[ "$RUN_MODE" == "host" ]]; then
  run_host
else
  run_docker
fi
