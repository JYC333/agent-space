"""BackupManifest — written as backup_manifest.json inside every backup archive."""
from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class BackupManifest:
    backup_format: str = "agent-space-backup.v1"
    kind: str = "auto"
    created_at: str = ""
    source_root: str = ""
    included_paths: list[str] = field(default_factory=list)
    excluded_paths: list[str] = field(default_factory=list)
    db_snapshot_method: str = "sqlite-backup-api"
    backup_interval_hours: int = 24
    backup_retention_count: int = 7
    warnings: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(
            {
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
            },
            indent=2,
        )
