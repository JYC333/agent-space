"""BackupManifest — written as backup_manifest.json inside every backup archive."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BackupManifest:
    backup_format: str = "agent-space-backup.v1"
    kind: str = "auto"
    created_at: str = ""
    source_root: str = ""
    included_paths: list[str] = field(default_factory=list)
    excluded_paths: list[str] = field(default_factory=list)
    db_snapshot_method: str = "pg_dump_custom"
    backup_interval_hours: int = 24
    backup_retention_count: int = 7
    warnings: list[str] = field(default_factory=list)
    # ── Version metadata (canonical PostgreSQL baseline) ───────────────────────
    # Recorded so restore can validate compatibility. None when a value cannot be
    # determined in the current environment.
    app_version: Optional[str] = None
    git_commit: Optional[str] = None
    alembic_revision: Optional[str] = None
    postgres_server_version: Optional[str] = None
    pg_dump_version: Optional[str] = None

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    def to_dict(self) -> dict:
        return {
            "backup_format": self.backup_format,
            "kind": self.kind,
            "created_at": self.created_at,
            "source_root": self.source_root,
            "included_paths": self.included_paths,
            "excluded_paths": self.excluded_paths,
            "db_snapshot_method": self.db_snapshot_method,
            "backup_interval_hours": self.backup_interval_hours,
            "backup_retention_count": self.backup_retention_count,
            "warnings": self.warnings,
            "app_version": self.app_version,
            "git_commit": self.git_commit,
            "alembic_revision": self.alembic_revision,
            "postgres_server_version": self.postgres_server_version,
            "pg_dump_version": self.pg_dump_version,
        }
