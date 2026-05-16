# Operations and Safety

See also: [docs/BACKUP_AND_RESTORE.md](../../docs/BACKUP_AND_RESTORE.md) and [docs/TWO_PERSON_DOGFOODING_RC.md](../../docs/TWO_PERSON_DOGFOODING_RC.md).

## Data Root

All runtime data lives under `AGENT_SPACE_HOME` (default: `~/aspace/dev` for dev mode). Never store runtime data in the source repository.

```
AGENT_SPACE_HOME/
  db/          SQLite database (all spaces, memory, proposals, runs, activity, etc.)
  storage/     Artifact storage files
  secrets/     Encrypted provider key files (AES key, CLI credentials)
  config/      Runtime configuration
  workspaces/  Workspace metadata
  backups/     Backup archives (auto-pruned to BACKUP_RETENTION_COUNT)
  logs/        Application logs (optional; excluded from backup by default)
  sandboxes/   Ephemeral sandbox state (never backed up)
  cache/        Ephemeral cache (never backed up)
```

## Backup — Primary: BackupService

`BackupService` (`core/backend/app/backups/service.py`) is the authoritative backup mechanism. It runs automatically on schedule and writes a structured manifest into every archive.

**Enable in `AGENT_SPACE_HOME/<mode>/.env`:**

```
BACKUP_ENABLED=true
BACKUP_INTERVAL_HOURS=24
BACKUP_RETENTION_COUNT=7
BACKUP_INCLUDE_LOGS=false
BACKUP_ON_STARTUP=true
```

Without `BACKUP_ENABLED=true`, no automatic backups are created. For dogfooding, this setting is required.

**What is backed up:**

| Directory | Included |
|---|---|
| `db/` — SQLite database | Always |
| `storage/` — artifact files | Always |
| `secrets/` — encrypted key files | Always |
| `config/` — runtime config | Always |
| `workspaces/` — workspace metadata | Always |
| `backups/` — previous archives | **Never** (recursion prevention) |
| `sandboxes/` — ephemeral sandbox | **Never** |
| `cache/` — ephemeral cache | **Never** |
| `logs/` — application logs | Only if `BACKUP_INCLUDE_LOGS=true` |

**SQLite consistency:** `BackupService` uses `sqlite3.Connection.backup()` (WAL-safe, live). No raw file-copy fallback — raw copy may miss WAL tail.

**Archive naming:**
- Auto: `AGENT_SPACE_HOME/backups/auto-YYYYMMDD-HHMMSS.tar.gz`
- Manual: `AGENT_SPACE_HOME/backups/manual-YYYYMMDD-HHMMSS.tar.gz`
- Fallback script: `AGENT_SPACE_HOME/backups/fallback-<timestamp>.tar.gz`

**Local overlap protection:** `backups/.backup.lock` (advisory, fcntl-based). Fails closed if sqlite backup API fails.

**Retention:** Latest `BACKUP_RETENTION_COUNT` auto archives kept; older pruned. Manual archives never pruned automatically.

**Every BackupService archive contains `backup_manifest.json`** with format version, kind, timestamp, source root, included/excluded paths, db snapshot method, and warnings.

**Manual trigger:**
```bash
curl -X POST http://localhost:8000/api/v1/system/backups/manual -H "X-API-Key: <key>"
```

## Backup — Fallback: backup.sh

Use `scripts/backup.sh` **only** when the backend is not running (offline emergency):

```bash
./scripts/backup.sh --mode dev
./scripts/backup.sh --mode prod
./scripts/backup.sh --dry-run
./scripts/backup.sh --include-logs
```

Fallback archives appear in the same `backups/` directory as service archives. The shell script does **not** write `backup_manifest.json`.

## Restore

Restore is always **manual and explicit**. There is no automatic restore.

```bash
# 1. Stop any running instance
docker compose -f deployments/local/docker-compose.dev.yml stop

# 2. Restore (requires --force to overwrite existing data root)
./scripts/restore.sh ~/aspace/dev/backups/auto-<timestamp>.tar.gz --mode dev

# 3. Restart
./scripts/start.sh
```

`--force` removes the existing data root before extracting. All current data is replaced.

