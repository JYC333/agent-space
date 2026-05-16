# Backup and Restore — agent-space Local Instance

**Scope:** Local two-person dogfooding instance.

---

## Architecture

Backup is **service-primary**. The backend `BackupService` is the authoritative backup
mechanism. It runs automatically on schedule and writes a structured manifest into every archive.

| Component | Role |
|---|---|
| `BackupService` (`app/backups/service.py`) | Creates archives, prunes old backups, sqlite snapshot |
| `BackupScheduler` (`app/backups/scheduler.py`) | Periodic auto-backup, tied to app lifespan |
| `scripts/backup.sh` | **Fallback only** — use when backend is not running |
| `scripts/restore.sh` | Manual restore — always explicit, always manual |

**Two-person dogfooding must set `BACKUP_ENABLED=true`** (or `backup_enabled: true` in `.env`).
The service defaults to `False` for test safety.

---

## Automatic Backup (Primary)

### Enable

In `~/aspace/<mode>/.env`:

```
BACKUP_ENABLED=true
BACKUP_INTERVAL_HOURS=24
BACKUP_RETENTION_COUNT=7
BACKUP_INCLUDE_LOGS=false
BACKUP_ON_STARTUP=true
```

The backend reads these on startup and starts `BackupScheduler`. No manual action required.
`BACKUP_ON_STARTUP=true` (the default) triggers an immediate backup on first startup, making it
easy to verify that the service is configured and writing archives before any writes occur.

### What is backed up

| Directory | Contents | Included |
|---|---|---|
| `db/` | SQLite database — all memory, proposals, runs, activity, artifacts, policies, run steps | Always |
| `storage/` | Artifact storage files | Always |
| `artifacts/` | Artifact storage root (may overlap `storage/` by config) | Always |
| `config/` | Runtime configuration (no secret values) | Always |
| `secrets/` | Encrypted key files (AES key for provider API keys, CLI credentials) | Always |
| `workspaces/` | Workspace metadata directories | Always |
| `backups/` | Previous backup archives | **Never** (recursion prevention) |
| `sandboxes/` | Ephemeral sandbox state | **Never** (ephemeral) |
| `cache/` | Ephemeral cache | **Never** (ephemeral) |
| `logs/` | Application logs | Optional (`BACKUP_INCLUDE_LOGS=true`) |

**Secrets note:** `secrets/` contains encrypted key files. Raw secret values are never
written to stdout, logs, or the manifest. Archive permissions are set to `600`.

### Archive naming

```
AGENT_SPACE_HOME/backups/auto-YYYYMMDD-HHMMSS.tar.gz    ← automatic
AGENT_SPACE_HOME/backups/manual-YYYYMMDD-HHMMSS.tar.gz  ← manual trigger
```

### backup_manifest.json

Every archive contains `backup_manifest.json` at the root with:

- `backup_format: "agent-space-backup.v1"`
- `kind: "auto" | "manual"`
- `created_at` — ISO timestamp
- `source_root` — absolute path of data root at time of backup
- `included_paths` — list of dirs/files copied
- `excluded_paths` — list of dirs excluded and why
- `db_snapshot_method` — `"sqlite-backup-api"`
- `backup_interval_hours`, `backup_retention_count`
- `warnings` — any non-fatal issues during backup

No raw secret values appear in the manifest.

### SQLite consistency

