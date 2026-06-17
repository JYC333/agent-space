export interface BackupManifest {
  backup_format: string;
  kind: string;
  created_at: string;
  source_root: string;
  included_paths: string[];
  excluded_paths: string[];
  db_snapshot_method: string;
  backup_interval_hours: number;
  backup_retention_count: number;
  warnings: string[];
  app_version: string | null;
  git_commit: string | null;
  alembic_revision: string | null;
  postgres_server_version: string | null;
  pg_dump_version: string | null;
}

export function serializeManifest(manifest: BackupManifest): string {
  return JSON.stringify(manifest, null, 2);
}