**After restore, verify before resuming writes:**
1. `curl -s http://localhost:8000/health` — expected: `{"status": "ok"}`
2. Spaces and users readable.
3. Memory, artifacts, proposals, and runs readable.
4. Activity inbox survives.
5. RunStep replay survives for a known run.

## Object Lifecycle States

| State | Meaning |
|---|---|
| `active` | Normal, readable, participates in queries and UI by default |
| `hidden` | Not shown in default queries but recoverable |
| `archived` | Removed from active use; preserved for audit; not in default reads |
| `stale` | Path or dependency unavailable; metadata preserved; recoverable |
| `superseded` | A newer version exists; old row kept for provenance |
| `pending_delete` | Marked for deletion; awaiting approval, retention period, or review gate |
| `deleted` | Soft-deleted; row retained for audit; content may be redacted |
| `redacted` | Content replaced with tombstone; identity and timestamps preserved |

## Archive, Delete, and Hard Delete

- **Archive** — marks object `archived`. Reversible. Full provenance preserved. Not shown in default reads.
- **Soft delete** — marks status `deleted`. Row retained for audit. Content may be redacted.
- **Hard delete** — permanently removes row and linked files. **Not exposed through any public API.** Reserved for legal compliance only, requiring `pending_delete` → review → execute sequence.

## Workspace Lifecycle

Missing workspace paths: `POST /workspaces/scan` marks workspace `stale`, **never** hard-deletes. All metadata (id, name, tasks, runs, artifacts, proposals, audit references) is fully preserved.

Operator restores a stale workspace: `PATCH /workspaces/{id}` setting `status=active`.

## Deployment Boundary

- App container does not restart or rebuild itself.
- Deployment actions route through the host-level deployer via Unix domain socket only (not public TCP).
- Deployer `ALLOWED_JOB_TYPES`: `rebuild_agent_space`, `restart_agent_space`, `health_check`. No arbitrary shell.
- `POST /deployments/jobs` returns 501. Deployment job persistence is not implemented. Operators use manual deployment scripts.

## Self-Evolution Default Off

- `register_system_core_workspace` is called only when `ENABLE_SYSTEM_EVOLUTION=true`.
- The public workspace create API rejects `workspace_type="system_core"` requests.
- Disabled in all deployment configurations by default.
- Do not change `ENABLE_SYSTEM_EVOLUTION` for dogfooding.

## Stop Conditions

Dogfooding must stop immediately on any of these:

1. Cross-user private-space data leak.
2. Household membership access bypass.
3. Memory write bypasses proposal or active policy boundary.
4. Accepted active Policy row does not affect its enforcement decision.
5. RunStep replay missing for a completed canonical-path run.
6. Raw secret in run output, RunStep, artifact, logs, or UI.
7. BackupService fails repeatedly (no `backup_manifest.json` after two intervals).
8. Restore rehearsal fails or key data missing after restore.
9. Workspace scan hard-deletes metadata instead of marking stale.
10. Deployer accepts a job type not in `ALLOWED_JOB_TYPES`.
11. Self-evolution executes behavior changes without approved proposal and deployer gate.
12. Code patch partial apply with rollback failure.
13. Database transaction produces partial inconsistent active state.

## Rollback Procedure

1. Stop writes: `docker compose stop backend worker`.
2. Snapshot current state: `cp -a ~/aspace/dev ~/aspace/dev-pre-rollback-$(date +%Y%m%d-%H%M%S)`.
3. Identify known-good revision: `git log --oneline -10`.
4. Revert app: `git checkout <known-good-commit>`.
5. If data integrity is suspect, restore from last known-good backup (not the latest, which may already contain the problem).
6. Disable implicated surface in `.env`.
7. File incident note: `.agent/incidents/YYYYMMDD-<slug>.md`.
8. Re-run failing gate tests. Do not resume until they pass.

## Security Notes

- Backup archives include `secrets/provider_keys.key` — treat archives as sensitive material.
- Archive permissions: `600` (owner only). Output directory: `700`.
- No raw secret values are written to stdout, logs, or manifests.
- For offsite storage: `gpg --symmetric <archive.tar.gz>` before transferring.