`BackupService` uses `sqlite3.Connection.backup()` (Python's built-in sqlite3 backup API).
This produces a WAL-safe consistent snapshot of the database even while the backend is live.
It is not necessary to stop the backend before an automatic backup.

If the backup API fails for any reason, the backup fails closed. The service does **not**
fall back to raw SQLite file copy, because raw copy can miss WAL state and produce a
misleading successful archive.

### Local overlap protection

`BackupService` uses an in-process scheduler lock and a local lock file:

```
AGENT_SPACE_HOME/backups/.backup.lock
```

The lock prevents overlapping backups across multiple backend processes on the same host.
If a process crashes, the lock file may remain, but the OS releases the advisory lock when
the process exits. A leftover unlocked file is reused by the next backup.

### Retention

- Auto backups: the latest `BACKUP_RETENTION_COUNT` (default: 7) are kept. Older ones are pruned after each backup run.
- Manual backups: never pruned automatically. Operator must remove manually if desired.
- The backup currently being written is never pruned; pruning takes the same local lock and skips if another backup is active.

### Manual trigger via API

```bash
curl -X POST http://localhost:8000/api/v1/system/backups/manual \
  -H "X-API-Key: <your-api-key>"
# Response: {"status": "ok", "backup": "manual-20260101-120000.tar.gz"}
```

### View backup list

```bash
curl http://localhost:8000/api/v1/system/backups \
  -H "X-API-Key: <your-api-key>"
```

---

## Fallback Shell Script (Offline / Emergency Only)

Use `scripts/backup.sh` only when the backend is not running:

```bash
./scripts/backup.sh                          # dev mode (default)
./scripts/backup.sh --mode prod              # prod mode
./scripts/backup.sh --dry-run               # preview without writing
./scripts/backup.sh --include-logs          # include logs/
./scripts/backup.sh --output /mnt/backups   # custom output directory
```

Archives are written to `AGENT_SPACE_HOME/<mode>/backups/` by default — the same directory
used by `BackupService`. This means fallback archives appear alongside service archives and
can be found in the same place. Archive name: `fallback-<YYYYMMDDTHHMMSSZ>.tar.gz`.

The shell script does **not** write `backup_manifest.json`. For manifested backups, use the backend service.

---

## Restore

Restore is always **manual and explicit**. There is no automatic restore.

### Restore procedure

```bash
# 1. Stop any running instance
docker compose -f deployments/local/docker-compose.yml stop

# 2. Restore (refuses to overwrite existing data root without --force)
./scripts/restore.sh ~/aspace/backups/auto-20260101-120000.tar.gz --mode dev

# 3. Restart
./scripts/start.sh
```

If a data root already exists, `--force` is required:

```bash
./scripts/restore.sh <archive> --mode dev --force
```

`--force` removes the existing data root before extracting — all current data is replaced.

---

## Restore Verification Checklist

After restore, verify before resuming writes:

**1. App starts**
```bash
curl -s http://localhost:8000/health
# Expected: {"status": "ok", ...}
```

**2. Spaces and users visible**
```bash
curl -s "http://localhost:8000/api/v1/spaces?space_id=personal"
```

**3. Memory entries readable**
```bash
curl -s "http://localhost:8000/api/v1/memory?space_id=personal&status=active"
```

**4. Artifacts readable**
```bash
curl -s "http://localhost:8000/api/v1/artifacts?space_id=personal"
```

**5. Proposals and runs inspectable**
```bash
curl -s "http://localhost:8000/api/v1/proposals?space_id=personal"
curl -s "http://localhost:8000/api/v1/runs?space_id=personal"
```

**6. Activity inbox survives**
```bash
curl -s "http://localhost:8000/api/v1/activity?space_id=personal"
```

**7. RunStep replay survives**
```bash
curl -s "http://localhost:8000/api/v1/runs/<run_id>/steps?space_id=personal"
```

---

## Rollback Strategy

1. Stop writes: `docker compose stop backend`.
2. Snapshot current state before overwriting: `cp -a ~/aspace/dev ~/aspace/dev-pre-rollback`.
3. Restore from last known-good archive: `./scripts/restore.sh <archive> --mode dev --force`.
4. Verify with checklist above.
5. Restart: `./scripts/start.sh`.

---

## Security Considerations

- Archives contain `secrets/provider_keys.key` — treat archives as sensitive material.
- Archive permissions: `600` (owner only). Output directory: `700`.
- No archive passphrase by default. For offsite storage: `gpg --symmetric <archive.tar.gz>`.
- Raw secret values are never printed to stdout or written to the manifest.

---

## Residual Risks

| Risk | Mitigation |
|---|---|
| Automatic backup requires `BACKUP_ENABLED=true` — not set, no backups | Dogfood operators must set this in `.env` before first write |
| `BackupService` fails closed when `sqlite3.backup()` raises — **no** raw DB file-copy fallback in the tarball | Fix the underlying SQLite/locking error before retrying; archives are only produced on full success |
| `workspaces/` captures directory structure, not external mount contents | Document external dependencies separately |
| No cloud backup or offsite replication | Manual GPG + offsite upload if required |
| No `backup_manifest.json` from shell script fallback | Shell script is for offline emergencies only; use the backend service for manifested backups |

---

## Implementation Notes

- `BackupService`: `core/backend/app/backups/service.py` — creates archives, sqlite backup API, prunes
- `BackupScheduler`: `core/backend/app/backups/scheduler.py` — periodic auto-backup, lifespan-tied
- `BackupManifest`: `core/backend/app/backups/manifest.py` — structured `backup_manifest.json`
- Backup API: `GET /api/v1/system/backups`, `POST /api/v1/system/backups/manual`
- `scripts/backup.sh`: fallback emergency tool only
- `scripts/restore.sh`: manual restore tool
- Workspace scan: missing paths marked `stale`, not hard-deleted
- Deployment job persistence: `501 Not Implemented` (deferred, documented)
- Self-evolution: disabled by default (`ENABLE_SYSTEM_EVOLUTION=false`)
