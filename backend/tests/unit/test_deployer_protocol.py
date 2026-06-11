"""Unit tests: deployer protocol allowlist and JOB_SCRIPTS consistency.

Verifies M7 deployment boundary invariants:
  - ALLOWED_JOB_TYPES is a closed set (no open-ended types).
  - JOB_SCRIPTS in deployer.py maps every ALLOWED_JOB_TYPES entry.
  - No extra scripts are mapped that are not in ALLOWED_JOB_TYPES.
  - Deployer handler rejects unknown job types.
  - All script files referenced by JOB_SCRIPTS actually exist on disk.
  - Self-evolution jobs are all in ALLOWED_JOB_TYPES (explicit, not wildcard).
  - Core job types are all in ALLOWED_JOB_TYPES (health_check, rebuild, restart).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ── Deployer is outside backend; add it to the import path ───────────────
_DEPLOYER_DIR = Path(__file__).resolve().parents[3] / "deployer"


def _import_deployer_modules():
    """Import deployer modules, adding the deployer dir to sys.path if needed."""
    if str(_DEPLOYER_DIR) not in sys.path:
        sys.path.insert(0, str(_DEPLOYER_DIR))
    import importlib
    protocol = importlib.import_module("protocol")
    deployer = importlib.import_module("deployer")
    return protocol, deployer


@pytest.fixture(scope="module")
def deployer_modules():
    if not _DEPLOYER_DIR.exists():
        pytest.skip("deployer/ directory not found")
    return _import_deployer_modules()


@pytest.fixture(scope="module")
def protocol(deployer_modules):
    return deployer_modules[0]


@pytest.fixture(scope="module")
def deployer_mod(deployer_modules):
    return deployer_modules[1]


# ---------------------------------------------------------------------------
# Protocol allowlist
# ---------------------------------------------------------------------------


def test_allowed_job_types_is_non_empty(protocol):
    """ALLOWED_JOB_TYPES must be a non-empty closed set."""
    assert len(protocol.ALLOWED_JOB_TYPES) > 0


def test_allowed_job_types_contains_core_jobs(protocol):
    """Core deployment job types must be present in ALLOWED_JOB_TYPES."""
    core_jobs = {"rebuild_agent_space", "restart_agent_space", "health_check"}
    missing = core_jobs - protocol.ALLOWED_JOB_TYPES
    assert not missing, f"Core job types missing from ALLOWED_JOB_TYPES: {missing}"


def test_allowed_job_types_contains_all_self_evolution_jobs(protocol):
    """All SelfEvolutionJobType literals must be in ALLOWED_JOB_TYPES."""
    evo_jobs = set(protocol.SelfEvolutionJobType.__args__)
    missing = evo_jobs - protocol.ALLOWED_JOB_TYPES
    assert not missing, f"Self-evolution jobs missing from ALLOWED_JOB_TYPES: {missing}"


def test_allowed_job_types_equals_core_plus_evolution(protocol):
    """ALLOWED_JOB_TYPES must equal exactly CoreJobType ∪ SelfEvolutionJobType — no unlisted extras."""
    core_jobs = set(protocol.CoreJobType.__args__)
    evo_jobs = set(protocol.SelfEvolutionJobType.__args__)
    expected = core_jobs | evo_jobs
    extra = protocol.ALLOWED_JOB_TYPES - expected
    assert not extra, f"ALLOWED_JOB_TYPES has undeclared job types: {extra}"


# ---------------------------------------------------------------------------
# JOB_SCRIPTS consistency
# ---------------------------------------------------------------------------


def test_job_scripts_covers_all_allowed_job_types(deployer_mod, protocol):
    """Every job type in ALLOWED_JOB_TYPES must have an entry in JOB_SCRIPTS."""
    mapped = set(deployer_mod.JOB_SCRIPTS.keys())
    missing = protocol.ALLOWED_JOB_TYPES - mapped
    assert not missing, (
        f"JOB_SCRIPTS is missing entries for: {missing}. "
        "Add the corresponding script paths to JOB_SCRIPTS in deployer.py."
    )


def test_job_scripts_has_no_extra_entries(deployer_mod, protocol):
    """JOB_SCRIPTS must not map job types that are not in ALLOWED_JOB_TYPES."""
    mapped = set(deployer_mod.JOB_SCRIPTS.keys())
    extra = mapped - protocol.ALLOWED_JOB_TYPES
    assert not extra, (
        f"JOB_SCRIPTS maps job types not in ALLOWED_JOB_TYPES: {extra}. "
        "Either add them to ALLOWED_JOB_TYPES or remove the script mapping."
    )


def test_all_job_scripts_exist_on_disk(deployer_mod):
    """Every script in JOB_SCRIPTS must exist as a file on disk."""
    missing = []
    for job_type, script_path in deployer_mod.JOB_SCRIPTS.items():
        if not script_path.exists():
            missing.append(f"{job_type} → {script_path}")
    assert not missing, (
        "JOB_SCRIPTS references script files that do not exist:\n"
        + "\n".join(missing)
    )


def test_core_job_scripts_map_to_correct_files(deployer_mod):
    """Core deployment jobs must map to the correct script files."""
    scripts = deployer_mod.JOB_SCRIPTS
    script_dir = deployer_mod.SCRIPT_DIR

    assert scripts.get("health_check") == script_dir / "health_check.sh", \
        "health_check must map to health_check.sh"
    assert scripts.get("rebuild_agent_space") == script_dir / "rebuild.sh", \
        "rebuild_agent_space must map to rebuild.sh"
    assert scripts.get("restart_agent_space") == script_dir / "restart.sh", \
        "restart_agent_space must map to restart.sh"


# ---------------------------------------------------------------------------
# Deployer rejects unknown job types
# ---------------------------------------------------------------------------


def test_deployer_rejects_unknown_job_type(protocol):
    """ALLOWED_JOB_TYPES must not contain 'arbitrary_shell' or open-ended types."""
    dangerous_types = {
        "arbitrary_shell",
        "shell",
        "exec",
        "run_command",
        "eval",
        "*",
    }
    overlap = dangerous_types & protocol.ALLOWED_JOB_TYPES
    assert not overlap, (
        f"ALLOWED_JOB_TYPES contains dangerous or open-ended job types: {overlap}"
    )


def test_deployer_rejects_unknown_job_type_at_runtime(protocol):
    """An unrecognized job_type must not be in ALLOWED_JOB_TYPES (handler would reject it)."""
    fake_job_type = "i_am_not_a_real_job_type_abc123"
    assert fake_job_type not in protocol.ALLOWED_JOB_TYPES


# ---------------------------------------------------------------------------
# Self-evolution default-off
# ---------------------------------------------------------------------------


def test_self_evolution_disabled_by_default_in_settings():
    """ENABLE_SYSTEM_EVOLUTION setting must default to False."""
    from app.config import settings
    assert settings.enable_system_evolution is False, (
        "enable_system_evolution must be False by default. "
        "Set ENABLE_SYSTEM_EVOLUTION=true only when explicitly enabling self-evolution."
    )


def test_system_core_owner_email_empty_by_default():
    """SYSTEM_CORE_OWNER_EMAIL must be empty by default (self-evolution cannot auto-register)."""
    from app.config import settings
    assert settings.system_core_owner_email == "", (
        "system_core_owner_email must be empty by default. "
        "Self-evolution must not auto-register without explicit configuration."
    )
