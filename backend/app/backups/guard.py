"""Backup safety guard for dogfood/prod environments.

`BackupService` defaults to disabled (`BACKUP_ENABLED=false`), which is correct
for CI and tests. Running a prod-like deployment with no automatic backups,
however, is a data-loss hazard. This guard enforces a clear policy at startup:

  - `AGENT_SPACE_ENV=prod` + backups disabled  -> fail fast, unless the operator
    explicitly acknowledges with `BACKUP_ACCEPT_NO_BACKUP=true`.
  - any other env + backups disabled            -> emit a strong startup warning.
  - backups enabled                             -> no-op.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


class BackupPolicyError(RuntimeError):
    """Raised when a prod environment starts with backups disabled and unacknowledged."""


def enforce_backup_policy(settings) -> None:
    """Enforce the backup safety policy. Raises BackupPolicyError to fail fast."""
    if settings.backup_enabled:
        return

    env = (settings.agent_space_env or "").strip().lower()

    if env == "prod":
        if settings.backup_accept_no_backup:
            log.warning(
                "BACKUP DISABLED in prod: AGENT_SPACE_ENV=prod with BACKUP_ENABLED=false. "
                "Proceeding because BACKUP_ACCEPT_NO_BACKUP=true. No automatic backups "
                "will be taken — you are responsible for an external backup strategy."
            )
            return
        raise BackupPolicyError(
            "Refusing to start: AGENT_SPACE_ENV=prod but BACKUP_ENABLED=false. "
            "Automatic backups are off, which risks unrecoverable data loss. "
            "Set BACKUP_ENABLED=true to enable scheduled pg_dump backups, or set "
            "BACKUP_ACCEPT_NO_BACKUP=true to explicitly run without them."
        )

    log.warning(
        "Automatic backups are DISABLED (BACKUP_ENABLED=false, AGENT_SPACE_ENV=%s). "
        "This is fine for tests/CI, but enable backups before any real dogfooding data.",
        env or "unset",
    )
