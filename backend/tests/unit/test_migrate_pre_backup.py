"""Static guards for ops/scripts/db/migrate.sh pre-migration backup safety.

For --mode prod a pre-migration pg_dump custom-format backup must be taken before
Alembic runs, written under $ASPACE_ROOT/<mode>/db/dumps/pre-migrate-<ts>.dump,
and migration must abort if that dump fails. Non-prod modes stay convenient but
must document how to opt into the same dump.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
OPS_SCRIPTS = REPO_ROOT / "ops" / "scripts"
MIGRATE_SH = OPS_SCRIPTS / "db" / "migrate.sh"
RESET_SH = OPS_SCRIPTS / "db" / "reset-postgres.sh"
DUMP_SH = OPS_SCRIPTS / "db" / "dump.sh"
RESTORE_SH = OPS_SCRIPTS / "db" / "restore.sh"
SYSTEM_BACKUP_SH = OPS_SCRIPTS / "system" / "backup.sh"
SYSTEM_RESTORE_SH = OPS_SCRIPTS / "system" / "restore.sh"
SYSTEM_VERIFY_SH = OPS_SCRIPTS / "system" / "verify-restore.sh"
LOCAL_COMPOSE_HELPER = OPS_SCRIPTS / "lib" / "local-compose.sh"


def _text() -> str:
    return MIGRATE_SH.read_text()


def test_migrate_script_exists_and_is_postgres_only():
    text = _text()
    assert "alembic upgrade head" in text
    assert "PostgreSQL is the server database" in text


def test_prod_requires_pre_migration_backup_before_alembic():
    text = _text()
    # prod (or explicit opt-in) gates the backup.
    assert re.search(r'MODE"\s*==\s*"prod"', text), "prod must trigger the pre-migration backup"
    assert "ensure_pre_migration_backup" in text

    # The backup gate must appear before the migration dispatch (run_host/run_docker).
    gate_idx = text.index("ensure_pre_migration_backup\nelse") if "ensure_pre_migration_backup\nelse" in text else text.rindex("ensure_pre_migration_backup")
    dispatch_idx = text.rindex("run_docker")
    assert gate_idx < dispatch_idx, "backup gate must run before Alembic dispatch"


def test_pre_migration_backup_uses_custom_format_dump_path():
    text = _text()
    assert "pre-migrate-" in text and ".dump" in text
    assert "db/dumps" in text
    # custom-format pg_dump
    assert "-Fc" in text and "pg_dump" in text


def test_pre_migration_backup_aborts_on_failure():
    text = _text()
    # Empty/failed dump must abort before Alembic.
    assert re.search(r"-s\s+\"\$dump_path\"", text)
    assert "Aborting BEFORE Alembic" in text


def test_non_prod_opt_in_is_documented():
    text = _text()
    assert "PRE_MIGRATION_BACKUP" in text
    assert "--pre-migration-backup" in text


def test_credentials_are_not_printed():
    text = _text()
    assert "credentials-redacted" in text


def test_migrate_test_mode_uses_shared_compose_env_resolution():
    text = _text()
    assert "local-compose.sh" in text
    assert 'local_compose_init "$MODE"' in text
    assert '"${COMPOSE[@]}"' in text
    assert 'COMPOSE_PROJECT="agent-space-dev"' not in text
    assert 'COMPOSE_FILE="$COMPOSE_DIR/docker-compose.dev.yml"' not in text
    assert 'source "$ENV_FILE"' not in text
    assert "set -a" not in text


def test_local_compose_helper_centralizes_postgres_lifecycle():
    text = LOCAL_COMPOSE_HELPER.read_text()
    assert "LOCAL_COMPOSE_POSTGRES_STARTED=false" in text
    assert "local_compose_service_running()" in text
    assert "local_compose_ensure_postgres()" in text
    assert "local_compose_wait_postgres_ready()" in text
    assert "local_compose_ensure_postgres_ready()" in text
    assert "local_compose_stop_postgres_if_started()" in text
    assert '"${COMPOSE[@]}" up -d postgres' in text
    assert '"${COMPOSE[@]}" stop postgres' in text
    assert "pg_isready" in text


def test_migrate_stops_only_postgres_it_started():
    text = _text()
    assert 'local_compose_ensure_postgres_ready "migration"' in text
    assert 'local_compose_stop_postgres_if_started "migrate"' in text
    assert "POSTGRES_STARTED_BY_" not in text
    assert "ensure_postgres_for_migration" not in text


def test_reset_starts_and_stops_only_postgres_it_started():
    text = RESET_SH.read_text()
    assert 'local_compose_ensure_postgres_ready "reset" "$PGUSER"' in text
    assert 'local_compose_stop_postgres_if_started "reset"' in text
    assert "POSTGRES_STARTED_BY_" not in text
    assert "ensure_postgres_for_reset" not in text
    assert "wait_postgres_ready_for_reset" not in text
    assert "Start postgres only:" not in text
    assert "keep postgres running" not in text


def test_dump_starts_and_stops_only_postgres_it_started():
    text = DUMP_SH.read_text()
    assert 'local_compose_ensure_postgres_ready "dump" "$PGUSER"' in text
    assert 'local_compose_stop_postgres_if_started "dump"' in text
    assert "POSTGRES_STARTED_BY_" not in text
    assert "ensure_postgres_for_dump" not in text
    assert "wait_postgres_ready_for_dump" not in text
    assert "Start postgres only:" not in text
    assert "postgres service is not running" not in text

    start_idx = text.index('local_compose_ensure_postgres_ready "dump" "$PGUSER"')
    dump_idx = text.index("pg_dump -U")
    assert start_idx < dump_idx


def test_restore_starts_and_stops_only_postgres_it_started_before_validation():
    text = RESTORE_SH.read_text()
    assert 'local_compose_ensure_postgres_ready "restore" "$PGUSER"' in text
    assert 'local_compose_stop_postgres_if_started "restore"' in text
    assert "POSTGRES_STARTED_BY_" not in text
    assert "ensure_postgres_for_restore" not in text
    assert "wait_postgres_ready_for_restore" not in text
    assert "Start postgres only:" not in text
    assert "keep postgres running" not in text

    start_idx = text.index('local_compose_ensure_postgres_ready "restore" "$PGUSER"')
    validate_idx = text.index("pg_restore --list")
    warning_idx = text.index('echo "WARNING: This will overwrite')
    assert start_idx < validate_idx < warning_idx


def test_system_backup_starts_and_stops_only_postgres_it_started():
    text = SYSTEM_BACKUP_SH.read_text()
    assert 'local_compose_ensure_postgres_ready "backup" "$PGUSER"' in text
    assert 'local_compose_stop_postgres_if_started "backup"' in text
    assert "POSTGRES_STARTED_BY_" not in text
    assert "Start postgres only:" not in text
    assert "postgres service is not running" not in text
    assert "backup will manage postgres as needed" in text

    start_idx = text.index('local_compose_ensure_postgres_ready "backup" "$PGUSER"')
    dump_idx = text.index("pg_dump -U")
    assert start_idx < dump_idx


def test_system_restore_starts_and_stops_only_postgres_it_started_before_validation():
    text = SYSTEM_RESTORE_SH.read_text()
    assert 'local_compose_ensure_postgres_ready "restore" "$PGUSER"' in text
    assert 'local_compose_stop_postgres_if_started "restore"' in text
    assert "POSTGRES_STARTED_BY_" not in text
    assert "Start postgres only:" not in text
    assert "keep postgres running" not in text

    start_idx = text.index('local_compose_ensure_postgres_ready "restore" "$PGUSER"')
    validate_idx = text.index("pg_restore --list")
    warning_idx = text.index('echo "WARNING: this overwrites')
    assert start_idx < validate_idx < warning_idx


def test_system_verify_starts_and_stops_only_postgres_it_started():
    text = SYSTEM_VERIFY_SH.read_text()
    assert 'local_compose_ensure_postgres_ready "verify" "$PGUSER"' in text
    assert 'local_compose_stop_postgres_if_started "verify"' in text
    assert "POSTGRES_STARTED_BY_" not in text
    assert "Start postgres only:" not in text
    assert "postgres service is not running" not in text

    start_idx = text.index('local_compose_ensure_postgres_ready "verify" "$PGUSER"')
    query_idx = text.index('psql_query "SELECT to_regclass')
    assert start_idx < query_idx


def test_system_verify_does_not_check_http_health():
    text = SYSTEM_VERIFY_SH.read_text()
    assert "--api-base-url" not in text
    assert "curl " not in text
    assert "HTTP health" not in text
    assert "/health" not in text
    assert "http://localhost:8000" not in text
    assert "http://localhost:8100" not in text
