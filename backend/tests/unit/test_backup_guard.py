"""Backup safety guard: fail fast in prod with backups off unless acknowledged."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.backups.guard import BackupPolicyError, enforce_backup_policy


def _settings(*, env: str, enabled: bool, accept: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        agent_space_env=env,
        backup_enabled=enabled,
        backup_accept_no_backup=accept,
    )


def test_prod_with_backups_disabled_and_unacknowledged_fails_fast():
    with pytest.raises(BackupPolicyError):
        enforce_backup_policy(_settings(env="prod", enabled=False, accept=False))


def test_prod_with_backups_disabled_but_acknowledged_is_allowed():
    # Must not raise.
    enforce_backup_policy(_settings(env="prod", enabled=False, accept=True))


def test_prod_with_backups_enabled_is_allowed():
    enforce_backup_policy(_settings(env="prod", enabled=True))


@pytest.mark.parametrize("env", ["dev", "test", "", "PROD-ish-but-not-prod"])
def test_non_prod_with_backups_disabled_warns_but_allows(env):
    """Non-prod with backups off must not raise, and must emit a warning.

    Captures via a dedicated handler and resets ``logging.disable`` so the test is
    immune to global logging state left behind by other tests in the suite.
    """
    import logging

    logger = logging.getLogger("app.backups.guard")
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _Capture(level=logging.WARNING)
    prev_level = logger.level
    prev_propagate = logger.propagate
    prev_disabled = logger.disabled  # alembic fileConfig may have disabled it
    prev_disable = logging.root.manager.disable

    logging.disable(logging.NOTSET)
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    logger.disabled = False
    try:
        enforce_backup_policy(_settings(env=env, enabled=False))
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prev_level)
        logger.propagate = prev_propagate
        logger.disabled = prev_disabled
        logging.disable(prev_disable)

    messages = [r.getMessage().lower() for r in records]
    assert any("backup" in m for m in messages), messages


def test_prod_case_insensitive_env_still_fails_fast():
    with pytest.raises(BackupPolicyError):
        enforce_backup_policy(_settings(env="PROD", enabled=False, accept=False))
