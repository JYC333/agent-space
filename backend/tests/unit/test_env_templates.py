"""Static guards for local env templates and production password safety."""
from __future__ import annotations

import shlex
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
OPS_DIR = REPO_ROOT / "ops"
ENV_DIR = OPS_DIR / "env"
START_SH = OPS_DIR / "scripts" / "start.sh"
LOCAL_COMPOSE_HELPER = OPS_DIR / "scripts" / "lib" / "local-compose.sh"
LOCAL_COMPOSE_SCRIPTS = [
    START_SH,
    OPS_DIR / "scripts" / "db" / "migrate.sh",
    OPS_DIR / "scripts" / "db" / "reset-postgres.sh",
    OPS_DIR / "scripts" / "db" / "dump.sh",
    OPS_DIR / "scripts" / "db" / "restore.sh",
    OPS_DIR / "scripts" / "db" / "shell.sh",
    OPS_DIR / "scripts" / "system" / "backup.sh",
    OPS_DIR / "scripts" / "system" / "restore.sh",
    OPS_DIR / "scripts" / "system" / "verify-restore.sh",
]
DEV_PASSWORD = "agent_space_dev_password"


def test_mode_specific_env_templates_exist():
    for mode in ("dev", "test", "prod"):
        assert (ENV_DIR / f".env.{mode}.example").is_file()


def test_dev_and_test_templates_keep_local_postgres_defaults():
    for mode in ("dev", "test"):
        text = (ENV_DIR / f".env.{mode}.example").read_text()
        assert f"POSTGRES_PASSWORD={DEV_PASSWORD}" in text
        assert "POSTGRES_MAJOR=18" in text


def test_prod_template_does_not_contain_development_postgres_password():
    text = (ENV_DIR / ".env.prod.example").read_text()
    assert DEV_PASSWORD not in text
    assert "POSTGRES_PASSWORD=REPLACE_ME_WITH_STRONG_PASSWORD" in text


def test_env_templates_declare_control_plane_defaults():
    for mode in ("dev", "test", "prod"):
        text = (ENV_DIR / f".env.{mode}.example").read_text()
        assert "CONTROL_PLANE_HOST=0.0.0.0" in text
        assert "CONTROL_PLANE_PORT=8010" in text
        assert "CONTROL_PLANE_ENABLE_LEGACY_PROXY=true" in text
        assert "CONTROL_PLANE_LOG_LEVEL=info" in text
        assert "CONTROL_PLANE_REQUEST_TIMEOUT_MS=300000" in text
        assert "LEGACY_PYTHON_API_BASE_URL=http://backend:8000" in text

    for mode in ("dev", "test"):
        text = (ENV_DIR / f".env.{mode}.example").read_text()
        assert "CONTROL_PLANE_API_URL=http://control-plane:8010" in text


def test_start_prod_rejects_development_and_placeholder_passwords():
    text = START_SH.read_text()
    assert 'ENV_TEMPLATE="$ENV_DIR/.env.$MODE.example"' in text
    assert '"$MODE" == "prod"' in text
    assert "local_compose_env_value POSTGRES_PASSWORD" in text
    assert DEV_PASSWORD in text
    assert "development password" in text
    assert "placeholder" in text
    assert "replace_me" in text


def test_local_compose_helper_centralizes_mode_root_and_compose_command():
    text = LOCAL_COMPOSE_HELPER.read_text()
    assert "dev|test|prod" in text
    assert 'COMPOSE_DIR="$REPO_ROOT/ops/compose"' in text
    assert 'ENV_DIR="$REPO_ROOT/ops/env"' in text
    assert 'ASPACE_ROOT="${ASPACE_ROOT:-$HOME/.aspace}"' in text
    assert 'MODE_ROOT="$ASPACE_ROOT/$MODE"' in text
    assert 'ENV_FILE="$MODE_ROOT/.env"' in text
    assert 'COMPOSE_PROJECT="agent-space-$MODE"' in text
    assert 'COMPOSE_FILE="$COMPOSE_DIR/docker-compose.$MODE.yml"' in text
    assert 'export AGENT_SPACE_MODE_ROOT="$MODE_ROOT"' in text
    assert 'COMPOSE=(docker compose --env-file "$ENV_FILE" -p "$COMPOSE_PROJECT" -f "$COMPOSE_FILE")' in text


def test_db_system_scripts_use_shared_compose_helper_and_do_not_source_env():
    for script in LOCAL_COMPOSE_SCRIPTS:
        text = script.read_text()
        assert "local-compose.sh" in text, f"{script} must source the shared helper"
        assert 'local_compose_init "$MODE"' in text, f"{script} must initialize shared compose state"
        assert 'source "$ENV_FILE"' not in text
        assert "set -a" not in text

    for script in LOCAL_COMPOSE_SCRIPTS:
        text = script.read_text()
        if script == LOCAL_COMPOSE_HELPER:
            continue
        assert '"${COMPOSE[@]}"' in text, f"{script} must use the shared compose array"


def test_local_compose_dotenv_parser_supports_simple_unexecuted_values(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join([
            "# comments and blanks are ignored",
            "",
            "POSTGRES_DB=agent_space_test",
            'POSTGRES_USER="quoted_user"',
            "POSTGRES_PASSWORD='quoted password'",
            "BACKUP_INTERVAL_HOURS=12 # inline comment",
        ]),
        encoding="utf-8",
    )

    script = "\n".join([
        "set -euo pipefail",
        f"source {shlex.quote(str(LOCAL_COMPOSE_HELPER))}",
        f"ENV_FILE={shlex.quote(str(env_file))}",
        "local_compose_env_value POSTGRES_DB",
        "local_compose_env_value POSTGRES_USER",
        "local_compose_env_value POSTGRES_PASSWORD",
        "local_compose_env_value BACKUP_INTERVAL_HOURS",
    ])
    result = subprocess.run(
        ["bash", "-lc", script],
        check=True,
        text=True,
        capture_output=True,
    )

    assert result.stdout.splitlines() == [
        "agent_space_test",
        "quoted_user",
        "quoted password",
        "12",
    ]
